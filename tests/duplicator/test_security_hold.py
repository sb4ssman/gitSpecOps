"""Org copy's optional security check (2026-11-17): chosen by the person, off for an exact copy.

Pins: a history holding a never-publish value is held, in a working clone and in a bare mirror,
with the way to a clean copy in its words and no value in them; a clean history is not; an
upload with the check on creates nothing for a held repository; only branches, tags and notes
are exported.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Special._org_duplicator import operations  # noqa: E402


class SecurityHoldTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="hold-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.repo, self.home = self.root / "checkout", self.root / "profile"
        self.home.mkdir()
        environment = patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                                              "GITSPECOPS_HOME": str(self.home), "GIT_OPTIONAL_LOCKS": "0"})
        environment.start()
        self.addCleanup(environment.stop)
        (self.home / "settings.json").write_text(json.dumps(
            {"schema_version": 2, "defaults": {"security": {"never_publish": ["private-marker"]}}}), encoding="utf-8")
        self.git(self.root, "init", "-q", "-b", "main", str(self.repo))
        for key, value in (("user.name", "orbit-user"), ("user.email", "123+orbit-user@users.noreply.github.com"),
                           ("commit.gpgsign", "false"), ("core.autocrlf", "false")):
            self.git(self.repo, "config", key, value)

    def git(self, cwd, *arguments):
        return subprocess.run(["git", *arguments], cwd=cwd, check=True, capture_output=True, text=True).stdout

    def commit(self, text):
        (self.repo / "notes.txt").write_text(text + "\n", encoding="utf-8")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-qm", "notes")

    def test_a_clean_history_is_not_held(self):
        self.commit("nothing to see")
        self.assertIsNone(operations.security_hold(str(self.repo), self.home))

    def test_a_value_left_in_history_holds_the_repository_and_its_mirror(self):
        self.commit("the private-marker slipped in")
        self.commit("cleaned up")
        reason = operations.security_hold(str(self.repo), self.home)
        self.assertIn("high-severity", reason)
        self.assertIn("gitso history clean", reason, "the way to a clean copy is in the words")
        self.assertNotIn("private-marker", reason, "never the value itself")
        mirror = self.root / "mirror.git"
        self.git(self.root, "clone", "-q", "--mirror", str(self.repo), str(mirror))
        self.assertIsNotNone(operations.security_hold(str(mirror), self.home), "a bare mirror is read too")

    def test_an_upload_with_the_check_creates_nothing_for_a_held_repository(self):
        self.commit("the private-marker slipped in")
        logs = [str(self.root / name) for name in ("completed", "success", "error")]
        import contextlib
        import io
        with patch.object(operations, "ensure_repo") as create, patch.object(operations, "run_checked") as run, \
                contextlib.redirect_stdout(io.StringIO()):
            result = operations.process_upload_repo({"name": "checkout", "path": str(self.repo)}, "dest",
                                                    *logs, security=True)
        self.assertEqual(result["status"], "held")
        create.assert_not_called()
        run.assert_not_called()
        self.assertFalse(Path(logs[0]).exists(), "a held repository is not marked complete")

    def test_only_branches_tags_and_notes_are_exported(self):
        self.commit("one")
        head = self.git(self.repo, "rev-parse", "HEAD").strip()
        self.git(self.repo, "tag", "v1")
        for ref in ("refs/pull/1/head", "refs/remotes/origin/main", "refs/notes/commits", "refs/original/x"):
            self.git(self.repo, "update-ref", ref, head)
        self.assertEqual(sorted(operations.exported_refs(str(self.repo))),
                         ["refs/heads/main", "refs/notes/commits", "refs/tags/v1"])


if __name__ == "__main__":
    unittest.main()
