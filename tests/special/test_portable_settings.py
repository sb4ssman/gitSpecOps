"""Portable policy/behavior stays separate from machine bindings; no profile or transport I/O.

    python tests/special/test_portable_settings.py
"""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup
setup()

from Special._settings import SettingsError, resolve_document
from Special._settings.portable import PortableSettings, merge_portable, portable_settings


class PortableTests(unittest.TestCase):
    def document(self):
        home = Path.cwd().anchor
        return {"schema_version": 2,
                "machine": {"id": "machine-a", "label": "local-label", "fleet_secret": "0" * 64},
                "transports": {"folder": {"path": home}},
                "defaults": {"scope": {"roots": [home], "exclude_paths": [str(Path(home) / "excluded")]},
                             "output": {"mode": "both", "format": "json", "directory": "local-reports"},
                             "logging": {"directory": "local-logs", "enabled": False},
                             "security": {"never_publish": ["master-private-marker"],
                                          "local_never_publish": ["machine-private-marker"],
                                          "local_safe_values": ["local-allowance"], "engines": ["gitleaks"]}},
                "components": {"sync": {"options": {"transport_names": ["folder"], "stale_hours": 12}},
                               "archive_manage": {"options": {"archives": [
                                   {"root": home, "mode": "update", "approved_remote_prefixes": []}]}}}}

    def test_projection_contains_policy_and_behavior_but_no_machine_bindings(self):
        document = self.document()
        before = copy.deepcopy(document)
        portable = portable_settings(document)
        raw = portable.raw_record()
        encoded = json.dumps(raw)
        self.assertIn("master-private-marker", encoded)
        for private in ("machine-private-marker", "local-allowance", "local-label", "local-reports", "local-logs", "0" * 64):
            self.assertNotIn(private, encoded)
        for key in ("machine", "transports", "scope", "transport_names", "archives"):
            self.assertNotIn(f'"{key}":', encoded)
        self.assertEqual(raw["settings"]["defaults"]["security"]["engines"], ["gitleaks"])
        self.assertEqual(raw["settings"]["components"]["sync"]["options"], {"stale_hours": 12})
        self.assertEqual(document, before)

    def test_summary_and_repr_hide_shared_policy_values(self):
        value = portable_settings(self.document())
        self.assertNotIn("master-private-marker", json.dumps(value.summary()))
        self.assertNotIn("master-private-marker", repr(value))
        self.assertTrue(value.summary()["requires_private_transport"])
        self.assertFalse(value.summary()["writes_settings"])

    def test_merge_preserves_local_fields_and_does_not_mutate_either_input(self):
        local = self.document()
        shared = portable_settings({"schema_version": 2, "defaults": {
            "output": {"mode": "stdout"}, "security": {"never_publish": ["new-master-marker"], "engines": []}}}).raw_record()
        before = copy.deepcopy((local, shared))
        result = merge_portable(local, shared)
        self.assertEqual(result["machine"], local["machine"])
        self.assertEqual(result["transports"], local["transports"])
        self.assertEqual(result["defaults"]["scope"], local["defaults"]["scope"])
        self.assertEqual(result["defaults"]["output"], {"mode": "stdout", "directory": "local-reports"})
        self.assertEqual(result["defaults"]["security"]["local_never_publish"], ["machine-private-marker"])
        self.assertEqual(result["defaults"]["security"]["never_publish"], ["new-master-marker"])
        self.assertEqual(result["components"]["archive_manage"], local["components"]["archive_manage"])
        self.assertEqual(result["components"]["sync"]["options"], {"transport_names": ["folder"]})
        self.assertEqual((local, shared), before)

    def test_machine_allowance_cannot_override_incoming_master_block(self):
        incoming = portable_settings({"schema_version": 2, "defaults": {"security": {
            "never_publish": ["LOCAL-ALLOWANCE"]}}}).raw_record()
        with self.assertRaises(SettingsError):
            merge_portable(self.document(), incoming)

    def test_incoming_allowance_cannot_override_machine_block(self):
        incoming = portable_settings({"schema_version": 2, "defaults": {"security": {
            "safe_values": ["MACHINE-PRIVATE-MARKER"]}}}).raw_record()
        with self.assertRaises(SettingsError):
            merge_portable(self.document(), incoming)

    def test_import_rejects_local_path_key_and_local_policy_injection(self):
        for part in ({"scope": {"roots": [str(Path.cwd())]}},
                     {"output": {"directory": "machine-specific"}},
                     {"security": {"local_never_publish": ["injected"]}}):
            with self.subTest(part=part), self.assertRaises(SettingsError):
                merge_portable(self.document(), {"schema_version": 1, "settings": {"schema_version": 2, "defaults": part}})

    def test_import_rejects_wrong_version_and_unknown_envelope_fields(self):
        for record in ({}, {"schema_version": True, "settings": {}},
                       {"schema_version": 1, "settings": {}, "machine": {}}):
            with self.subTest(record=record), self.assertRaises(SettingsError):
                merge_portable(self.document(), record)

    def test_raw_record_is_copied_and_revalidated_after_mutation(self):
        portable = portable_settings(self.document())
        portable.raw_record()["settings"]["defaults"]["security"]["never_publish"].clear()
        self.assertEqual(portable.summary()["protected_values"], 1)
        portable.document["defaults"]["security"]["local_safe_values"] = ["injected"]
        with self.assertRaises(SettingsError):
            portable.raw_record()

    def test_v1_settings_remain_usable_without_enrollment(self):
        local = {"schema_version": 1, "defaults": {"output": {"directory": "local-reports"}}}
        incoming = portable_settings({"schema_version": 1, "defaults": {"security": {"engines": []}}}).raw_record()
        result = merge_portable(local, incoming)
        self.assertEqual(result["schema_version"], 2)
        self.assertNotIn("machine", result)
        self.assertNotIn("transports", result)
        resolved = resolve_document(result, "security", home=Path.cwd())
        self.assertEqual(resolved.values["security"]["engines"], [])


if __name__ == "__main__":
    unittest.main()
