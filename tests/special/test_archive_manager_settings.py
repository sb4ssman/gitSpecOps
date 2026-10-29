"""Manager/registry/profile integration using temporary invented state only.

Repository execution and OS scheduling are mocked here. Generated launchers are inspected,
not installed on this machine. The separate manager integration covers real temporary pulls.
Run directly with Python; no actual user profile, network or enrollment is needed.
"""
from __future__ import annotations

import copy
import io
import json
import os
import subprocess
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

from Special import archive_manager as command
from Special._archive import manager, registry
from Special._archive import operation
from Special._archive import sync as sync_engine
from Special._archive.plan import RepoRef
from Special._settings import SettingsError
from Special._settings.archives import load_archive_settings, save_archive_preferences
from Special._settings import store
from Elaborate import archive_manage as scheduled


class ManagerSettingsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="manager-settings-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.home = self.root / "profile"
        self.archive = self.root / "archive-a"
        self.other = self.root / "archive-b"
        self.archive.mkdir()
        self.other.mkdir()
        environment = patch.dict(os.environ, {"GITSPECOPS_HOME": str(self.root / "unused-profile")})
        environment.start()
        self.addCleanup(environment.stop)
        self.output = io.StringIO()
        stdout = redirect_stdout(self.output)
        stderr = redirect_stderr(self.output)
        stdout.__enter__()
        stderr.__enter__()
        self.addCleanup(stdout.__exit__, None, None, None)
        self.addCleanup(stderr.__exit__, None, None, None)

    def choice(self, root=None, mode="update", prefixes=None):
        return {"root": str(root or self.archive), "mode": mode,
                "approved_remote_prefixes": ["https://example.test/team/"] if prefixes is None else prefixes}

    def put(self, name, value):
        path = self.home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
        return path

    def profile(self, choices=None, **extra):
        document = {"schema_version": 2, "components": {"archive_manage": {
            "options": {"archives": [self.choice()] if choices is None else choices}}}, **extra}
        self.put("settings.json", document)
        return document

    def receipts(self):
        record = {**self.choice(mode="sync", prefixes=["https://old.example.test/"]),
                  "installed_at": "2026-01-01T00:00:00", "launcher": "old-launcher",
                  "unknown_receipt": {"keep": True}}
        return self.put(registry.REGISTRY_NAME, {"version": 1, "installations": [record]})

    def install(self, mode=None, prefixes=None):
        return manager.install_launchers(self.archive, prefixes, prevalidated_repos=["fixture"],
                                         mode=mode, home=self.home)

    def record(self, mode="sync"):
        return registry.InstallRecord(str(self.archive), "2026-02-01T00:00:00", "2026-02-01T00:00:00",
            str(ROOT), str(Path(sys.executable)), "fixture-runner", "fixture-launcher", "fixture",
            1, ["https://example.test/team/"], mode)

    def test_common_choices_override_receipts_and_import_ignores_old_roots(self):
        self.receipts()
        self.profile([self.choice(self.other, "update")])
        data = registry.load_registry(home=self.home)
        self.assertEqual(data["installations"], [self.choice(self.other)])
        self.assertEqual(registry.registered_roots(home=self.home), [str(self.other)])
        self.profile([])
        self.assertEqual(registry.load_registry(home=self.home)["installations"], [])
        self.assertEqual(registry.registered_roots(home=self.home), [])

    def test_bad_common_settings_never_fall_back_or_write_launchers(self):
        self.receipts()
        for document in ("{private-broken", {"schema_version": 1}, {"schema_version": 99}):
            self.put("settings.json", document)
            with self.subTest(document=document), patch.object(manager.launcher, "write_launcher") as write, \
                 patch.object(manager, "inspect_candidate") as inspect:
                self.assertEqual(command.main(["--settings-home", str(self.home), "--install", str(self.archive)]), 2)
                write.assert_not_called()
                inspect.assert_not_called()
                with self.assertRaises(SettingsError):
                    registry.registered_roots(home=self.home)
        self.assertFalse(manager.log_path(self.home).exists())

    def test_receipt_save_cannot_change_settings_or_historical_allowances(self):
        self.profile()
        path = self.receipts()
        original = (self.home / "settings.json").read_bytes()
        data = registry.load_registry(home=self.home)
        data["installations"][0].update(mode="sync", approved_remote_prefixes=["https://untrusted.example.test/"],
                                          last_run_result="ok")
        registry.save_registry(data)
        saved = json.loads(path.read_text())["installations"][0]
        self.assertEqual(saved["mode"], "sync")
        self.assertEqual(saved["approved_remote_prefixes"], ["https://old.example.test/"])
        self.assertEqual(saved["last_run_result"], "ok")
        self.assertEqual(saved["unknown_receipt"], {"keep": True})
        self.assertEqual((self.home / "settings.json").read_bytes(), original)
        self.assertEqual(registry.load_registry(home=self.home)["installations"][0]["mode"], "update")

    def test_install_preserves_unspecified_choices_and_new_launcher_has_no_copied_consent(self):
        self.profile([self.choice(mode="sync")])
        before = (self.home / "settings.json").read_bytes()
        record = self.install()
        self.assertEqual(record.mode, "sync")
        self.assertEqual((self.home / "settings.json").read_bytes(), before)
        text = "\n".join(path.read_text(encoding="utf-8") for path in
                         manager.launcher.launcher_files(self.archive, manager.ARCHIVE_LAUNCHER))
        for value in ("Special/archive_manager.py", "--refresh", str(self.archive), "--settings-home", str(self.home)):
            self.assertIn(value, text)
        for value in ("--sync", "--update", "--yes", "--approved-remote-prefix", "example.test"):
            self.assertNotIn(value, text)
        self.assertFalse((self.root / "unused-profile").exists())
        receipt = json.loads(registry.registry_path(self.home).read_text())["installations"][0]
        self.assertNotIn("mode", receipt)
        self.assertNotIn("approved_remote_prefixes", receipt)

    def test_current_settings_drive_direct_and_catalog_refresh_after_launcher_generation(self):
        self.profile()
        self.install()
        snapshot = load_archive_settings(self.home)
        save_archive_preferences(snapshot, [self.choice(mode="sync", prefixes=["https://new.example.test/"])])
        import gitso
        with patch.object(operation, "execute_archive", return_value={"exit_code": 0, "effects_possible": False, "result": {}}) as run:
            for entry in (command.main, lambda args: gitso.main(["archive-manager", *args])):
                self.assertEqual(entry(["--refresh", str(self.archive), "--settings-home", str(self.home)]), 0)
        for call in run.call_args_list:
            request = call.args[0]
            self.assertEqual(request["mode"], "sync")
            self.assertEqual(request["approved_remote_prefixes"], ["https://new.example.test/"])
        self.assertEqual(json.loads(registry.registry_path(self.home).read_text())["installations"][0]["last_run_result"], "ok")

    def test_single_refresh_does_not_run_other_archives_and_never_registers_an_unknown_root(self):
        self.profile([self.choice(), self.choice(self.other, "sync")])
        with patch.object(operation, "execute_archive", return_value={"exit_code": 0, "effects_possible": False, "result": {}}) as run:
            self.assertEqual(command.main(["--refresh", str(self.other), "--settings-home", str(self.home)]), 0)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0]["root"], str(self.other))
            run.reset_mock()
            self.assertEqual(command.main(["--refresh", str(self.root / "unknown"), "--settings-home", str(self.home)]), 2)
            run.assert_not_called()

    def test_forget_keeps_receipts_and_launcher_but_disables_its_future_dispatch(self):
        self.profile()
        installed = self.install()
        path = registry.registry_path(self.home)
        before = path.read_bytes()
        self.assertTrue(registry.forget_installation(self.archive, home=self.home))
        self.assertEqual(path.read_bytes(), before)
        self.assertTrue(Path(installed.launcher).is_file())
        self.assertEqual(registry.registered_roots(home=self.home), [])
        with patch.object(operation, "execute_archive") as run:
            self.assertEqual(command.main(["--refresh", str(self.archive), "--settings-home", str(self.home)]), 2)
            run.assert_not_called()

    def test_explicit_registration_changes_only_preferences_and_receipt_metadata(self):
        original = self.profile([self.choice(), self.choice(self.other)],
            defaults={"security": {"never_publish": ["private-fixture"]}})
        receipt_path = self.receipts()
        registry.upsert_record(self.record(), home=self.home)
        saved = json.loads((self.home / "settings.json").read_text())
        expected = copy.deepcopy(original)
        expected["components"]["archive_manage"]["options"]["archives"][0]["mode"] = "sync"
        self.assertEqual(saved, expected)
        receipt = json.loads(receipt_path.read_text())["installations"][0]
        self.assertEqual(receipt["installed_at"], "2026-01-01T00:00:00")
        self.assertEqual(receipt["unknown_receipt"], {"keep": True})

    def test_stale_receipt_or_settings_snapshot_and_busy_lock_refuse_without_overwriting(self):
        self.profile()
        path = self.receipts()
        data = registry.load_registry(home=self.home)
        changed = json.loads(path.read_text())
        changed["installations"][0]["last_run_result"] = "another-writer"
        self.put(registry.REGISTRY_NAME, changed)
        for explicit in (False, True):
            with self.assertRaises(SettingsError):
                registry.save_registry(data, path if explicit else None)
        self.assertEqual(json.loads(path.read_text()), changed)
        data = registry.load_registry(home=self.home)
        self.profile([])
        with self.assertRaises(SettingsError):
            registry.save_registry(data)
        self.profile()
        data = registry.load_registry(home=self.home)
        lock = self.put(".archive-registry.lock", "existing")
        with self.assertRaisesRegex(SettingsError, "busy"):
            registry.save_registry(data)
        self.assertEqual(lock.read_text(), "existing")
        self.assertEqual(json.loads(path.read_text()), changed)

    def test_legacy_snapshot_cannot_write_after_common_authority_appears(self):
        path = self.receipts()
        before = path.read_bytes()
        data = registry.load_registry(home=self.home)
        self.profile([])
        with self.assertRaisesRegex(SettingsError, "authority changed"):
            registry.save_registry(data)
        self.assertEqual(path.read_bytes(), before)

    def test_copying_a_common_view_cannot_bypass_stale_snapshot_checks(self):
        self.profile()
        path = self.receipts()
        data = registry.load_registry(home=self.home)
        before = path.read_bytes()
        with self.assertRaisesRegex(SettingsError, "original revision-checked"):
            registry.save_registry(dict(data), home=self.home)
        self.assertEqual(path.read_bytes(), before)

    def test_receipt_failure_after_preference_save_reports_partial_installation(self):
        self.profile()
        path = self.receipts()
        data = registry.load_registry(home=self.home)
        registry.save_registry(data)  # Establish the receipt-only version before testing the later write.
        before = path.read_bytes()
        with patch.object(registry, "atomic_write_bytes", side_effect=OSError("private-path")), \
             self.assertRaisesRegex(SettingsError, "preferences were saved but receipt saving failed") as caught:
            registry.upsert_record(self.record(), home=self.home)
        self.assertNotIn("private-path", str(caught.exception))
        self.assertEqual(load_archive_settings(self.home).archives[0]["mode"], "sync")
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.home / ".archive-registry.lock").exists())

    def test_preference_failure_preserves_choices_and_receipt_fields(self):
        self.profile()
        path = self.receipts()
        before = path.read_bytes(), (self.home / "settings.json").read_bytes()
        with patch.object(store, "atomic_write_bytes", side_effect=OSError("private-path")), \
             self.assertRaises(SettingsError):
            registry.upsert_record(self.record(), home=self.home)
        retained = json.loads(before[0])
        retained["version"] = 2
        self.assertEqual(json.loads(path.read_text()), retained)
        self.assertEqual((self.home / "settings.json").read_bytes(), before[1])

    def test_missing_common_settings_cannot_reactivate_historical_receipt_choices(self):
        self.profile()
        path = self.receipts()
        registry.save_registry(registry.load_registry(home=self.home))
        self.assertEqual(json.loads(path.read_text())["version"], 2)
        (self.home / "settings.json").unlink()  # Deliberate loss of this test's temporary profile.
        with self.assertRaisesRegex(SettingsError, "settings are missing"):
            registry.load_registry(home=self.home)
        with self.assertRaisesRegex(SettingsError, "settings are missing"):
            registry.registered_roots(home=self.home)
        with patch.object(operation, "execute_archive") as run:
            self.assertEqual(command.main(["--refresh-all", "--settings-home", str(self.home)]), 2)
            run.assert_not_called()

    def test_first_receipt_format_write_failure_prevents_preference_change(self):
        self.profile()
        path = self.receipts()
        before = path.read_bytes(), (self.home / "settings.json").read_bytes()
        with patch.object(registry, "atomic_write_bytes", side_effect=OSError("private-fixture")), \
             self.assertRaises(SettingsError):
            registry.upsert_record(self.record(), home=self.home)
        self.assertEqual((path.read_bytes(), (self.home / "settings.json").read_bytes()), before)

    def test_empty_allowances_and_exclusions_stop_before_git_or_launcher_writes(self):
        for exclusion in (self.archive, self.root, self.archive / "do-not-touch", self.home):
            with self.subTest(exclusion=exclusion):
                self.profile(defaults={"scope": {"exclude_paths": [str(exclusion)]}})
                with patch.object(operation, "execute_archive") as run, patch.object(manager, "inspect_candidate") as inspect, \
                     patch.object(manager.launcher, "write_launcher") as write:
                    self.assertEqual(command.main(["--refresh", str(self.archive), "--settings-home", str(self.home)]), 2)
                    self.assertEqual(command.main(["--install", str(self.archive), "--settings-home", str(self.home)]), 2)
                    run.assert_not_called()
                    inspect.assert_not_called()
                    write.assert_not_called()
        self.profile([self.choice(prefixes=[])])
        with patch.object(operation, "execute_archive") as run:
            self.assertEqual(command.main(["--refresh-all", "--settings-home", str(self.home)]), 2)
            run.assert_not_called()
        self.assertFalse(registry.registry_path(self.home).exists())
        self.assertFalse(manager.log_path(self.home).exists())

    def test_linked_child_is_refused_before_sync_engine_inspection(self):
        self.profile()
        (self.archive / "child").mkdir()
        with patch.object(operation, "linked", return_value=True), patch.object(operation, "execute_archive") as run:
            self.assertEqual(command.main(["--refresh", str(self.archive), "--settings-home", str(self.home)]), 2)
            run.assert_not_called()
        self.assertFalse(manager.log_path(self.home).exists())

    def test_changed_profile_between_archives_stops_later_actions_and_reports_partial_results(self):
        self.profile([self.choice(), self.choice(self.other)])

        def first_run(*args, **kwargs):
            self.profile([])
            return {"exit_code": 0, "effects_possible": True, "result": {}}

        with patch.object(operation, "execute_archive", side_effect=first_run) as run:
            self.assertEqual(command.main(["--refresh-all", "--settings-home", str(self.home)]), 2)
        self.assertEqual(run.call_count, 1)
        self.assertIn("partial operations", self.output.getvalue())
        self.assertEqual(load_archive_settings(self.home).archives, [])

    def test_receipt_save_failure_after_execution_is_explicit(self):
        self.profile()
        with patch.object(operation, "execute_archive", return_value={"exit_code": 0, "effects_possible": True, "result": {}}), \
             patch.object(operation, "save_registry", side_effect=SettingsError("fixture-error")):
            self.assertEqual(command.main(["--refresh", str(self.archive), "--settings-home", str(self.home)]), 2)
        self.assertIn("operations finished but receipt saving failed", self.output.getvalue())

    def test_refresh_all_launcher_pins_the_selected_profile_without_installing_a_task(self):
        self.profile()
        path = scheduled.write_refresh_all_script(home=self.home)
        self.assertEqual(path.parent, self.home)
        text = "\n".join(p.read_text(encoding="utf-8") for p in
                         scheduled.launcher.launcher_files(self.home, scheduled.REFRESH_ALL_LAUNCHER))
        self.assertIn("--settings-home", text)
        self.assertIn(str(self.home), text)
        self.assertNotIn("--approved-remote-prefix", text)
        with patch.object(scheduled, "write_refresh_all_script", return_value=path) as writer, \
             patch.object(scheduled.schedule, "install_monthly", return_value=0) as task:
            self.assertEqual(scheduled.install_monthly_task("fixture", 1, "09:00", home=self.home), 0)
        self.assertEqual(writer.call_args.kwargs, {"home": self.home})
        self.assertEqual(task.call_args.args, ("fixture", path, 1, "09:00"))

    def test_help_and_parser_refusals_do_not_read_profiles(self):
        with patch.object(manager, "load_registry", side_effect=AssertionError("unexpected read")):
            for args in (["--help"], ["--refresh", str(self.archive), "--mode", "sync"],
                         ["--refresh-all", "--approved-remote-prefix", "https://example.test/"],
                         ["--scan-only"], ["--refresh-all", "--forget", str(self.archive)]):
                with self.subTest(args=args), self.assertRaises(SystemExit):
                    command.main(args)
        self.assertFalse(self.home.exists())

    def test_unattended_manager_and_scheduler_refuse_ambiguous_actions_without_settings(self):
        with patch.object(sys.stdin, "isatty", return_value=False), \
             patch.object(manager, "load_registry", side_effect=AssertionError("unexpected read")):
            self.assertEqual(command.main(["--settings-home", str(self.home)]), 2)
            with self.assertRaises(SystemExit):
                command.main(["--refresh", str(self.archive), "--mode", "sync"])
            for args in (["--settings-home", str(self.home)], ["--refresh-all"], ["--list"]):
                with self.assertRaises(SystemExit):
                    scheduled.main(args)
        self.assertFalse(self.home.exists())

    def test_launcher_failure_reports_partial_artifacts_without_registering(self):
        self.profile()
        before = (self.home / "settings.json").read_bytes()
        with patch.object(manager.launcher, "write_launcher", side_effect=OSError("private-fixture")), \
             self.assertRaisesRegex(SettingsError, "some launcher files may exist") as caught:
            self.install()
        self.assertNotIn("private-fixture", str(caught.exception))
        self.assertEqual((self.home / "settings.json").read_bytes(), before)
        self.assertFalse(registry.registry_path(self.home).exists())

    def test_headless_subprocess_reads_only_explicit_profile_from_outside_checkout(self):
        self.profile()
        done = subprocess.run([sys.executable, "-B", str(ROOT / "Special" / "archive_manager.py"),
            "--list", "--settings-home", str(self.home)], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(str(self.archive), done.stdout)
        self.assertFalse((self.root / "unused-profile").exists())
        self.assertEqual([path.name for path in self.home.iterdir()], ["settings.json"])

    def test_sync_import_refuses_invalid_common_settings_before_any_initialization(self):
        self.put("settings.json", "{private-broken")
        config = self.root / "sync-profile"
        environment = {**os.environ, "GITSPECOPS_HOME": str(self.home)}
        done = subprocess.run([sys.executable, "-B", str(ROOT / "git-sync-suggester" / "sync_suggester.py"),
            "--config-dir", str(config), "init", "--from-archives", "--machine-id", "machine-a",
            "--machine-label", "fixture"], cwd=self.root, env=environment, capture_output=True, text=True)
        self.assertEqual(done.returncode, 2)
        self.assertIn("no initialization was performed", done.stderr)
        self.assertNotIn("private-broken", done.stderr)
        self.assertNotIn("Traceback", done.stderr)
        self.assertFalse(config.exists())

    def test_shared_engine_excludes_unapproved_local_origins_from_pull_targets(self):
        local = SimpleNamespace(name="blocked", is_work_tree=True, origin="https://blocked.example.test/team/repo",
                                approved_remote=False, dirty_work_tree=False, dirty_index=False)
        with patch.object(sync_engine, "list_child_dirs", return_value=[self.archive]), \
             patch.object(sync_engine, "inspect_candidate", return_value=local), \
             patch.object(sync_engine, "provider_for") as provider:
            result = sync_engine.detect_plan(self.root, ["https://example.test/team/"])
        self.assertEqual(result.plan.to_pull, [])
        self.assertEqual(result.plan.to_clone, [])
        self.assertEqual([issue.action for issue in result.errors], ["scope"])
        provider.assert_not_called()

    def test_shared_engine_filters_remote_clone_candidates_using_saved_allowances(self):
        local = SimpleNamespace(name="repo", is_work_tree=True, origin="https://example.test/team/repo",
                                approved_remote=True, dirty_work_tree=False, dirty_index=False)
        allowed = RepoRef(id="allowed", owner="team", name="permitted", url="https://example.test/team/permitted")
        blocked = RepoRef(id="blocked", owner="other", name="blocked", url="https://blocked.example.test/other/blocked")
        provider = SimpleNamespace(name="fixture", list_repos=lambda owner: ([allowed, blocked], None),
                                   resolve=lambda spec: (None, "not found"))
        with patch.object(sync_engine, "list_child_dirs", return_value=[self.archive]), \
             patch.object(sync_engine, "inspect_candidate", return_value=local), \
             patch.object(sync_engine, "provider_for", return_value=provider):
            result = sync_engine.detect_plan(self.root, ["https://example.test/team/"], owner_override="team")
        self.assertEqual([ref.name for ref in result.plan.to_clone], ["permitted"])
        self.assertEqual(result.remote_count, 1)
        self.assertIn("scope", [issue.action for issue in result.errors])

    def test_blank_remote_prefix_cannot_authorize_every_origin(self):
        from Special._archive import sync_cli
        with patch.object(sync_engine, "detect_plan") as detect, self.assertRaises(SystemExit) as caught:
            sync_cli.main(["--root", str(self.archive), "--approved-remote-prefix", "", "--yes"])
        self.assertEqual(caught.exception.code, 2)
        detect.assert_not_called()
        with patch.object(sync_engine, "list_child_dirs") as folders, self.assertRaises(ValueError):
            sync_engine.detect_plan(self.archive, [""])
        folders.assert_not_called()


if __name__ == "__main__":
    unittest.main()
