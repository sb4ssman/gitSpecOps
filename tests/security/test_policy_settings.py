"""Common security-policy read/save contracts on invented profiles; no actual user policy.

Identity discovery is mocked; real Git/scanner integration remains in test_scanners.py.
Only explicit save tests write their own temporary settings; no migration or policy editor UI.
"""
from __future__ import annotations

import copy
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT, setup
setup()

from Special._settings import SettingsError, resolve_document, resolve_settings
from Special._settings import security as editor
from Special._settings import store
from Special.security import _me as subject
from Special.security import _cli as command


class PolicySettingsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="policy-settings-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.home = self.root / "profile"
        self.repo = self.root / "repo"
        self.repo.mkdir()
        environment = patch.dict(os.environ, {"GITSPECOPS_HOME": str(self.home)})
        environment.start()
        self.addCleanup(environment.stop)
        identities = patch.object(subject, "run", return_value=SimpleNamespace(returncode=1, stdout=""))
        self.git_config = identities.start()
        self.addCleanup(identities.stop)
        hostname = patch.object(subject.socket, "gethostname", return_value="machine-a")
        hostname.start()
        self.addCleanup(hostname.stop)
        user_home = patch.object(Path, "home", return_value=self.root / "fixture-user")
        user_home.start()
        self.addCleanup(user_home.stop)

    def put(self, name, value):
        path = self.home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
        return path

    def profile(self, **extra):
        document = {"schema_version": 2, "defaults": {"security": {
            "never_publish": ["private-marker"], "safe_values": ["generic@example.test"]}}, **extra}
        self.put("settings.json", document)
        return document

    def test_fresh_scan_uses_memory_defaults_without_writing_any_profile(self):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            policy = subject.load_policy(self.repo)
        self.assertEqual(policy.identities["never-publish"], [])
        self.assertEqual(policy.sources["safe-list"], "not-configured")
        self.assertFalse(policy.gaps)
        self.assertEqual(output.getvalue(), "")
        self.assertFalse(self.home.exists())

    def test_common_policy_ignores_legacy_copies_and_preserves_component_accumulation(self):
        self.profile(components={"security": {"security": {"never_publish": ["component-private"]}}})
        self.put("security/never_publish.txt", "stale-private\n")
        self.put("security/safe.txt", "private-marker\n")
        with patch.object(subject, "_values", side_effect=AssertionError("unexpected legacy read")):
            policy = subject.load_policy(self.repo)
        self.assertEqual(policy.identities["never-publish"], ["private-marker", "component-private"])
        self.assertIn("generic@example.test", policy.safe)
        self.assertNotIn("stale-private", policy.identities["never-publish"])
        self.assertEqual(policy.sources["settings"]["home_source"], "environment")

    def test_summaries_and_repr_never_disclose_policy_or_identity_values(self):
        self.profile(machine={"id": "machine-a", "label": "private-fixture", "fleet_secret": "ab" * 32})
        policy = subject.load_policy(self.repo)
        snapshot = editor.load_security_settings()
        record = json.dumps(policy.summary()) + repr(policy) + repr(snapshot) + json.dumps(snapshot.summary())
        for value in ("private-marker", "generic@example.test", "fixture-user", str(self.home), "ab" * 32,
                      "private-fixture"):
            self.assertNotIn(value, record)
        self.assertEqual(snapshot.summary()["owned_values"], {"never_publish": 1, "safe_values": 1})

    def test_bad_common_settings_fail_before_identity_discovery_without_legacy_fallback(self):
        self.put("security/never_publish.txt", "legacy-private\n")
        for document in ("{private-broken", '{"schema_version":2,"schema_version":2}',
                         {"schema_version": 3}, {"schema_version": 2, "bad": "private-value"}):
            self.put("settings.json", document)
            self.git_config.reset_mock()
            with self.subTest(document=document), self.assertRaises(SettingsError) as caught:
                subject.load_policy(self.repo)
            self.git_config.assert_not_called()
            self.assertNotIn("private-", str(caught.exception))

    def test_explicit_profile_wins_without_reading_an_invalid_default(self):
        self.put("settings.json", "{broken-default")
        alternate = self.root / "alternate"
        alternate.mkdir()
        (alternate / "settings.json").write_text(json.dumps({"schema_version": 1}))
        policy = subject.load_policy(self.repo, home=alternate)
        self.assertEqual(policy.sources["settings"]["schema_version"], 1)
        self.assertEqual(policy.sources["settings"]["home_source"], "explicit")

    def test_explicit_files_add_to_common_lists_without_removing_saved_blocks(self):
        self.profile()
        watch = self.put("watch-extra.txt", "# comment\nadditional-private\n")
        safe = self.put("safe-extra.txt", "another@example.test\n")
        policy = subject.load_policy(self.repo, never_file=watch, safe_file=safe, safe=["fixture-safe"])
        self.assertEqual(policy.identities["never-publish"], ["private-marker", "additional-private"])
        self.assertTrue({"generic@example.test", "another@example.test", "fixture-safe"} <= set(policy.safe))

    def test_runtime_safe_conflict_cannot_suppress_a_saved_protected_value(self):
        self.profile()
        for options in ({"safe": ["PRIVATE-MARKER"]},
                        {"safe_file": self.put("conflict-safe.txt", "private-marker\n")}):
            self.git_config.reset_mock()
            with self.subTest(options=options), self.assertRaises(SettingsError):
                subject.load_policy(self.repo, **options)
            self.git_config.assert_not_called()

    def test_public_handle_and_discovered_safe_identity_conflicts_fail_explicitly(self):
        self.profile()
        with self.assertRaises(SettingsError):
            subject.load_policy(self.repo, login=["private-marker"])
        address = "123+orbit-user@users.noreply.github.com"
        self.profile(defaults={"security": {"never_publish": [address]}})
        self.git_config.side_effect = [SimpleNamespace(returncode=0, stdout=address),
                                       SimpleNamespace(returncode=1, stdout="")]
        with self.assertRaises(SettingsError):
            subject.load_policy(self.repo)

    def test_exclusions_stop_before_identity_or_material_inspection(self):
        for target in (self.repo, self.root, self.repo / "excluded-child"):
            self.profile(defaults={"scope": {"exclude_paths": [str(target)]}})
            self.git_config.reset_mock()
            with self.subTest(target=target), self.assertRaisesRegex(SettingsError, "excluded"):
                subject.load_policy(self.repo)
            self.git_config.assert_not_called()

    def test_linked_scope_is_refused_but_the_source_checkout_is_a_valid_scan_target(self):
        self.profile()
        with patch.object(subject, "linked", return_value=True), self.assertRaises(SettingsError):
            subject.load_policy(self.repo)
        self.git_config.assert_not_called()
        policy = subject.load_policy(ROOT)
        self.assertIn("private-marker", policy.identities["never-publish"])

    def test_resolved_policy_seam_reads_no_config_and_does_not_mutate_input(self):
        document = {"schema_version": 2, "defaults": {"security": {"never_publish": ["private-marker"]}}}
        resolved = resolve_document(document, "security", home=self.home,
                                    overrides={"security": {"never_publish": []}})
        before = copy.deepcopy(resolved.values)
        with patch.object(subject, "resolve_settings", side_effect=AssertionError("unexpected resolve")), \
             patch.object(subject, "select_home", side_effect=AssertionError("unexpected home lookup")):
            policy = subject.load_policy(self.repo, settings=resolved)
        self.assertIn("private-marker", policy.identities["never-publish"])
        policy.identities["never-publish"].append("caller-change")
        self.assertEqual(resolved.values, before)
        self.assertFalse(self.home.exists())

    def test_legacy_text_requires_explicit_selection_and_remains_read_only(self):
        watch = self.put("security/never_publish.txt", "private-marker\n")
        safe = self.put("security/safe.txt", "private-marker\n")
        before = watch.read_bytes(), safe.read_bytes()
        with self.assertRaises(SettingsError):
            subject.load_policy(self.repo)
        self.git_config.assert_not_called()
        policy = subject.load_policy(self.repo, legacy_policy=True)
        self.assertEqual(policy.sources["settings"], "legacy-explicit")
        self.assertTrue(policy.allowed("private-marker", 0, len("private-marker")))
        self.assertEqual((watch.read_bytes(), safe.read_bytes()), before)
        self.assertFalse((self.home / "settings.json").exists())

    def test_legacy_mode_cannot_bypass_valid_or_invalid_common_settings(self):
        for document in ({"schema_version": 2}, "{broken"):
            self.put("settings.json", document)
            with self.subTest(document=document), self.assertRaisesRegex(SettingsError, "cannot bypass"):
                subject.load_policy(self.repo, legacy_policy=True)
        self.git_config.assert_not_called()

    def test_missing_and_linked_explicit_files_keep_incomplete_coverage(self):
        self.profile()
        absent = self.root / "missing.txt"
        policy = subject.load_policy(self.repo, never_file=absent)
        self.assertTrue(policy.gaps)
        self.assertIn("private-marker", policy.identities["never-publish"])
        target = self.put("selected.txt", "extra-private\n")
        original = subject.linked
        with patch.object(subject, "linked", side_effect=lambda path: path == target or original(path)):
            policy = subject.load_policy(self.repo, never_file=target)
        self.assertTrue(policy.gaps)
        self.assertNotIn("extra-private", policy.identities["never-publish"])

    def test_invalid_call_sources_and_scalar_allowances_are_refused(self):
        resolved = resolve_document({"schema_version": 2}, "security", home=self.home)
        for options in ({"settings": resolved, "home": self.home}, {"settings": resolved, "legacy_policy": True},
                        {"settings": {}}, {"legacy_policy": "yes"}, {"safe": "scalar"}, {"login": "scalar"}):
            with self.subTest(options=options), self.assertRaises(SettingsError):
                subject.load_policy(self.repo, **options)
        self.git_config.assert_not_called()

    def test_explicit_save_preserves_schema_other_components_and_legacy_files(self):
        for version in (1, 2):
            document = self.profile(schema_version=version,
                components={"app": {"security": {"never_publish": ["component-private"]}},
                            "archive_update": {"logging": {"enabled": False}}})
            legacy = self.put("security/never_publish.txt", "stale-copy\n")
            before = legacy.read_bytes()
            snapshot = editor.load_security_settings()
            editor.save_security_settings(snapshot, {"never_publish": ["replacement-private"]})
            expected = copy.deepcopy(document)
            expected["defaults"]["security"]["never_publish"] = ["replacement-private"]
            self.assertEqual(json.loads((self.home / "settings.json").read_text()), expected)
            self.assertEqual(legacy.read_bytes(), before)
            self.assertEqual(resolve_settings("app").values["security"]["never_publish"],
                             ["replacement-private", "component-private"])
            self.assertFalse((self.home / "logs").exists())
        self.git_config.assert_not_called()

    def test_save_refuses_conflicts_in_other_components_and_invalid_fields(self):
        self.profile(components={"app": {"security": {"never_publish": ["component-private"]}}})
        snapshot = editor.load_security_settings()
        before = (self.home / "settings.json").read_bytes()
        for updates in ({"safe_values": ["COMPONENT-PRIVATE"]}, {"scope": {}}, {"never_publish": "wrong"},
                        {"safe_values": None}, {"never_publish": [""]}, []):
            with self.subTest(updates=updates), self.assertRaises(SettingsError):
                editor.save_security_settings(snapshot, updates)
        self.assertEqual((self.home / "settings.json").read_bytes(), before)

    def test_missing_profile_editor_never_creates_or_migrates_one(self):
        self.put("security/never_publish.txt", "legacy-private\n")
        with self.assertRaises(SettingsError):
            editor.load_security_settings()
        self.assertFalse((self.home / "settings.json").exists())

    def test_noop_keeps_exact_bytes_including_absent_default_fields(self):
        for document, updates in ((self.profile(), {}), ({"schema_version": 2}, {"never_publish": []})):
            self.put("settings.json", document)
            path = self.home / "settings.json"
            before = path.read_bytes(), path.stat().st_mtime_ns
            snapshot = editor.load_security_settings()
            with patch.object(editor, "write_settings", side_effect=AssertionError("unexpected write")):
                editor.save_security_settings(snapshot, updates)
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_stale_and_mutated_snapshots_cannot_overwrite_new_policy(self):
        self.profile()
        snapshot = editor.load_security_settings()
        changed = self.profile(defaults={"security": {"never_publish": ["changed-private"]}})
        with self.assertRaises(SettingsError):
            editor.save_security_settings(snapshot, {"never_publish": []})
        self.assertEqual(json.loads((self.home / "settings.json").read_text()), changed)
        snapshot = editor.load_security_settings()
        snapshot.document["defaults"]["security"]["never_publish"] = []
        with self.assertRaisesRegex(SettingsError, "snapshot changed"):
            editor.save_security_settings(snapshot, {})

    def test_final_source_verification_is_under_lock_and_refusal_preserves_policy(self):
        self.profile()
        snapshot = editor.load_security_settings()
        before = (self.home / "settings.json").read_bytes()
        calls = []

        def refuse():
            calls.append((self.home / ".settings.lock").exists())
            raise SettingsError("policy inputs changed")

        with self.assertRaises(SettingsError):
            editor.save_security_settings(snapshot, {"never_publish": []}, check_sources=refuse)
        self.assertEqual(calls, [True])
        self.assertEqual((self.home / "settings.json").read_bytes(), before)
        self.assertFalse((self.home / ".settings.lock").exists())

    def test_write_failure_and_busy_lock_never_change_destination_or_policy(self):
        self.profile()
        snapshot = editor.load_security_settings()
        before = (self.home / "settings.json").read_bytes()
        with patch.object(store, "atomic_write_bytes", side_effect=OSError("private-path")), self.assertRaises(SettingsError):
            editor.save_security_settings(snapshot, {"never_publish": []})
        self.assertEqual((self.home / "settings.json").read_bytes(), before)
        self.put(".settings.lock", "existing")
        with self.assertRaisesRegex(SettingsError, "busy"):
            editor.save_security_settings(snapshot, {"never_publish": []})
        self.assertEqual((self.home / "settings.json").read_bytes(), before)
        self.assertEqual((self.home / ".settings.lock").read_text(), "existing")

    def test_cli_errors_are_machine_readable_and_help_does_not_read_policy(self):
        self.put("settings.json", "{private-broken")
        output = io.StringIO()
        with redirect_stdout(output), patch.object(command, "scan") as scan:
            self.assertEqual(command.main("tree", [str(self.repo), "--json"]), 2)
            scan.assert_not_called()
        record = json.loads(output.getvalue())
        self.assertEqual(record["coverage"], "incomplete")
        self.assertNotIn("private-broken", output.getvalue())
        with patch.object(command, "load_policy", side_effect=AssertionError("unexpected read")), \
             redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as caught:
            command.main("history", ["--help"])
        self.assertEqual(caught.exception.code, 0)

    def test_excluded_report_destination_is_refused_before_material_scan(self):
        self.profile(defaults={"scope": {"exclude_paths": [str(self.root / "reports")]}})
        with patch.object(command, "scan") as scan, redirect_stdout(io.StringIO()):
            self.assertEqual(command.main("tree", [str(self.repo), "--out", str(self.root / "reports" / "scan.json"), "--json"]), 2)
        scan.assert_not_called()
        self.assertFalse((self.root / "reports").exists())


if __name__ == "__main__":
    unittest.main()
