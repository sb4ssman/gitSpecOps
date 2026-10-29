"""Shared archive runner/CLI contracts with disposable Git remotes and invented profiles.

Real pulls/clones/repairs exercise the engine; provider plans and failures are injected only
at external boundaries. No installed tasks, live profiles, external engines or network hosts.
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
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT, setup
setup()

from Special import archive_sync
from Special._archive import operation, sync, sync_cli
from Special._archive.plan import LocalRepo, ReconcileItem, RepoRef, SyncPlan
from Special._settings import resolve_settings
import gitso


class ArchiveSyncTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="archive-sync-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.home, self.archive, self.bare, self.seed = (self.root / name for name in ("profile", "archive", "remote.git", "seed"))
        self.home.mkdir()
        self.archive.mkdir()
        environment = patch.dict(os.environ, {"GITSPECOPS_HOME": str(self.home), "GIT_CONFIG_GLOBAL": os.devnull,
                                              "GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0"})
        environment.start()
        self.addCleanup(environment.stop)
        self.document = {"schema_version": 2, "defaults": {"logging": {"enabled": False},
                         "security": {"never_publish": ["private-fixture-marker"]}}}
        self.save()
        self.git(self.root, "init", "-q", "--bare", "-b", "main", str(self.bare))
        self.git(self.root, "clone", "-q", str(self.bare), str(self.seed))
        self.git(self.seed, "config", "user.name", "orbit-user")
        self.git(self.seed, "config", "user.email", "123+orbit-user@users.noreply.github.com")
        self.git(self.seed, "config", "commit.gpgsign", "false")
        self.advance("base.txt")
        self.work = self.archive / "work"
        self.git(self.root, "clone", "-q", str(self.bare), str(self.work))

    def git(self, repo, *args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                              text=True, timeout=30).stdout.strip()

    def save(self):
        (self.home / "settings.json").write_text(json.dumps(self.document), encoding="utf-8")

    def advance(self, name):
        (self.seed / name).write_text("ordinary", encoding="utf-8")
        self.git(self.seed, "add", "--", name)
        self.git(self.seed, "commit", "-qm", "fixture change")
        self.git(self.seed, "push", "-q", "origin", "main")

    def request(self, mode="sync", **choices):
        return {"root": str(self.archive), "mode": mode, "approved_remote_prefixes": [str(self.root)], **choices}

    def run_operation(self, requests=None, **kwargs):
        return operation.run_archives(resolve_settings("archive_sync", home=self.home),
                                      requests if requests is not None else [self.request()], **kwargs)

    def cli(self, *args, entry=archive_sync.main):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = entry(["--root", str(self.archive), "--settings-home", str(self.home),
                          "--approved-remote-prefix", str(self.root), "--json", *args])
        return code, json.loads(out.getvalue()), err.getvalue()

    def detected(self, plan):
        return sync.DetectResult(root=str(self.archive), plan=plan)

    def commit(self, repo, name="ahead.txt"):
        self.git(repo, "config", "user.name", "orbit-user")
        self.git(repo, "config", "user.email", "123+orbit-user@users.noreply.github.com")
        self.git(repo, "config", "commit.gpgsign", "false")
        (repo / name).write_text("ordinary", encoding="utf-8")
        self.git(repo, "add", "--", name)
        self.git(repo, "commit", "-qm", "fixture ahead")

    def test_explicit_publication_real_push_has_one_masked_result_and_no_provider(self):
        self.commit(self.work)
        tip = self.git(self.work, "rev-parse", "HEAD")
        with patch.object(sync, "detect_plan", side_effect=AssertionError("unexpected discovery")):
            code, record, err = self.cli("--publish", "--yes", "--publish-pause", "0")
        self.assertEqual(code, 0, (record, err))
        self.assertEqual(self.git(self.bare, "rev-parse", "main"), tip)
        published = record["archives"][0]["result"]["publication"]
        self.assertEqual(published[0]["status"], "pushed")
        self.assertIsNotNone(published[0]["security"])
        self.assertNotIn("private-fixture-marker", json.dumps(record))

    def test_publish_preview_binds_tip_without_fetch_or_clearance(self):
        self.commit(self.work)
        base = self.git(self.bare, "rev-parse", "main")
        with patch.object(sync, "publish_checked", side_effect=AssertionError("unexpected gate/fetch")):
            code, record, err = self.cli("--publish", "--dry-run")
        self.assertEqual(code, 0, (record, err))
        payload = record["archives"][0]["result"]
        self.assertEqual(payload["plan"]["to_push"][0]["tip"], self.git(self.work, "rev-parse", "HEAD"))
        self.assertIn("Local plan only", payload["security_notice"])
        self.assertEqual(payload["publication"], [])
        self.assertEqual(self.git(self.bare, "rev-parse", "main"), base)

    def test_changed_security_profile_at_approval_prevents_publication(self):
        self.commit(self.work)
        base = self.git(self.bare, "rev-parse", "main")
        def approve(*_):
            self.document["defaults"]["security"]["never_publish"].append("different-private-marker")
            self.save()
            return True
        with patch.object(sys.stdin, "isatty", return_value=True), patch.object(sync_cli, "_approve", side_effect=approve), \
             patch.object(sync, "publish_checked", side_effect=AssertionError("unexpected gate/fetch")):
            code, record, err = self.cli("--publish")
        self.assertEqual(code, 2, (record, err))
        self.assertFalse(record["effects_possible"])
        self.assertEqual(self.git(self.bare, "rev-parse", "main"), base)
        self.assertNotIn("different-private-marker", json.dumps(record))

    def test_later_publication_interruption_keeps_completed_push_record(self):
        other = self.archive / "z-work"
        self.git(self.root, "clone", "-q", str(self.bare), str(other))
        self.commit(self.work)
        self.commit(other, "other.txt")
        tip = self.git(self.work, "rev-parse", "HEAD")
        real = sync._publish_one
        calls = []
        def publish(path, *args, **kwargs):
            calls.append(path.name)
            if path == other:
                raise KeyboardInterrupt
            return real(path, *args, **kwargs)
        with patch.object(sync, "_publish_one", side_effect=publish):
            result = self.run_operation([self.request("publish", publish_pause=0)], scan_only=False, approve=lambda *_: True)
        self.assertEqual(result.exit_code, 130, result.record())
        self.assertEqual(result.record()["status"], "partial")
        self.assertEqual(calls, ["work", "z-work"])
        payload = result.archives[0]["result"]
        self.assertEqual(payload["applied"]["pushed"], 1)
        self.assertEqual(payload["publication"][0]["status"], "pushed")
        self.assertEqual(self.git(self.bare, "rev-parse", "main"), tip)

    def test_default_and_catalog_plan_to_one_stdout_record_without_files_or_mutation(self):
        self.advance("later.txt")
        for entry in (archive_sync.main, lambda args: gitso.main(["archive-sync", *args])):
            code, record, err = self.cli(entry=entry)
            self.assertEqual(code, 0, err)
            self.assertTrue(record["scan_only"])
            self.assertEqual(record["operation"], "archive_sync")
            self.assertEqual(record["artifacts"], [])
            self.assertFalse((self.work / "later.txt").exists())
        self.assertEqual([path.name for path in self.home.iterdir()], ["settings.json"])
        self.assertFalse((self.archive / ".gitSpecOps").exists())

    def test_private_repo_name_is_masked_in_text_json_and_object_representation(self):
        private = self.archive / "private-fixture-marker"
        self.work.rename(private)
        result = self.run_operation()
        self.assertEqual(result.exit_code, 0, result.record())
        self.assertNotIn("private-fixture-marker", repr(result))
        self.assertNotIn("private-fixture-marker", operation.render_result(result, "text"))
        self.assertNotIn("private-fixture-marker", operation.render_result(result, "json"))
        self.assertIn("[redacted]", operation.render_result(result, "text"))

    def test_explicit_update_real_pull_has_no_discovery_clone_or_publication(self):
        self.advance("later.txt")
        with patch.object(sync, "detect_plan", side_effect=AssertionError("unexpected discovery")), \
             patch.object(sync, "apply_publish", side_effect=AssertionError("unexpected publication")):
            code, record, err = self.cli("--update", "--yes")
        self.assertEqual(code, 0, (record, err))
        self.assertTrue((self.work / "later.txt").exists())

    def test_sync_uses_real_pull_and_clone_without_touching_other_action_classes(self):
        self.advance("later.txt")
        plan = SyncPlan(to_pull=[LocalRepo("work", str(self.bare), None)],
                        to_clone=[RepoRef(id="fixture-new", owner="fixture", name="missing", url=str(self.bare))])
        with patch.object(sync, "detect_plan", return_value=self.detected(plan)), \
             patch.object(sync, "apply_publish", side_effect=AssertionError("unexpected publish")):
            result = self.run_operation(scan_only=False, approve=lambda *_: True)
        self.assertEqual(result.exit_code, 0, result.record())
        self.assertTrue((self.work / "later.txt").exists())
        self.assertTrue((self.archive / "missing" / "later.txt").exists())

    def test_headless_requires_explicit_approval_and_never_prints(self):
        self.advance("later.txt")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            result = self.run_operation(scan_only=False)
        self.assertEqual(result.exit_code, 2)
        self.assertIn("approval_required", result.errors)
        self.assertEqual(out.getvalue() + err.getvalue(), "")
        self.assertFalse((self.work / "later.txt").exists())

    def test_declined_masked_update_plan_prevents_real_pull(self):
        self.advance("later.txt")
        plans = []
        result = self.run_operation([self.request("update")], scan_only=False,
                                    approve=lambda action, plan: plans.append((action, plan)) or False)
        self.assertEqual(result.exit_code, 2, result.record())
        self.assertFalse(result.effects_possible)
        self.assertEqual(plans[0][0], "update")
        self.assertNotIn("private-fixture-marker", json.dumps(plans))
        self.assertFalse((self.work / "later.txt").exists())

    def test_interactive_profile_disappearance_holds_pull_without_default_fallback(self):
        self.advance("later.txt")
        def approve(*_):
            (self.home / "settings.json").unlink()
            return True
        with patch.object(sys.stdin, "isatty", return_value=True), patch.object(sync_cli, "_approve", side_effect=approve):
            code, record, err = self.cli("--update")
        self.assertEqual(code, 2, (record, err))
        self.assertFalse((self.work / "later.txt").exists())
        self.assertFalse((self.home / "logs").exists())

    def test_invalid_required_report_prevents_all_actions_without_fallback(self):
        self.advance("later.txt")
        bad = self.root / "occupied"
        bad.write_text("keep", encoding="utf-8")
        code, record, err = self.cli("--update", "--yes", "--output-dir", str(bad))
        self.assertEqual(code, 2, (record, err))
        self.assertEqual(record["artifacts"], [])
        self.assertEqual(bad.read_text(), "keep")
        self.assertFalse((self.work / "later.txt").exists())
        self.assertFalse((self.home / "reports").exists())

    def test_explicit_report_and_log_are_presented_as_actual_masked_artifacts(self):
        code, record, err = self.cli("--output-dir", str(self.home / "reports"), "--log")
        self.assertEqual(code, 0, err)
        artifacts = {item["kind"]: Path(item["path"]) for item in record["artifacts"]}
        self.assertEqual(set(artifacts), {"report", "operational-log"})
        self.assertEqual(json.loads(artifacts["report"].read_text()), record)
        self.assertNotIn(str(self.archive), artifacts["operational-log"].read_text())

    def test_explicit_origin_and_folder_repairs_use_same_engine_and_real_git(self):
        replacement = self.root / "replacement.git"
        self.git(self.root, "clone", "-q", "--bare", str(self.bare), str(replacement))
        ref = RepoRef(id="fixture-repair", owner="fixture", name="renamed", url=str(replacement))
        plan = SyncPlan(to_reconcile=[ReconcileItem(LocalRepo("work", str(self.bare), None), ref, True, True)])
        with patch.object(sync, "detect_plan", return_value=self.detected(plan)):
            code, record, err = self.cli("--reconcile", "--rename-folders", "--yes")
        self.assertEqual(code, 0, (record, err))
        self.assertFalse(self.work.exists())
        renamed = self.archive / "renamed"
        self.assertEqual(self.git(renamed, "remote", "get-url", "origin"), str(replacement))
        self.assertEqual(record["archives"][0]["result"]["applied"]["renamed"], 1)

    def test_dry_run_never_repairs_or_requires_approval(self):
        ref = RepoRef(id="fixture-repair", owner="fixture", name="renamed", url=str(self.bare))
        plan = SyncPlan(to_reconcile=[ReconcileItem(LocalRepo("work", str(self.bare), None), ref, False, True)])
        with patch.object(sync, "detect_plan", return_value=self.detected(plan)):
            code, record, err = self.cli("--rename-folders", "--dry-run")
        self.assertEqual(code, 0, (record, err))
        self.assertTrue(self.work.exists())
        self.assertFalse((self.archive / "renamed").exists())

    def test_invalid_second_scope_or_duplicate_roots_prevent_first_action(self):
        self.advance("later.txt")
        for requests in ([self.request("update"), self.request("invalid")], [self.request("update"), self.request("update")]):
            result = self.run_operation(requests, scan_only=False, approve=lambda *_: True)
            self.assertEqual(result.exit_code, 2)
            self.assertFalse(result.effects_possible)
        self.assertFalse((self.work / "later.txt").exists())

    def test_unattended_mutations_and_invalid_publish_combinations_fail_before_settings(self):
        with patch.object(sync_cli, "resolve_settings", side_effect=AssertionError("unexpected read")), \
             patch.object(sys.stdin, "isatty", return_value=False), redirect_stderr(io.StringIO()):
            for args in (["--sync"], ["--publish", "--sync"], ["--publish", "--reconcile", "--yes"],
                         ["--publish", "--publish-pause", "nan", "--yes"], ["--include-dirty"], ["--legacy-policy"]):
                with self.subTest(args=args), self.assertRaises(SystemExit) as caught:
                    archive_sync.main(args)
                self.assertEqual(caught.exception.code, 2)

    def test_direct_script_help_from_outside_checkout_creates_no_profile(self):
        absent = self.root / "absent-profile"
        done = subprocess.run([sys.executable, "-B", str(ROOT / "Special" / "archive_sync.py"),
                               "--settings-home", str(absent), "--help"], cwd=self.root,
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("--output-mode", done.stdout)
        self.assertFalse(absent.exists())


if __name__ == "__main__":
    unittest.main()
