"""Archive adapter contracts on invented temporary profiles; no Git, launchers or migration.

Run directly with Python. Only explicit adapter-save tests write their temporary settings;
receipt conversions stay in memory. No default machine profile is consulted.
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
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT, setup
setup()

from Special._runtime.files import RuntimeIOError
from Special._settings import SettingsError, resolve_settings
from Special._settings import archives as subject
from Special._settings import store


class ArchiveSettingsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="archive-settings-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.home = self.root / "user-data"
        self.archive = self.root / "archive"
        self.other = self.root / "other-archive"
        environment = patch.dict(os.environ, {"GITSPECOPS_HOME": str(self.home)})
        environment.start()
        self.addCleanup(environment.stop)

    def archive_record(self, root=None, mode="update", prefixes=None):
        return {"root": str(root or self.archive), "mode": mode,
                "approved_remote_prefixes": ["https://example.test/team/"] if prefixes is None else prefixes}

    def put(self, name, value):
        target = self.home / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
        return target

    def profile(self, archives=None):
        return {"schema_version": 2, "components": {"archive_manage": {
            "options": {"archives": [self.archive_record()] if archives is None else archives}}}}

    def load(self, document=None):
        self.put("settings.json", self.profile() if document is None else document)
        return subject.load_archive_settings()

    def registry(self):
        return {"version": 1, "installations": [
            {**self.archive_record(mode="sync", prefixes=["https://old.example.test/"]),
             "installed_at": "2026-01-01T00:00:00", "launcher": "previous-launcher",
             "last_run_result": "previous", "unknown_receipt": {"retained": True}},
            {**self.archive_record(self.other), "launcher": "inactive-launcher"}]}

    def test_absent_common_settings_never_import_legacy_or_create_defaults(self):
        self.put("gitspecops_managed_archives.json", self.registry())
        before = (self.home / "gitspecops_managed_archives.json").read_bytes()
        with self.assertRaises(SettingsError):
            subject.load_archive_settings()
        self.assertEqual(before, (self.home / "gitspecops_managed_archives.json").read_bytes())
        self.assertFalse((self.home / "settings.json").exists())

    def test_read_uses_only_selected_profile_without_side_effects_or_private_summary(self):
        document = self.profile()
        document["machine"] = {"id": "machine-a", "label": "private-fixture", "fleet_secret": "ab" * 32}
        document["transports"] = {"repo": {"name": "example/private-state"}}
        document["defaults"] = {"security": {"never_publish": ["private-policy-marker"]},
                                "scope": {"exclude_paths": [str(self.other)]}}
        path = self.put("settings.json", document)
        original = path.read_bytes()
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            loaded = subject.load_archive_settings()
            summary = json.dumps(loaded.summary()) + repr(loaded)
        for value in (str(self.archive), "example.test", "private-fixture", "ab" * 32,
                      "example/private-state", "private-policy-marker"):
            self.assertNotIn(value, summary)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual([item.name for item in self.home.iterdir()], ["settings.json"])
        self.assertEqual(loaded.summary()["modes"], {"update": 1, "sync": 0})
        self.assertEqual(loaded.resolved().values["scope"]["exclude_paths"], [self.other])
        self.assertFalse(self.archive.exists())

    def test_explicit_home_wins_and_only_its_settings_bytes_are_read(self):
        self.put("settings.json", "{malformed-default")
        selected = self.root / "explicit"
        selected.mkdir()
        target = selected / "settings.json"
        target.write_text(json.dumps(self.profile()))
        read_bytes = Path.read_bytes
        seen = []

        def read(path):
            seen.append(path)
            return read_bytes(path)

        with patch.object(Path, "read_bytes", read):
            loaded = subject.load_archive_settings(selected)
        self.assertEqual(seen, [target])
        self.assertEqual(loaded.home, selected)
        self.assertEqual(loaded.home_source, "explicit")

    def test_invalid_common_profiles_never_fall_back_and_errors_do_not_echo_values(self):
        cases = ["{private-broken", '{"schema_version":2,"schema_version":2}',
                 {"schema_version": 1}, {"schema_version": 3},
                 {"schema_version": 2, "private-key": "private-value"},
                 {"schema_version": 2, "components": {"app": {"logging": {"enabled": "private-value"}}}}]
        for document in cases:
            with self.subTest(document=document):
                target = self.put("settings.json", document)
                before = target.read_bytes()
                with self.assertRaises(SettingsError) as caught:
                    subject.load_archive_settings()
                self.assertNotIn("private-", str(caught.exception))
                self.assertEqual(target.read_bytes(), before)

    def test_duplicate_lexical_roots_are_rejected_before_any_repository_access(self):
        duplicate = str(self.archive / "child" / "..")
        self.put("settings.json", self.profile([self.archive_record(), self.archive_record(Path(duplicate))]))
        with self.assertRaisesRegex(SettingsError, "duplicate roots"):
            subject.load_archive_settings()

    def test_no_receipt_roots_resurrect_when_preferences_are_absent_or_empty(self):
        for document in ({"schema_version": 2}, self.profile([])):
            with self.subTest(document=document):
                loaded = self.load(document)
                self.assertEqual(subject.manager_view(loaded, self.registry())["installations"], [])
                self.assertEqual(loaded.archives, [])

    def test_authoritative_choices_join_receipts_without_inheriting_stale_consent(self):
        loaded = self.load(self.profile([self.archive_record(prefixes=[])]))
        registry = self.registry()
        original = copy.deepcopy(registry)
        view = subject.manager_view(loaded, registry)
        entry = view["installations"][0]
        self.assertEqual(entry["mode"], "update")
        self.assertEqual(entry["approved_remote_prefixes"], [])
        self.assertEqual(entry["last_run_result"], "previous")
        self.assertEqual(entry["unknown_receipt"], {"retained": True})
        entry["mode"] = "sync"
        entry["unknown_receipt"]["retained"] = False
        self.assertEqual(registry, original)
        self.assertEqual(loaded.archives[0]["mode"], "update")

    def test_conversion_is_pure_and_never_inspects_root_paths(self):
        loaded = self.load()
        registry = self.registry()
        with patch.object(Path, "stat", side_effect=AssertionError("unexpected stat")), \
             patch.object(Path, "resolve", side_effect=AssertionError("unexpected resolve")), \
             patch.object(Path, "read_bytes", side_effect=AssertionError("unexpected read")):
            view = subject.manager_view(loaded, registry)
            merged = subject.merge_archive_receipts(loaded, registry, view["installations"])
        self.assertEqual(merged, {**registry, "version": 2})

    def test_receipt_merge_retains_inactive_material_and_historical_preferences(self):
        loaded = self.load()
        registry = self.registry()
        original = copy.deepcopy(registry)
        update = subject.manager_view(loaded, registry)["installations"][0]
        update.update(last_run_result="ok", last_run_elapsed_seconds=0.25, last_report=None,
                      installed_at="2026-02-01T00:00:00")
        merged = subject.merge_archive_receipts(loaded, registry, [update])
        self.assertEqual(registry, original)
        self.assertEqual(merged["installations"][1], registry["installations"][1])
        first = merged["installations"][0]
        self.assertEqual(first["mode"], "sync")
        self.assertEqual(first["approved_remote_prefixes"], ["https://old.example.test/"])
        self.assertEqual(first["last_run_result"], "ok")
        self.assertEqual(first["installed_at"], original["installations"][0]["installed_at"])
        self.assertEqual(loaded.archives[0]["mode"], "update")

    def test_new_receipt_carries_no_mode_or_allowed_prefixes(self):
        loaded = self.load()
        updated = {**loaded.archives[0], "repo_count": 2, "last_run_result": "ok"}
        merged = subject.merge_archive_receipts(loaded, None, [updated])
        self.assertEqual(merged, {"version": 2, "installations": [
            {"root": str(self.archive), "repo_count": 2, "last_run_result": "ok"}]})
        self.assertEqual(subject.manager_view(loaded)["installations"], loaded.archives)

    def test_bad_receipts_fail_instead_of_choosing_an_entry_or_an_empty_registry(self):
        loaded = self.load()
        cases = [[], {"version": True, "installations": []}, {"version": 3, "installations": []},
                 {"version": 1, "installations": "bad"}, {"version": 1, "installations": [{}]},
                 {"version": 1, "installations": [{"root": "relative"}]},
                 {"version": 1, "installations": [{"root": str(self.archive)}] * 2}]
        for registry in cases:
            with self.subTest(registry=registry), self.assertRaises(SettingsError):
                subject.manager_view(loaded, registry)

    def test_bad_receipt_updates_are_rejected_without_mutating_either_input(self):
        loaded = self.load()
        root = {"root": str(self.archive)}
        cases = [None, [{}], [{"root": str(self.other)}], [root, root],
                 [{**root, "surprise": "private-value"}], [{**root, "unknown_receipt": False}],
                 [{**root, "repo_count": True}], [{**root, "repo_count": -1}],
                 [{**root, "last_run_elapsed_seconds": float("nan")}],
                 [{**root, "last_run_elapsed_seconds": True}], [{**root, "launcher": ["bad"]}]]
        for updates in cases:
            registry = self.registry()
            before = copy.deepcopy(registry)
            with self.subTest(updates=updates), self.assertRaises(SettingsError) as caught:
                subject.merge_archive_receipts(loaded, registry, updates)
            self.assertNotIn("private-value", str(caught.exception))
            self.assertEqual(registry, before)

    def test_save_changes_only_archive_choices_and_never_writes_receipts_or_artifacts(self):
        document = self.profile()
        document["defaults"] = {"security": {"never_publish": ["private-marker"]}}
        document["machine"] = {"id": "machine-a", "label": "fixture", "fleet_secret": "ab" * 32}
        document["transports"] = {"repo": {"name": "example/state"}}
        document["components"]["archive_manage"].update(logging={"enabled": False})
        document["components"]["archive_update"] = {"scope": {"roots": [str(self.other)]}}
        loaded = self.load(document)
        receipt_path = self.put("gitspecops_managed_archives.json", self.registry())
        receipt_bytes = receipt_path.read_bytes()
        choices = [self.archive_record(mode="sync"), self.archive_record(self.other)]
        expected = copy.deepcopy(document)
        expected["components"]["archive_manage"]["options"]["archives"] = choices
        subject.save_archive_preferences(loaded, choices)
        self.assertEqual(json.loads((self.home / "settings.json").read_text()), expected)
        self.assertEqual(receipt_path.read_bytes(), receipt_bytes)
        self.assertFalse(self.archive.exists())
        self.assertFalse((self.home / "logs").exists())
        self.assertEqual(resolve_settings("archive_manage").values["options"]["archives"], choices)
        self.assertEqual(loaded.archives, document["components"]["archive_manage"]["options"]["archives"])

    def test_noop_preserves_exact_bytes_and_does_not_invoke_writer(self):
        loaded = self.load()
        path = self.home / "settings.json"
        before = path.read_bytes(), path.stat().st_mtime_ns
        with patch.object(subject, "write_settings", side_effect=AssertionError("unexpected write")):
            self.assertEqual(subject.save_archive_preferences(loaded, loaded.archives), loaded.expected_revision)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_stale_file_and_mutated_snapshot_refuse_saves_and_noops(self):
        loaded = self.load()
        changed = self.profile([])
        path = self.put("settings.json", changed)
        for choices in ([], loaded.archives):
            with self.assertRaises(SettingsError):
                subject.save_archive_preferences(loaded, choices)
        self.assertEqual(json.loads(path.read_text()), changed)
        loaded = self.load()
        loaded.document["components"]["archive_manage"]["options"]["archives"] = []
        with self.assertRaisesRegex(SettingsError, "snapshot changed"):
            subject.save_archive_preferences(loaded, [])

    def test_invalid_choices_cannot_silently_widen_or_overwrite_settings(self):
        loaded = self.load()
        before = (self.home / "settings.json").read_bytes()
        cases = [[self.archive_record(mode="unknown")], [{**self.archive_record(), "unexpected": True}],
                 [self.archive_record(Path("relative"))], [self.archive_record(prefixes=[""])],
                 [self.archive_record(), self.archive_record()], "bad"]
        for choices in cases:
            with self.subTest(choices=choices), self.assertRaises(SettingsError):
                subject.save_archive_preferences(loaded, choices)
        self.assertEqual((self.home / "settings.json").read_bytes(), before)

    def test_final_source_check_runs_under_writer_lock_and_can_refuse(self):
        loaded = self.load()
        path = self.home / "settings.json"
        before = path.read_bytes()
        calls = []

        def refuse():
            calls.append((self.home / ".settings.lock").exists())
            raise SettingsError("receipt inputs changed; review again")

        with self.assertRaisesRegex(SettingsError, "receipt inputs changed"):
            subject.save_archive_preferences(loaded, [], check_sources=refuse)
        self.assertEqual(calls, [True])
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.home / ".settings.lock").exists())

    def test_state_change_immediately_before_writer_cannot_replace_new_preferences(self):
        loaded = self.load()
        real_writer = store.write_settings
        changed = self.profile([self.archive_record(self.other)])

        def changed_writer(*args, **kwargs):
            self.put("settings.json", changed)
            return real_writer(*args, **kwargs)

        with patch.object(subject, "write_settings", side_effect=changed_writer), self.assertRaises(SettingsError):
            subject.save_archive_preferences(loaded, [])
        self.assertEqual(json.loads((self.home / "settings.json").read_text()), changed)

    def test_write_failure_or_busy_lock_preserves_profile_without_fallback(self):
        loaded = self.load()
        path = self.home / "settings.json"
        before = path.read_bytes()
        with patch.object(store, "atomic_write_bytes", side_effect=OSError("private-destination")):
            with self.assertRaises(SettingsError) as caught:
                subject.save_archive_preferences(loaded, [])
        self.assertNotIn("private-destination", str(caught.exception))
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.home / ".settings.lock").exists())
        self.put(".settings.lock", "existing lock")
        with self.assertRaisesRegex(SettingsError, "busy"):
            subject.save_archive_preferences(loaded, [])
        self.assertEqual((self.home / ".settings.lock").read_text(), "existing lock")
        self.assertEqual(path.read_bytes(), before)

    def test_link_or_source_storage_refused_before_read(self):
        with patch.object(subject, "checked_path", side_effect=RuntimeIOError("linked_destination")), \
             patch.object(Path, "read_bytes", side_effect=AssertionError("unexpected read")), \
             self.assertRaises(SettingsError):
            subject.load_archive_settings(self.home)
        with patch.object(Path, "read_bytes", side_effect=AssertionError("unexpected source read")), \
             self.assertRaises(SettingsError):
            subject.load_archive_settings(ROOT / "temporary-profile")


if __name__ == "__main__":
    unittest.main()
