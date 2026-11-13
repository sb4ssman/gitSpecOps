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
                patch("Special._security._audit.subprocess", create=True) as never_run:
            status = engines_status()
        self.assertEqual([item["engine"] for item in status], ["gitleaks", "betterleaks", "trufflehog"])
        self.assertTrue(all(not item["installed"] for item in status))
        self.assertTrue(all(item["install"] is None for item in status), "no package tool, no suggestion")
        self.assertFalse(never_run.mock_calls, "looking must never run anything")

    def test_a_missing_engine_comes_with_this_systems_install_command(self):
        with patch("Special._security._audit.sys.platform", "win32"), \
                patch("Special._security._audit.shutil.which", side_effect=lambda name: name if name == "winget" else None):
            status = {item["engine"]: item for item in engines_status()}
        self.assertEqual(status["gitleaks"]["install"], "winget install --id Gitleaks.Gitleaks --exact")
        self.assertIsNone(status["trufflehog"]["install"], "no winget package: the home page instead")
        self.assertTrue(status["trufflehog"]["home_page"])


if __name__ == "__main__":
    unittest.main()
