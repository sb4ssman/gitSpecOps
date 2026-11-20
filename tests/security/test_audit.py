"""The web view's security audit, in disposable Git repositories only.

Pins: a value committed and later deleted is found in history and not in the current files;
results are masked and carry no folder path; only repository ids the observer knows are
audited; one audit runs at a time and can be stopped; engines are only looked at, never run
unless chosen. No user settings, scanner installation or network.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Special._security._audit import AuditJobs, audit_checkout, engines_status  # noqa: E402


class AuditTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="audit-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.repo, self.home = self.root / "checkout", self.root / "profile"
        self.home.mkdir()
        environment = patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                                              "GITSPECOPS_HOME": str(self.home), "GIT_OPTIONAL_LOCKS": "0"})
        environment.start()
        self.addCleanup(environment.stop)
        self.git(self.root, "init", "-q", "-b", "main", str(self.repo))
        for key, value in (("user.name", "orbit-user"), ("user.email", "123+orbit-user@users.noreply.github.com"),
                           ("commit.gpgsign", "false"), ("core.autocrlf", "false")):
            self.git(self.repo, "config", key, value)
        (self.home / "settings.json").write_text(json.dumps(
            {"schema_version": 2, "defaults": {"security": {"never_publish": ["private-marker"]}}}), encoding="utf-8")
        self.commit("notes.txt", "the private-marker slipped in")
        self.commit("notes.txt", "cleaned up")

    def git(self, cwd, *arguments):
        subprocess.run(["git", *arguments], cwd=cwd, check=True, capture_output=True)

    def commit(self, name, text):
        (self.repo / name).write_text(text, encoding="utf-8")
        self.git(self.repo, "add", name)
        self.git(self.repo, "commit", "-q", "-m", "change")

    def test_history_finds_what_the_current_files_no_longer_show(self):
        result = audit_checkout(self.repo, history=True, settings_home=self.home)
        tree = [f for f in result["working_tree"]["findings"] if f["classification"] != "quiet"]
        past = [f for f in result["history"]["findings"] if f["classification"] != "quiet"]
        self.assertEqual(tree, [], "the current files are clean")
        self.assertTrue(past, "the deleted value is still in history")
        self.assertEqual(result["check_status"], "blocked", "a never-publish value is high severity")
        text = json.dumps(result)
        self.assertNotIn("private-marker", text, "values are masked")
        self.assertNotIn(str(self.repo), text, "no folder path reaches the web view")
        quick = audit_checkout(self.repo, history=False, settings_home=self.home)
        self.assertIsNone(quick["history"], "files only when history is not asked for")

    def test_browser_history_storage_requires_opt_in_and_disable_preserves_file(self):
        from Special._security._policy_edit import audit_cache_change, audit_cache_view

        def run():
            return audit_checkout(self.repo, settings_home=self.home, cache=None)["history"]

        settings = audit_cache_view(self.home)
        database = Path(settings["path"])
        self.assertFalse(settings["enabled"])
        self.assertNotIn("checkpoint", run())
        self.assertFalse(database.exists())

        enabled = audit_cache_change(self.home, {"audit_history_cache": True})
        self.assertTrue(enabled["enabled"])
        self.assertFalse(database.exists(), "enabling stores the preference only")
        self.assertEqual(run()["checkpoint"]["mode"], "full")
        self.assertTrue(database.exists())

        original = database.read_bytes()
        audit_cache_change(self.home, {"audit_history_cache": False})
        self.assertNotIn("checkpoint", run())
        self.assertEqual(database.read_bytes(), original)

    def test_history_checkpoint_reuses_masked_results_and_a_fresh_scan_can_reveal(self):
        def audit(**options):
            return audit_checkout(self.repo, settings_home=self.home, cache=True, **options)

        first = audit()
        self.assertEqual(first["history"]["checkpoint"]["mode"], "full")
        self.assertEqual(first["history"]["coverage"], "complete-for-selected-checks")
        values = {}
        reused = audit(values=values)
        self.assertEqual(reused["check_status"], "blocked")
        self.assertEqual(reused["history"]["checkpoint"],
                         {"mode": "reused", "reused_commits": 2, "new_commits": 0})
        self.assertNotIn("history", values)
        self.assertNotIn(b"private-marker", (self.home / "security-history.sqlite3").read_bytes())
        fresh = audit(values=values, fresh=True)
        self.assertEqual(fresh["history"]["checkpoint"]["mode"], "full")
        self.assertIn("private-marker", values["history"])

    def test_clean_history_checkpoint_handles_new_commits_and_unmerged_branch(self):
        self.git(self.repo, "checkout", "--orphan", "clean")
        self.commit("notes.txt", "a new unrelated history")
        self.git(self.repo, "branch", "-D", "main")

        def history():
            return audit_checkout(self.repo, settings_home=self.home, cache=True)["history"]

        first = history()
        self.assertEqual(first["checkpoint"]["mode"], "full")
        self.assertFalse(first["findings"])
        self.git(self.repo, "checkout", "-b", "side")
        self.commit("side.txt", "another change")
        self.git(self.repo, "checkout", "clean")
        self.commit("notes.txt", "a change on the original branch")
        delta = history()
        self.assertEqual(delta["checkpoint"], {"mode": "incremental", "reused_commits": 1, "new_commits": 2})
        self.assertEqual(delta["commits"], 3)
        self.git(self.repo, "branch", "-D", "side")
        self.assertEqual(history()["checkpoint"]["mode"], "full")

    def test_history_checkpoint_invalidates_when_private_policy_changes(self):
        default = audit_checkout(self.repo, settings_home=self.home, cache=True)
        self.assertEqual(default["history"]["check_status"], "blocked")
        (self.home / "settings.json").write_text(json.dumps(
            {"schema_version": 2, "defaults": {"security": {"never_publish": ["unrelated-value"]}}}), encoding="utf-8")
        updated = audit_checkout(self.repo, settings_home=self.home, cache=True)
        self.assertEqual(updated["history"]["checkpoint"]["mode"], "full")
        self.assertEqual(updated["history"]["check_status"], "passed")

    def test_coverage_receipt_omits_findings_locations_and_ref_names(self):
        from Special._security._audit import coverage_receipt

        result = audit_checkout(self.repo, settings_home=self.home)
        audit = {"results": [{"repo_id": "a" * 32, "checkout": 1, "security": result}],
                 "started_at": "now", "finished_at": None, "state": "running", "engines": [],
                 "history": True, "total": 2, "done": 1}
        receipt = coverage_receipt(audit, "test-machine")
        self.assertEqual(receipt["repositories_finished"], 1)
        self.assertEqual(receipt["checkouts"][0]["history"]["commits_scanned"], 2)
        from Elaborate._transport.folder import FolderTransport

        shared = FolderTransport(self.root)
        published = shared.write_audit_coverage("test-machine", json.dumps(receipt).encode())
        self.assertEqual(published, self.root / "audit-coverage" / "test-machine.json")
        self.assertEqual(json.loads(published.read_bytes()), receipt)
        for private in ("findings", "notes.txt", "refs/heads", "policy", "private-marker", str(self.repo)):
            self.assertNotIn(private, json.dumps(receipt))

    def test_batched_history_preserves_findings_and_reuses_clean_work_after_ref_changes(self):
        self.git(self.repo, "checkout", "--orphan", "clean")
        self.commit("clean.txt", "a small clean object")
        self.git(self.repo, "branch", "-D", "main")

        def audit(**options):
            return audit_checkout(self.repo, settings_home=self.home, cache=True,
                                  history_workers=2, **options)["history"]

        full = audit()
        self.assertEqual(full["reused_batches"], 0)
        self.git(self.repo, "branch", "-m", "renamed")
        self.assertEqual(audit()["reused_batches"], 1)
        self.assertEqual(audit(fresh=True)["reused_batches"], 0)

        self.commit("one.txt", "a private-marker")
        self.commit("two.txt", "a private-marker")
        report = audit(fresh=True)
        locations = {item["where"] for item in report["findings"] if item["check"] == "never-publish"}
        self.assertEqual(locations, {"one.txt", "two.txt"})

    def test_runners_finish_other_repositories_while_a_slow_one_is_active(self):
        release_slow = threading.Event()
        slow_active = threading.Event()
        following_active = threading.Event()
        self.addCleanup(release_slow.set)

        def runner(path, *, values, step, **kwargs):
            step("scanning history")
            if path.name == "slow":
                slow_active.set()
                release_slow.wait(10)
            if path.name == "following":
                following_active.set()
            values["history"] = [path.name]
            return {"check_status": "passed"}

        jobs = AuditJobs(lambda repo_id: [Path(repo_id)], runner=runner)
        for invalid in (0, 9, True, "2"):
            with self.assertRaisesRegex(ValueError, "simultaneous runners"):
                jobs.start({"repo_ids": ["slow"], "runners": invalid})
        jobs.start({"repo_ids": ["slow", "fast", "following"], "runners": 2})
        self.assertTrue(slow_active.wait(5))
        self.assertTrue(following_active.wait(5))
        running = jobs.status()["audit"]
        self.assertEqual((running["state"], running["runners"]), ("running", 2))
        self.assertIn("slow", {worker["repo_id"] for worker in running["active"]})
        self.assertTrue(any(entry["repo_id"] == "fast" for entry in running["results"]))
        release_slow.set()
        for _ in range(200):
            finished = jobs.status()["audit"]
            if finished["state"] != "running":
                break
            threading.Event().wait(0.01)
        self.assertEqual((finished["state"], finished["done"], finished["active"]), ("finished", 3, []))
        for entry in finished["results"]:
            result = jobs.reveal({"index": entry["index"], "material": "history", "finding_id": "finding-000001"})
            self.assertEqual(result["value"], entry["repo_id"])

    def test_jobs_audit_known_ids_only_one_at_a_time(self):
        gate = threading.Event()

        def runner(path, **kwargs):
            gate.wait(5)
            return audit_checkout(path, settings_home=self.home, history=kwargs["history"])
        jobs = AuditJobs(lambda repo_id: [self.repo] if repo_id == "known" else [], runner=runner)
        for bad in ({"repo_ids": []}, {"repo_ids": ["a", "a"]}, {"repo_ids": ["a"], "path": "/x"},
                    {"repo_ids": ["a"], "engines": ["rm"]}, {"repo_ids": ["a"], "history": "yes"}):
            with self.assertRaises(ValueError, msg=bad):
                jobs.start(bad)
        jobs.start({"repo_ids": ["known", "stranger"], "history": True})
        with self.assertRaisesRegex(ValueError, "already running"):
            jobs.start({"repo_ids": ["known"]})
        gate.set()
        for _ in range(200):
            audit = jobs.status()["audit"]
            if audit["state"] != "running":
                break
            threading.Event().wait(0.05)
        self.assertEqual((audit["state"], audit["done"], audit["total"]), ("finished", 2, 2))
        by_id = {entry["repo_id"]: entry["security"] for entry in audit["results"]}
        self.assertNotEqual(by_id["known"]["check_status"], "passed")
        self.assertEqual(by_id["stranger"]["check_status"], "incomplete", "an unknown id is never resolved")

    def test_a_finding_is_revealed_only_on_request_and_never_in_the_status(self):
        jobs = AuditJobs(lambda repo_id: [self.repo],
                         runner=lambda path, **kwargs: audit_checkout(path, settings_home=self.home, **{
                             key: kwargs[key] for key in ("history", "values")}))
        jobs.start({"repo_ids": ["known"], "history": True})
        for _ in range(200):
            audit = jobs.status()["audit"]
            if audit["state"] != "running":
                break
            threading.Event().wait(0.05)
        self.assertNotIn("private-marker", json.dumps(jobs.status()), "the polled status stays masked")
        full = jobs.status(full=True)["audit"]
        self.assertNotIn("private-marker", json.dumps(full))
        self.assertNotIn("values", full)
        entry = audit["results"][0]
        finding = next(f for f in entry["security"]["history"]["findings"] if f["classification"] != "quiet")
        request = {"index": entry["index"], "material": "history", "finding_id": finding["finding_id"]}
        shown = jobs.reveal({**request, "audit_started_at": audit["started_at"]})
        self.assertIn("private-marker", shown["value"])
        for action in (jobs.reveal, jobs.accept):
            with self.assertRaisesRegex(ValueError, "earlier audit"):
                action({**request, "audit_started_at": "2020-01-01T00:00:00Z"})
        for bad in ({"index": 9, "material": "history", "finding_id": finding["finding_id"]},
                    {"index": 0, "material": "path", "finding_id": finding["finding_id"]},
                    {"index": 0, "material": "history", "finding_id": "finding-999999"},
                    {"index": 0, "material": "history", "finding_id": "x", "extra": 1}):
            with self.assertRaises(ValueError, msg=bad):
                jobs.reveal(bad)

    def test_accept_reviews_a_binary_file_and_the_next_audit_leaves_it(self):
        # The Security page's Accept (2026-11-17): the same review `gitso review` saves.
        (self.repo / "font.woff2").write_bytes(b"wOF2\x00\x01\x00\x00binary font bytes\x00" * 20)
        self.git(self.repo, "add", "font.woff2")
        self.git(self.repo, "commit", "-q", "-m", "font")

        def run_audit():
            jobs = AuditJobs(lambda repo_id: [self.repo],
                             runner=lambda path, **kwargs: audit_checkout(path, settings_home=self.home, **{
                                 key: kwargs[key] for key in ("history", "values")}))
            jobs.start({"repo_ids": ["known"], "history": False})
            for _ in range(400):
                audit = jobs.status()["audit"]
                if audit["state"] != "running":
                    break
                threading.Event().wait(0.05)
            return jobs, audit

        jobs, audit = run_audit()
        entry = audit["results"][0]
        binary = [f for f in entry["security"]["working_tree"]["findings"]
                  if f["check"] == "binary content" and not f.get("review_id")]
        self.assertTrue(binary, "the binary file is a finding to review")
        done = jobs.accept({"index": entry["index"], "material": "working_tree", "finding_id": binary[0]["finding_id"]})
        self.assertEqual(done["status"], "accepted", done)
        _, again = run_audit()
        open_findings = [f for f in again["results"][0]["security"]["working_tree"]["findings"]
                         if f["check"] == "binary content" and not f.get("review_id")]
        self.assertEqual(open_findings, [], "the next audit leaves the accepted file alone")

    def test_the_audit_runs_in_its_own_process_and_reports_back(self):
        # A long audit took the app's process and the page stopped answering (2026-11-17).
        from Special._security._audit import audit_in_process
        values: dict = {}
        steps = []
        result = audit_in_process(self.repo, history=True, settings_home=self.home, values=values,
                                  step=steps.append, worker_budget=lambda: 8)
        self.assertEqual(result["check_status"], "blocked", "the deleted value is still found in history")
        self.assertTrue(steps and steps[0].startswith("working files"), steps)
        self.assertTrue(any(step.startswith("every commit:") for step in steps), "the status line hears each phase")
        self.assertNotIn("private-marker", json.dumps(result), "what comes back to the page stays masked")
        self.assertTrue(any("private-marker" in v for v in values.get("history", [])), "values come back for Show")

    def test_stop_ends_an_audit_process_at_once(self):
        from Special._security._audit import audit_in_process
        result = audit_in_process(self.repo, history=True, settings_home=self.home, should_stop=lambda: True)
        self.assertEqual(result["check_status"], "incomplete")
        self.assertIn("Stopped", result["gaps"][0]["reason"])

    def test_a_running_audit_can_be_stopped(self):
        gate = threading.Event()
        jobs = AuditJobs(lambda repo_id: [self.repo],
                         runner=lambda path, **kwargs: (gate.wait(5), {"check_status": "passed"})[1])
        jobs.start({"repo_ids": ["a", "b", "c"]})
        jobs.stop()
        gate.set()
        for _ in range(200):
            audit = jobs.status()["audit"]
            if audit["state"] != "running":
                break
            threading.Event().wait(0.05)
        self.assertEqual(audit["state"], "stopped")
        self.assertLess(audit["done"], 3)

    def test_engines_are_only_looked_for(self):
        with patch("Special._security._audit.shutil.which", return_value=None), \
                patch("Special._security._audit.find_program", return_value=None), \
                patch("Special._security._audit.subprocess", create=True) as never_run:
            status = engines_status()
        self.assertEqual([item["engine"] for item in status], ["gitleaks", "betterleaks", "trufflehog"])
        self.assertTrue(all(not item["installed"] for item in status))
        self.assertTrue(all(item["install"] is None for item in status), "no package tool, no suggestion")
        self.assertFalse(never_run.mock_calls, "looking must never run anything")

    def test_a_missing_engine_comes_with_this_systems_install_command(self):
        with patch("Special._security._audit.sys.platform", "win32"), \
                patch("Special._security._audit.shutil.which", side_effect=lambda name: name if name == "winget" else None),                 patch("Special._security._audit.find_program", return_value=None):
            status = {item["engine"]: item for item in engines_status()}
        self.assertEqual(status["gitleaks"]["install"], "winget install --id Gitleaks.Gitleaks --exact")
        self.assertIsNone(status["trufflehog"]["install"], "no winget package: the home page instead")
        self.assertTrue(status["trufflehog"]["home_page"])


if __name__ == "__main__":
    unittest.main()
