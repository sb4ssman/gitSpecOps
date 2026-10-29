"""Registered refresh contracts in disposable local archives; no live settings or scheduling.

Real fast-forward pulls use a temporary bare remote. Provider/IO failures are injected before
actions to prove no fallback, partial results and separation of reports/receipts/logs.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup
setup()

from Special._archive import operation, registry, sync
from Special._archive.update_operation import UpdateRequest, run_update
from Special._archive.plan import SyncPlan, LocalRepo, RepoRef
from Special._settings import resolve_document, SettingsError
from Special._runtime.files import RuntimeIOError
from Special._runtime.output import conceal
from Special import archive_manager
from Special import update_archive
from Elaborate import archive_manage
import gitso


class ArchiveRefreshTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="archive-refresh-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.home, self.a, self.b = (self.root / name for name in ("profile", "archive-a", "archive-b"))
        for folder in (self.home, self.a, self.b):
            folder.mkdir()
        environment = patch.dict(os.environ, {"GITSPECOPS_HOME": str(self.home), "GIT_CONFIG_GLOBAL": os.devnull,
                                              "GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0"})
        environment.start()
        self.addCleanup(environment.stop)
        self.remote, self.seed = self.root / "remote.git", self.root / "seed"
        self.git(self.root, "init", "-q", "--bare", "-b", "main", str(self.remote))
        self.git(self.root, "clone", "-q", str(self.remote), str(self.seed))
        self.git(self.seed, "config", "user.email", "123+orbit-user@users.noreply.github.com")
        self.git(self.seed, "config", "user.name", "orbit-user")
        self.git(self.seed, "config", "commit.gpgsign", "false")
        self.advance("first.txt")
        for archive in (self.a, self.b):
            self.git(self.root, "clone", "-q", str(self.remote), str(archive / "work"))
        self.document = {"schema_version": 2, "defaults": {"logging": {"enabled": False}},
                         "components": {"archive_manage": {"options": {"archives": [self.choice(self.a), self.choice(self.b, "sync")]}}}}
        self.save()

    def git(self, repo, *args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                              text=True, timeout=30).stdout.strip()

    def choice(self, root, mode="update"):
        return {"root": str(root), "mode": mode, "approved_remote_prefixes": [str(self.root)]}

    def save(self):
        (self.home / "settings.json").write_text(json.dumps(self.document), encoding="utf-8")

    def advance(self, name):
        (self.seed / name).write_text("ordinary", encoding="utf-8")
        self.git(self.seed, "add", "--", name)
        self.git(self.seed, "commit", "-qm", "fixture change")
        self.git(self.seed, "push", "-q", "origin", "main")

    def run_refresh(self, **kwargs):
        return operation.run_refresh(home=self.home, **kwargs)

    def test_both_modes_refresh_real_repositories_without_printing_or_default_reports(self):
        self.advance("next.txt")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            result = self.run_refresh()
        self.assertEqual(result.exit_code, 0, result.record())
        self.assertEqual(out.getvalue() + err.getvalue(), "")
        self.assertEqual([item["operation"] for item in result.archives], ["update", "sync"])
        for archive in (self.a, self.b):
            self.assertTrue((archive / "work/next.txt").exists())
            self.assertFalse((archive / ".gitSpecOps").exists())
        receipt = registry.load_registry(home=self.home)
        self.assertTrue(all(item["last_run_result"] == "ok" for item in receipt["installations"]))

    def test_scan_only_without_sinks_writes_no_receipts_or_user_files(self):
        before = (self.home / "settings.json").read_bytes()
        self.advance("next.txt")
        result = self.run_refresh(scan_only=True)
        self.assertEqual(result.exit_code, 0, result.record())
        self.assertFalse(result.effects_possible)
        self.assertEqual(list(self.home.iterdir()), [self.home / "settings.json"])
        self.assertEqual((self.home / "settings.json").read_bytes(), before)
        self.assertFalse((self.a / "work/next.txt").exists())

    def test_requested_report_and_log_are_exact_masked_invocation_artifacts(self):
        self.document["components"]["archive_manage"].update(output={"mode": "both", "format": "json", "directory": "reports"},
                                                           logging={"enabled": True, "directory": "logs"})
        self.save()
        result = self.run_refresh(scan_only=True)
        self.assertEqual(result.exit_code, 0, result.record())
        self.assertEqual(json.loads(result.report_path.read_text()), result.record())
        self.assertEqual({item["kind"] for item in result.record()["artifacts"]}, {"report", "operational-log"})
        saved_log = result.log_path.read_text()
        self.assertIn("refresh_finished", saved_log)
        self.assertNotIn(str(self.a), saved_log)
        self.assertFalse(registry.registry_path(self.home).exists())

    def test_invalid_output_destination_prevents_all_repository_actions_without_fallback(self):
        self.advance("next.txt")
        occupied = self.home / "occupied"
        occupied.write_text("retain")
        result = self.run_refresh(overrides={"output": {"mode": "both", "directory": str(occupied)}})
        self.assertEqual(result.exit_code, 2)
        self.assertFalse(result.effects_possible)
        self.assertFalse((self.a / "work/next.txt").exists())
        self.assertEqual(occupied.read_text(), "retain")
        self.assertFalse((self.a / ".gitSpecOps").exists())

    def test_required_log_failure_holds_all_actions(self):
        self.advance("next.txt")
        with patch.object(operation, "configure_logging", side_effect=RuntimeIOError("logging_setup")):
            result = self.run_refresh()
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(result.errors, ["logging_setup"])
        self.assertFalse((self.a / "work/next.txt").exists())

    def test_excluded_or_invalid_later_archive_holds_every_archive_before_git(self):
        self.advance("next.txt")
        self.document["defaults"]["scope"] = {"exclude_paths": [str(self.b / "private")]}
        self.save()
        with patch.object(operation, "execute_archive", side_effect=AssertionError("unexpected action")):
            result = self.run_refresh()
        self.assertEqual(result.exit_code, 2)
        self.assertFalse((self.a / "work/next.txt").exists())

    def test_stale_profile_between_archives_retains_partial_results_and_stops(self):
        real = operation.execute_archive
        def first(*args, **kwargs):
            result = real(*args, **kwargs)
            self.document["components"]["archive_manage"]["options"]["archives"] = []
            self.save()
            return result
        self.advance("next.txt")
        with patch.object(operation, "execute_archive", side_effect=first) as execute:
            result = self.run_refresh()
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(result.record()["status"], "partial")
        self.assertEqual(len(result.archives), 1)
        self.assertTrue((self.a / "work/next.txt").exists())
        self.assertFalse((self.b / "work/next.txt").exists())

    def test_receipt_failure_reports_completed_actions_as_partial(self):
        self.advance("next.txt")
        with patch.object(operation, "save_registry", side_effect=SettingsError("private diagnostic")):
            result = self.run_refresh()
        self.assertEqual(result.errors, ["receipts"])
        self.assertEqual(result.record()["status"], "partial")
        self.assertNotIn("private diagnostic", json.dumps(result.record()))

    def test_direct_and_catalog_route_return_one_json_record_without_default_files(self):
        for command in (archive_manager.main, lambda args: gitso.main(["archive-manager", *args])):
            output = io.StringIO()
            with redirect_stdout(output), redirect_stderr(io.StringIO()):
                code = command(["--refresh-all", "--scan-only", "--settings-home", str(self.home), "--json", "--no-log"])
            self.assertEqual(code, 0)
            self.assertEqual(len(json.loads(output.getvalue())["archives"]), 2)
        self.assertFalse(registry.registry_path(self.home).exists())

    def test_single_selection_and_force_sync_preserve_saved_preferences(self):
        before = (self.home / "settings.json").read_bytes()
        result = self.run_refresh(only_root=self.a, scan_only=True, force_sync=True)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(len(result.archives), 1)
        self.assertEqual(result.archives[0]["operation"], "sync")
        self.assertEqual((self.home / "settings.json").read_bytes(), before)
        self.assertEqual(self.run_refresh(only_root=self.root / "unknown").exit_code, 2)

    def plan_with_clone(self, name="new-copy", url=None):
        return sync.DetectResult(str(self.b), SyncPlan(
            to_pull=[LocalRepo("work", str(self.remote), None)],
            to_clone=[RepoRef("fixture-id", "example", name, url or str(self.remote))]))

    def test_sync_can_clone_an_approved_missing_repo_through_shared_action(self):
        with patch.object(sync, "detect_plan", return_value=self.plan_with_clone()):
            result = self.run_refresh(only_root=self.b)
        self.assertEqual(result.exit_code, 0, result.record())
        self.assertTrue((self.b / "new-copy/.git").is_dir())
        self.assertEqual(result.archives[0]["result"]["applied"]["cloned"], 1)

    def test_unsafe_clone_targets_and_changed_allowances_hold_before_any_pull(self):
        for name, url in (("../outside", None), ("nested/name", None), (".GIT", None),
                           ("new-copy", "https://outside.example/project")):
            with self.subTest(name=name), patch.object(sync, "detect_plan", return_value=self.plan_with_clone(name, url)), \
                 patch.object(sync, "fast_forward", side_effect=AssertionError("unexpected pull")), \
                 patch.object(sync, "clone", side_effect=AssertionError("unexpected clone")):
                result = self.run_refresh(only_root=self.b)
            self.assertEqual(result.exit_code, 2)
            self.assertFalse(result.effects_possible)

    def test_log_failure_after_first_archive_stops_later_actions(self):
        self.advance("next.txt")
        from unittest.mock import Mock
        logger = Mock(handler=None)
        def event(name, **kwargs):
            if name == "archive_finished":
                raise RuntimeIOError("logging_write")
        logger.event.side_effect = event
        with patch.object(operation, "configure_logging", return_value=logger):
            result = self.run_refresh()
        self.assertIn("logging_write", result.errors)
        self.assertTrue((self.a / "work/next.txt").exists())
        self.assertFalse((self.b / "work/next.txt").exists())
        self.assertEqual(result.record()["status"], "partial")

    def test_report_failure_is_explicit_and_never_advertises_successful_report(self):
        with patch.object(operation.ReportSink, "write", side_effect=RuntimeIOError("report_write")):
            result = self.run_refresh(scan_only=True, overrides={"output": {"mode": "both", "directory": str(self.home / "reports")}})
        self.assertIn("report_write", result.errors)
        self.assertIsNone(result.report_path)
        self.assertFalse(any(item["kind"] == "report" for item in result.record()["artifacts"]))
        self.assertFalse(list((self.home / "reports").iterdir()))

    def test_master_and_machine_local_values_are_redacted_from_update_and_manager_results(self):
        protected_value = "local-private-marker"
        (self.a / "work").rename(self.a / protected_value)
        self.document["defaults"]["security"] = {"local_never_publish": [protected_value]}
        self.save()
        settings = resolve_document(self.document, "archive_update", home=self.home)
        direct = run_update(settings, UpdateRequest(roots=(self.a,), scan_only=True, approved_prefixes=(str(self.root),)))
        managed = self.run_refresh(only_root=self.a, scan_only=True)
        self.assertNotIn(protected_value, json.dumps(direct.record()))
        self.assertNotIn(protected_value, json.dumps(managed.record()))

    def test_file_only_output_exposes_artifacts_on_stderr_without_mixed_json(self):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = archive_manager.main(["--refresh-all", "--scan-only", "--settings-home", str(self.home),
                                         "--output-mode", "file", "--output-dir", str(self.home / "reports"), "--json", "--no-log"])
        self.assertEqual(code, 0)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("report:", errors.getvalue())
        self.assertEqual(len(list((self.home / "reports").iterdir())), 1)

    def test_refresh_options_and_help_do_not_read_or_change_profiles(self):
        for command in (archive_manager.main, archive_manage.main):
            for options in (["--help"], ["--list", "--json"], ["--refresh-all", "--no-log", "--log-dir", "chosen"],
                             ["--refresh-all", "--no-report", "--output-dir", "chosen"]):
                with self.subTest(options=options), patch.object(operation, "load_registry", side_effect=AssertionError("unexpected read")), \
                     redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    command(options)

    def test_profile_change_during_preflight_prevents_sink_creation_and_actions(self):
        self.document["defaults"].update(output={"mode": "both", "directory": "reports"}, logging={"enabled": True})
        self.save()
        real_scope = operation._scope
        def changing(*args):
            real_scope(*args)
            self.document["components"]["archive_manage"]["options"]["archives"] = []
            self.save()
        with patch.object(operation, "_scope", side_effect=changing), \
             patch.object(operation, "execute_archive", side_effect=AssertionError("unexpected action")):
            result = self.run_refresh()
        self.assertEqual(result.exit_code, 2)
        self.assertFalse((self.home / "logs").exists())
        self.assertFalse((self.home / "reports").exists())

    def test_uri_userinfo_is_redacted_for_ssh_and_other_transports(self):
        for scheme in ("https", "ssh", "git+ssh", "ftp"):
            with self.subTest(scheme=scheme):
                value = conceal(f"{scheme}://example-user:private-marker@host.example/work")
                self.assertNotIn("private-marker", value)
                self.assertIn("host.example/work", value)

    def test_interruption_reports_uncertain_action_and_stops_without_saving_receipts(self):
        with patch.object(operation, "execute_archive", side_effect=KeyboardInterrupt) as execute:
            result = self.run_refresh()
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(result.exit_code, 130)
        self.assertEqual(result.record()["status"], "partial")
        self.assertFalse(registry.registry_path(self.home).exists())

    def test_status_uses_saved_metadata_instead_of_guessing_an_unrelated_report(self):
        location = self.a / "old-generated-reports"
        location.mkdir(parents=True)
        (location / "archive-update-unrelated.json").write_text("unrelated")
        status = archive_manager.installation_status({"root": str(self.a), "last_report": "recorded-report",
                                                       "last_report_at": "2026-01-01T00:00:00"})
        self.assertEqual(status["latest_report"], "recorded-report")
        self.assertEqual(status["latest_report_at"], "2026-01-01T00:00:00")

    def test_unexpected_backend_failure_after_action_is_partial_and_stops_later_archives(self):
        self.advance("next.txt")
        real = operation.execute_archive
        def failing(*args, **kwargs):
            real(*args, **kwargs)
            raise RuntimeError("private backend diagnostic")
        with patch.object(operation, "execute_archive", side_effect=failing) as execute:
            result = self.run_refresh()
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(result.record()["status"], "partial")
        self.assertEqual(len(result.archives), 1)
        self.assertNotIn("private backend diagnostic", json.dumps(result.record()))
        self.assertTrue((self.a / "work/next.txt").exists())
        self.assertFalse((self.b / "work/next.txt").exists())

    def test_logger_close_failure_returns_explicit_partial_result(self):
        from unittest.mock import Mock
        logger = Mock(handler=None)
        logger.close.side_effect = OSError("private close diagnostic")
        with patch.object(operation, "configure_logging", return_value=logger):
            result = self.run_refresh()
        self.assertEqual(result.record()["status"], "partial")
        self.assertIn("logging_write", result.errors)
        self.assertNotIn("private close diagnostic", json.dumps(result.record()))

    def test_linked_cli_output_destinations_are_checked_before_alias_resolution(self):
        target, alias = self.home / "actual", self.home / "alias"
        target.mkdir()
        try:
            alias.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("native directory symlink creation unavailable on this host")
        for command, action in ((archive_manager.main, ["--refresh-all"]),
                                (update_archive.main, ["--root", str(self.a)])):
            with self.subTest(command=command.__module__), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = command([*action, "--settings-home", str(self.home), "--scan-only", "--no-log", "--output-dir", str(alias)])
            self.assertEqual(code, 2)
        self.assertEqual(list(target.iterdir()), [])

    def test_empty_collection_still_honors_requested_report_without_creating_receipts(self):
        self.document["components"]["archive_manage"]["options"]["archives"] = []
        self.save()
        result = self.run_refresh(overrides={"output": {"mode": "both", "format": "json", "directory": str(self.home / "reports")}})
        self.assertEqual(result.exit_code, 0, result.record())
        self.assertEqual(result.archives, [])
        self.assertEqual(json.loads(result.report_path.read_text()), result.record())
        self.assertFalse(registry.registry_path(self.home).exists())


if __name__ == "__main__":
    unittest.main()
