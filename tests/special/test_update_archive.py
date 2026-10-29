"""Standalone updater integration with invented settings, scopes and temporary Git repos."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup
setup()

from Special import update_archive as public
from Special._archive import updater, update_cli
from Special._archive.plan import RepoInfo
from Special._runtime.files import RuntimeIOError, SOURCE_ROOT
from Special._settings import resolve_settings


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="archive-operation-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home, self.archive = self.root / "home", self.root / "archive"
        self.archive.mkdir()
        self.env = patch.dict(os.environ, {"GITSPECOPS_HOME": str(self.home),
                                          "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def save(self, defaults=None, components=None):
        self.home.mkdir(exist_ok=True)
        (self.home / "settings.json").write_text(json.dumps({"schema_version": 2,
            "defaults": defaults or {}, "components": components or {}}), encoding="utf-8")

    def settings(self, **sections):
        overrides = {"scope": {"roots": [str(self.archive)]}, "logging": {"enabled": False}}
        overrides.update(sections)
        return resolve_settings("archive_update", overrides=overrides)

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = public.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def repo(self, name="work", origin="https://example.test/team/work"):
        path = self.archive / name
        path.mkdir(exist_ok=True)
        return RepoInfo(name=name, path=str(path), hidden=False, has_git_marker=True,
            is_work_tree=True, origin_present=True, origin=origin, host="example.test",
            approved_remote=True, branch="main", dirty_work_tree=False, dirty_index=False,
            eligible=True, action="eligible: pull --ff-only")

    def test_help_never_resolves_settings_or_creates_state(self):
        with patch.object(update_cli, "resolve_settings", side_effect=AssertionError("must not read")), \
             redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as stopped:
            public.main(["--help"])
        self.assertEqual(stopped.exception.code, 0)
        self.assertFalse(self.home.exists())

    def test_fresh_stdout_and_disabled_logging_create_no_user_files(self):
        code, out, err = self.cli("--root", str(self.archive), "--scan-only", "--json", "--no-log")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["status"], "ok")
        self.assertFalse(self.home.exists())

    def test_default_logging_is_counts_only_and_reports_remain_off(self):
        repo = self.repo("private-marker")
        with patch.object(updater, "inspect_candidate", return_value=repo):
            code, out, err = self.cli("--root", str(self.archive), "--scan-only", "--json")
        self.assertEqual(code, 0, err)
        self.assertFalse(any(item["kind"] == "report" for item in json.loads(out)["artifacts"]))
        log = (self.home / "logs" / "archive_update.log").read_text()
        self.assertNotIn("private-marker", log)
        self.assertNotIn(str(self.archive), log)
        self.assertFalse((self.home / "reports").exists())
        self.assertTrue(all(json.loads(line)["component"] == "archive_update" for line in log.splitlines()))

    def test_saved_component_preferences_and_explicit_stdout_override(self):
        self.save({"scope": {"roots": [str(self.archive)]}, "logging": {"enabled": False}},
                  {"archive_update": {"output": {"mode": "both", "format": "json", "directory": "chosen"}}})
        code, out, err = self.cli("--scan-only")
        self.assertEqual(code, 0, err)
        record = json.loads(out)
        self.assertEqual(json.loads(Path(next(item["path"] for item in record["artifacts"] if item["kind"] == "report")).read_text()), record)
        before = list((self.home / "chosen").iterdir())
        code, out, err = self.cli("--scan-only", "--no-report")
        self.assertEqual(code, 0, err)
        self.assertFalse(any(item["kind"] == "report" for item in json.loads(out)["artifacts"]))
        self.assertEqual(list((self.home / "chosen").iterdir()), before)

    def test_explicit_root_replaces_saved_roots(self):
        self.save({"scope": {"roots": [str(self.root / "missing")]}, "logging": {"enabled": False}})
        code, out, err = self.cli("--root", str(self.archive), "--scan-only", "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["roots"][0]["scan"]["root"], str(self.archive.resolve()))

    def test_exclusions_prevent_git_inspection_and_empty_scope_never_expands(self):
        hidden = self.archive / "excluded"
        hidden.mkdir()
        nested = hidden / "private-subtree"
        with patch.object(updater, "inspect_candidate", side_effect=AssertionError("excluded repo inspected")):
            result = public.run_update(self.settings(scope={"roots": [str(self.archive)],
                "exclude_paths": [str(nested)]}), public.UpdateRequest(scan_only=True))
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.reports[0].excluded_folders, 1)
        with patch.object(updater, "scan_root") as scan:
            result = public.run_update(self.settings(), public.UpdateRequest(roots=()))
        self.assertEqual(result.exit_code, 2)
        scan.assert_not_called()

    def test_excluded_root_refuses_before_inspection_or_output_setup(self):
        settings = self.settings(scope={"roots": [str(self.archive)], "exclude_paths": [str(self.archive)]},
                                 output={"mode": "both"})
        with patch.object(updater, "scan_root") as scan:
            result = public.run_update(settings)
        self.assertEqual(result.errors, ["excluded_root"])
        scan.assert_not_called()
        self.assertFalse(self.home.exists())

    def test_invalid_report_and_log_destinations_prevent_pulls(self):
        bad = self.root / "not-directory"
        bad.write_text("retained")
        for section, value in (("output", {"mode": "both", "directory": str(bad)}),
                               ("logging", {"enabled": True, "directory": str(bad)})):
            with self.subTest(section=section), patch.object(updater, "update_repo") as pull:
                result = public.run_update(self.settings(**{section: value}))
            self.assertEqual(result.exit_code, 2)
            pull.assert_not_called()
        self.assertEqual(bad.read_text(), "retained")

    def test_required_log_failure_does_not_fall_back_or_pull(self):
        with patch("Special._archive.update_operation.configure_logging", side_effect=RuntimeIOError("logging_busy")), \
             patch.object(updater, "update_repo") as pull:
            result = public.run_update(self.settings(output={"mode": "both"}, logging={"enabled": True}))
        self.assertEqual(result.exit_code, 2)
        self.assertIsNone(result.report_path)
        self.assertEqual(list((self.home / "reports").iterdir()), [])
        pull.assert_not_called()

    def test_failed_pull_returns_one_and_credentials_never_reach_presentation(self):
        credential = "ghp_" + "A" * 30
        repo = self.repo("private-marker", "https://user:" + credential + "@example.test/work")
        settings = self.settings(security={"never_publish": ["private-marker"]})
        with patch.object(updater, "inspect_candidate", return_value=repo), \
             patch.object(updater, "update_repo", return_value="failed: fetch " + credential), \
             redirect_stdout(io.StringIO()) as out:
            result = public.run_update(settings)
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(result.exit_code, 1)
        rendered = public.render_result(result, "json") + public.render_result(result, "text", show_remote_urls=True)
        self.assertNotIn(credential, rendered)
        self.assertNotIn("private-marker", rendered)
        self.assertNotIn("private-marker", repr(result))
        self.assertIn(credential, json.dumps(result.record(redacted=False)))

    def test_file_mode_has_no_stdout_and_reports_never_overwrite(self):
        args = ["--root", str(self.archive), "--scan-only", "--output-dir", str(self.root / "reports"),
                "--output-mode", "file", "--json", "--no-log"]
        for _ in range(2):
            code, out, err = self.cli(*args)
            self.assertEqual((code, out), (0, ""), err)
            self.assertIn("report: ", err)
            self.assertIn(str(self.root / "reports"), err)
        reports = list((self.root / "reports").glob("*.json"))
        self.assertEqual(len(reports), 2)
        self.assertTrue(all(json.loads(path.read_text())["status"] == "ok" for path in reports))

    def test_json_respects_remote_url_visibility_and_explicit_relative_report_location(self):
        repo = self.repo()
        with patch.object(updater, "inspect_candidate", return_value=repo):
            result = public.run_update(self.settings(), public.UpdateRequest(scan_only=True))
        hidden = json.loads(public.render_result(result, "json"))
        visible = json.loads(public.render_result(result, "json", show_remote_urls=True))
        self.assertEqual(hidden["roots"][0]["scan"]["repos"][0]["origin"], "present")
        self.assertEqual(visible["roots"][0]["scan"]["repos"][0]["origin"], repo.origin)
        code, out, err = self.cli("--root", str(self.archive), "--scan-only", "--json", "--no-log",
                                  "--default-output-dir", "reports")
        self.assertEqual(code, 0, err)
        self.assertEqual(Path(next(item["path"] for item in json.loads(out)["artifacts"] if item["kind"] == "report")).parent, self.archive / "reports")

    def test_logging_failure_after_a_pull_stops_later_repositories(self):
        first, second = self.repo("first"), self.repo("second")
        from Special._runtime.logger import OperationalLog
        class FailingLog(OperationalLog):
            def event(self, name, **counts):
                if name == "repository_finished":
                    raise RuntimeIOError("logging_write")
        with patch.object(updater, "inspect_candidate", side_effect=[first, second]), \
             patch.object(updater, "update_repo", return_value="updated") as pull, \
             patch("Special._archive.update_operation.configure_logging", return_value=FailingLog()):
            result = public.run_update(self.settings())
        self.assertEqual(pull.call_count, 1)
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(result.record()["status"], "partial")
        self.assertEqual(second.result, "not run")

    def test_update_progress_is_stderr_and_json_stdout_remains_one_record(self):
        repo = self.repo("private-marker")
        self.save({"security": {"never_publish": ["private-marker"]}, "logging": {"enabled": False}})
        with patch.object(updater, "inspect_candidate", return_value=repo), \
             patch.object(updater, "update_repo", return_value="updated"):
            code, out, err = self.cli("--root", str(self.archive), "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["roots"][0]["summary"]["updated"], ["[redacted]"])
        self.assertIn("[PULL]", err)
        self.assertNotIn("private-marker", out + err)

    def test_report_write_failure_after_update_returns_partial_without_fallback(self):
        repo = self.repo()
        settings = self.settings(output={"mode": "both", "format": "json"})
        with patch.object(updater, "inspect_candidate", return_value=repo), \
             patch.object(updater, "update_repo", return_value="updated") as pull, \
             patch("Special._archive.update_operation.ReportSink.write", side_effect=OSError("private-marker")):
            result = public.run_update(settings)
        self.assertTrue(pull.called)
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(result.record()["status"], "partial")
        self.assertIsNone(result.report_path)
        self.assertNotIn("private-marker", public.render_result(result, "text"))
        self.assertEqual(list((self.home / "reports").iterdir()), [])

    def test_malformed_or_legacy_settings_error_instead_of_profile_fallback(self):
        self.home.mkdir()
        source = self.home / "settings.json"
        source.write_text("{broken")
        code, out, err = self.cli("--root", str(self.archive), "--no-log")
        self.assertEqual((code, out), (2, ""))
        source.unlink()
        (self.home / "security").mkdir()
        (self.home / "security" / "never_publish.txt").write_text("private-marker")
        code, out, err = self.cli("--root", str(self.archive), "--no-log")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("migration", err)
        self.assertFalse((self.home / "logs").exists())

    def test_conflicting_flags_and_source_runtime_destinations_are_errors(self):
        for flags in (("--no-report", "--output-dir", str(self.root / "reports")),
                      ("--no-log", "--log-dir", str(self.root / "logs"))):
            self.assertEqual(self.cli("--root", str(self.archive), *flags)[0], 2)
        result = public.run_update(self.settings(output={"mode": "both", "directory": str(SOURCE_ROOT / "logs")}))
        self.assertEqual(result.errors, ["source_destination"])

    def test_real_local_fast_forward_keeps_dirty_checkout_untouched(self):
        def git(*args):
            return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()
        bare, seed, work = self.root / "remote.git", self.root / "seed", self.archive / "work"
        git("init", "--bare", "-q", "-b", "main", str(bare))
        git("clone", "-q", str(bare), str(seed))
        git("-C", str(seed), "config", "user.name", "Fixture")
        git("-C", str(seed), "config", "user.email", "fixture@example.test")
        (seed / "tracked.txt").write_text("first")
        git("-C", str(seed), "add", "tracked.txt")
        git("-C", str(seed), "-c", "commit.gpgsign=false", "commit", "-qm", "first")
        git("-C", str(seed), "push", "-q", "origin", "main")
        git("clone", "-q", str(bare), str(work))
        (seed / "tracked.txt").write_text("second")
        git("-C", str(seed), "add", "tracked.txt")
        git("-C", str(seed), "-c", "commit.gpgsign=false", "commit", "-qm", "second")
        git("-C", str(seed), "push", "-q", "origin", "main")
        request = public.UpdateRequest(approved_prefixes=(str(self.root),))
        result = public.run_update(self.settings(), request)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual((work / "tracked.txt").read_text(), "second")
        (work / "tracked.txt").write_text("local edit")
        with patch.object(updater, "update_repo", side_effect=AssertionError("dirty checkout pulled")):
            result = public.run_update(self.settings(), request)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual((work / "tracked.txt").read_text(), "local edit")
        self.assertFalse(result.reports[0].repos[0].eligible)


if __name__ == "__main__":
    unittest.main()
