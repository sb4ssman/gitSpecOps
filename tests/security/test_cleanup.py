"""Finding-id cleanup plans and public adapters; native effects opt in on temp repos only.

Set GITSPECOPS_RUN_HISTORY_REWRITE=1 to include real cleanup CLI/rewriter/rescan trials.
All profiles, raw reports, plan/workspace writes and history mutations are disposable.
"""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup
setup()

import gitso
from Special._history.operation import execute as native_execute
from Special._history.plan import load
from Special.security import _cleanup_cli
from Special.security._cleanup import run_cleanup
from Special.security._findings import write_report
from Special.security._material import scan
from Special.security._me import load_policy
from Special.security._private_files import write_private_json


class Fixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="security-cleanup-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo, self.home = self.root / "repo", self.root / "profile"
        self.environment = patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                                                   "GIT_OPTIONAL_LOCKS": "0", "GITSPECOPS_HOME": str(self.root / "unused")})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.git("init", "-q", "-b", "main", str(self.repo), cwd=self.root)
        self.git("config", "user.name", "Old Owner")
        self.git("config", "user.email", "old@example.test")
        self.git("config", "core.autocrlf", "false")
        (self.repo / "readme.txt").write_bytes(b"private-marker\n")
        (self.repo / "obsolete").mkdir()
        (self.repo / "obsolete/packaging.txt").write_bytes(b"retired material\n")
        self.save("initial")
        self.document = {"schema_version": 2, "defaults": {"logging": {"enabled": False},
                        "security": {"never_publish": ["private-marker", "old@example.test"]}}}
        self.home.mkdir()
        self.settings = self.home / "settings.json"
        self.settings.write_text(json.dumps(self.document))
        self.report = self.root / "report.json"
        self.refresh_report()
        self.decisions = {"schema_version": 1, "replace_findings": [
            {"finding_id": self.content, "new": "public-marker", "targets": ["blob", "path", "message"],
             "ignore_case": True, "bounded": True}], "remove_files": [], "remove_paths": ["obsolete/"],
            "rewrite_identities": [{"finding_id": self.identity, "name": "Public Owner",
                                    "email": "101+owner@users.noreply.github.com"}]}
        self.choices, self.plan_path = self.root / "choices.json", self.root / "plan.json"
        self.choices.write_text(json.dumps(self.decisions))

    def git(self, *args, cwd=None):
        result = subprocess.run(["git", "-C", str(cwd or self.repo), *args], capture_output=True,
                                check=True, timeout=30)
        return result.stdout.decode().strip()

    def save(self, message):
        self.git("add", "-A")
        self.git("-c", "commit.gpgsign=false", "commit", "--allow-empty", "-qm", message)

    def refresh_report(self):
        if self.report.exists():
            self.report.unlink()
        checked = scan(self.repo, load_policy(self.repo, home=self.home), material="history", engines=())
        write_report(self.report, checked)
        rows = checked.record(redacted=False)["findings"]
        self.content = next(row["finding_id"] for row in rows if row["where"] == "readme.txt" and row["value"] == "private-marker")
        self.identity = next(row["finding_id"] for row in rows if row["where"] == "author" and row["value"] == "old@example.test")

    def plan(self, **kwargs):
        return run_cleanup("plan", self.report, choices=self.choices, home=self.home, **kwargs)


class CleanupPlans(Fixture):
    def test_preview_needs_no_raw_value_and_creates_no_plan_or_profile_fallback(self):
        before = sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*"))
        result = self.plan()
        self.assertEqual(result.status, "planned", result.record())
        self.assertEqual(result.counts["identity_pairs"], 1)
        self.assertEqual(result.decisions["replace_findings"][0]["finding_id"], self.content)
        self.assertNotIn("private-marker", json.dumps(result.record()))
        self.assertNotIn("old@example.test", json.dumps(result.record()))
        self.assertEqual(before, sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*")))
        self.assertFalse((self.root / "unused").exists())

    def test_saved_plan_binds_explicit_scope_and_policy_without_global_allowances(self):
        before = self.settings.read_bytes()
        result = self.plan(plan_out=self.plan_path)
        self.assertEqual(result.status, "planned", result.record())
        plan = load(self.plan_path)
        self.assertEqual(plan.choices["remove_paths"], ["obsolete/"])
        self.assertEqual(plan.choices["replacements"][0]["old"], "private-marker")
        self.assertEqual(plan.choices["identities"][0]["old_email"], "old@example.test")
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertTrue(any(item["kind"] == "saved cleanup plan" for item in result.artifacts))
        refused = self.plan(overrides={"security": {"safe_values": ["private-marker"]}})
        self.assertEqual(refused.status, "incomplete")
        self.assertEqual(self.settings.read_bytes(), before)

    def test_stale_refs_tampered_values_and_empty_choices_refuse(self):
        raw = json.loads(self.report.read_text())
        row = next(row for row in raw["findings"] if row["finding_id"] == self.content)
        row["value"] = "different-value"
        self.report.write_text(json.dumps(raw))
        self.assertEqual(self.plan().status, "incomplete")
        self.refresh_report()
        self.decisions.update(replace_findings=[], remove_paths=[], rewrite_identities=[])
        self.choices.write_text(json.dumps(self.decisions))
        self.assertEqual(self.plan().status, "incomplete")
        self.save("moved")
        self.assertEqual(self.plan().status, "incomplete")
        self.assertFalse(self.plan_path.exists())

    def test_file_selection_means_whole_file_and_never_inferred_directory_purge(self):
        self.decisions.update(replace_findings=[], remove_files=[self.content], remove_paths=[])
        self.choices.write_text(json.dumps(self.decisions))
        result = self.plan(plan_out=self.plan_path)
        self.assertEqual(result.status, "planned", result.record())
        self.assertEqual(load(self.plan_path).choices["remove_paths"], ["readme.txt"])

    def test_missing_or_changed_settings_hold_application_before_mirror_creation(self):
        planned = self.plan(plan_out=self.plan_path)
        self.assertEqual(planned.status, "planned")
        self.settings.unlink()
        with patch("Special.security._cleanup.execute", side_effect=AssertionError("must not rewrite")):
            result = run_cleanup("apply", self.plan_path, workspace=self.root / "output",
                                 approve=planned.plan_id, confirmation="REWRITE", home=self.home)
        self.assertEqual(result.status, "incomplete")
        self.assertFalse((self.root / "output").exists())
        self.assertFalse((self.root / "unused").exists())

    def test_excluded_inputs_are_not_read(self):
        self.document["defaults"]["scope"] = {"exclude_paths": [str(self.report)]}
        self.settings.write_text(json.dumps(self.document))
        with patch("Special.security._cleanup.read_private_json", side_effect=AssertionError("must not read")):
            self.assertEqual(self.plan().status, "incomplete")

    def test_excluded_saved_plan_is_not_read_and_profile_mismatch_is_not_fallback(self):
        planned = self.plan(plan_out=self.plan_path)
        with patch("Special.security._cleanup.execute", side_effect=AssertionError("must not rewrite")):
            result = run_cleanup("apply", self.plan_path, workspace=self.root / "output",
                                 approve=planned.plan_id, confirmation="REWRITE")
        self.assertIn("same settings home", result.message)
        self.assertFalse((self.root / "unused").exists())
        self.document["defaults"]["scope"] = {"exclude_paths": [str(self.plan_path)]}
        self.settings.write_text(json.dumps(self.document))
        with patch("Special.security._cleanup.load", side_effect=AssertionError("must not read")):
            result = run_cleanup("apply", self.plan_path, workspace=self.root / "output", home=self.home,
                                 approve=planned.plan_id, confirmation="REWRITE")
        self.assertEqual(result.status, "incomplete")
        self.assertFalse((self.root / "output").exists())

    def test_explicit_remote_inclusion_is_needed_and_scope_is_presented(self):
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        self.refresh_report()
        self.decisions["replace_findings"][0]["finding_id"] = self.content
        self.decisions["rewrite_identities"][0]["finding_id"] = self.identity
        self.choices.write_text(json.dumps(self.decisions))
        self.assertEqual(self.plan().status, "incomplete")
        result = self.plan(include_remote_refs=True, plan_out=self.plan_path)
        self.assertEqual(result.status, "planned", result.record())
        self.assertEqual((result.counts["remote_refs"], result.counts["symbolic_refs"]), (2, 1))
        self.assertTrue(load(self.plan_path).include_remote_refs)

    def test_common_file_report_and_counts_log_are_presented_without_raw_values(self):
        result = self.plan(overrides={"output": {"mode": "file", "format": "json", "directory": str(self.root / "reports")},
                                     "logging": {"enabled": True, "directory": str(self.root / "logs")}})
        self.assertEqual(result.status, "planned", result.record())
        saved = next(item for item in result.artifacts if item["kind"] == "masked operation report")
        text = Path(saved["path"]).read_text()
        self.assertEqual(json.loads(text)["status"], "planned")
        log = (self.root / "logs/security_cleanup.log").read_text()
        self.assertNotIn("private-marker", text + log)
        self.assertNotIn("old@example.test", text + log)
        self.assertNotIn(str(self.repo), log)

    def test_unignored_report_destination_is_removed_and_never_falls_back(self):
        result = self.plan(overrides={"output": {"mode": "file", "directory": str(self.repo / "reports")}})
        self.assertEqual(result.status, "incomplete")
        self.assertFalse(list((self.repo / "reports").glob("*")))
        self.assertFalse((self.home / "reports").exists())
        self.assertFalse(result.artifacts)

    def test_direct_and_catalog_plan_route_share_the_headless_operation(self):
        for invoke in (_cleanup_cli.main, lambda args: gitso.main(["clean-history", *args])):
            output = io.StringIO()
            with redirect_stdout(output):
                code = invoke(["plan", str(self.report), "--choices", str(self.choices),
                               "--settings-home", str(self.home), "--json"])
            self.assertEqual(code, 0, output.getvalue())
            self.assertEqual(json.loads(output.getvalue())["status"], "planned")

    def test_unattended_apply_refuses_before_plan_read_or_prompt(self):
        with patch.object(sys.stdin, "isatty", return_value=False), redirect_stderr(io.StringIO()), \
             patch("Special.security._cleanup_cli.run_cleanup", side_effect=AssertionError("must not run")), \
             self.assertRaises(SystemExit) as error:
            _cleanup_cli.main(["apply", "private-plan.json", "--workspace", "new-output", "--approve", "plan-id"])
        self.assertEqual(error.exception.code, 2)

    def test_declined_typed_approval_never_starts_the_operation(self):
        with patch.object(sys.stdin, "isatty", return_value=True), patch.object(sys.stdout, "isatty", return_value=True), \
             patch("builtins.input", return_value="yes"), redirect_stderr(io.StringIO()), \
             patch("Special.security._cleanup_cli.run_cleanup", side_effect=AssertionError("must not run")):
            self.assertEqual(_cleanup_cli.main(["apply", "private-plan.json", "--workspace", "new-output", "--approve", "plan-id"]), 130)

    def test_requested_report_failure_stops_before_rewriting_without_fallback(self):
        from Special._runtime.files import RuntimeIOError
        planned = self.plan(plan_out=self.plan_path)
        with patch("Special.security._cleanup.ReportSink", side_effect=RuntimeIOError("report_setup")), \
             patch("Special.security._cleanup.execute", side_effect=AssertionError("must not rewrite")):
            result = run_cleanup("apply", self.plan_path, workspace=self.root / "output", home=self.home,
                                 approve=planned.plan_id, confirmation="REWRITE",
                                 overrides={"output": {"mode": "both", "directory": str(self.root / "reports")}})
        self.assertEqual(result.status, "incomplete")
        self.assertFalse(result.effects_possible)
        self.assertFalse((self.root / "output").exists())
        self.assertFalse((self.home / "reports").exists())

    def test_failed_required_log_is_closed_and_does_not_start_rewriting(self):
        from Special._runtime.files import RuntimeIOError
        closed = []
        def fail_event(*args, **kwargs):
            raise RuntimeIOError("logging_write")
        log = SimpleNamespace(handler=None, event=fail_event, close=lambda: closed.append(True))
        with patch("Special.security._cleanup.configure_logging", return_value=log):
            result = self.plan(plan_out=self.plan_path)
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(closed, [True])
        self.assertFalse(self.plan_path.exists())

    def test_interruption_keeps_actual_artifacts_in_masked_partial_result(self):
        planned = self.plan(plan_out=self.plan_path)
        def interrupted(plan, workspace, **kwargs):
            path = write_private_json(self.root / "partial.json", {"stage": "fixture"})
            kwargs["artifacts"].append(path)
            raise KeyboardInterrupt()
        with patch("Special.security._cleanup.execute", side_effect=interrupted):
            result = run_cleanup("apply", self.plan_path, workspace=self.root / "output",
                                 approve=planned.plan_id, confirmation="REWRITE", home=self.home)
        self.assertEqual(result.exit_code, 130)
        self.assertTrue(result.effects_possible)
        self.assertTrue(any(item["path"] == str(self.root / "partial.json") for item in result.artifacts))


@unittest.skipUnless(os.environ.get("GITSPECOPS_RUN_HISTORY_REWRITE") == "1", "explicit native rewrite trial not selected")
class NativeCleanup(Fixture):
    def test_selected_missing_engine_never_turns_rewritten_mirror_into_verified_result(self):
        with patch("Special.security._engines.shutil.which", return_value=None):
            planned = self.plan(plan_out=self.plan_path, engines=["gitleaks"])
            self.assertEqual(planned.status, "planned", planned.record())
            self.assertTrue(planned.check["gaps"])
            result = run_cleanup("apply", self.plan_path, workspace=self.root / "output", home=self.home,
                                 approve=planned.plan_id, confirmation="REWRITE")
        self.assertEqual(result.status, "incomplete", result.record())
        self.assertEqual(result.check["engines"], {"gitleaks": "incomplete"})
        self.assertTrue((self.root / "output/mirror.git").is_dir())
        self.assertFalse(result.record()["publication_clearance"])

    def test_unselected_binary_is_retained_and_remains_an_explicit_coverage_gap(self):
        (self.repo / "retained.dat").write_bytes(b"unrelated\0binary")
        self.save("unrelated binary")
        self.refresh_report()
        self.decisions["replace_findings"][0]["finding_id"] = self.content
        self.decisions["rewrite_identities"][0]["finding_id"] = self.identity
        self.choices.write_text(json.dumps(self.decisions))
        planned = self.plan(plan_out=self.plan_path)
        self.assertEqual(planned.status, "planned", planned.record())
        result = run_cleanup("apply", self.plan_path, workspace=self.root / "output", home=self.home,
                             approve=planned.plan_id, confirmation="REWRITE")
        self.assertEqual(result.status, "incomplete", result.record())
        self.assertTrue(result.check["gaps"])
        self.assertEqual(self.git("show", "HEAD:retained.dat", cwd=self.root / "output/mirror.git"), "unrelated\0binary")
        self.assertFalse(result.record()["publication_clearance"])

    def test_catalog_plan_and_attended_direct_apply_prove_and_rescan_remote_refs(self):
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        self.refresh_report()
        self.decisions["replace_findings"][0]["finding_id"] = self.content
        self.decisions["rewrite_identities"][0]["finding_id"] = self.identity
        self.choices.write_text(json.dumps(self.decisions))
        before = self.git("rev-parse", "HEAD"), (self.repo / ".git/index").read_bytes()
        output = io.StringIO()
        with redirect_stdout(output):
            code = gitso.main(["clean-history", "plan", str(self.report), "--choices", str(self.choices),
                               "--settings-home", str(self.home), "--include-remote-refs", "--plan-out", str(self.plan_path), "--json"])
        self.assertEqual(code, 0, output.getvalue())
        plan_id = json.loads(output.getvalue())["plan_id"]
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()), patch.object(sys.stdin, "isatty", return_value=True), \
             patch.object(sys.stdout, "isatty", return_value=True), patch("builtins.input", return_value="REWRITE"):
            code = _cleanup_cli.main(["apply", str(self.plan_path), "--workspace", str(self.root / "output"),
                                      "--approve", plan_id, "--settings-home", str(self.home), "--json"])
        self.assertEqual(code, 0, output.getvalue())
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["check"]["coverage"], "complete-for-selected-checks")
        self.assertFalse(result["publication_clearance"])
        self.assertNotIn("private-marker", output.getvalue())
        self.assertNotIn("old@example.test", output.getvalue())
        self.assertEqual(before, (self.git("rev-parse", "HEAD"), (self.repo / ".git/index").read_bytes()))
        self.assertTrue((self.root / "output/rescan.json").is_file())

    def test_policy_loss_during_rewrite_retains_mirror_without_success_or_fallback(self):
        planned = self.plan(plan_out=self.plan_path)
        def lose_settings(*args, **kwargs):
            outcome = native_execute(*args, **kwargs)
            self.settings.unlink()
            return outcome
        with patch("Special.security._cleanup.execute", side_effect=lose_settings):
            result = run_cleanup("apply", self.plan_path, workspace=self.root / "output",
                                 approve=planned.plan_id, confirmation="REWRITE", home=self.home)
        self.assertEqual(result.status, "incomplete", result.record())
        self.assertTrue((self.root / "output/mirror.git").is_dir())
        self.assertTrue(any(item["kind"] == "rewritten private mirror" for item in result.artifacts))
        self.assertFalse(result.record()["publication_clearance"])
        self.assertFalse((self.root / "unused").exists())


if __name__ == "__main__":
    unittest.main()
