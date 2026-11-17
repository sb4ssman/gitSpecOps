"""Resolving from the page (2026-11-17): the actions act only on this machine's own copy.

Pins: changes lists each file and shows the diff; an unknown action or a repository without a
copy here is refused; a folder on the not-counted list is left out of the next read.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Special._sync.inventory import IncrementalObserver  # noqa: E402
from Special._sync.resolve import repo_action  # noqa: E402


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class ResolveTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.repo = Path(folder.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "t@example.invalid")
        git(self.repo, "config", "user.name", "t")
        git(self.repo, "config", "core.autocrlf", "false")
        (self.repo / "a.txt").write_text("one\n")
        git(self.repo, "add", "a.txt")
        git(self.repo, "commit", "-qm", "one")
        self.checkouts = lambda repo_id: [self.repo] if repo_id == "r1" else []

    def test_changes_lists_each_file_and_the_diff(self):
        (self.repo / "a.txt").write_text("two\n")
        (self.repo / "new.txt").write_text("new\n")
        answer = repo_action("changes", {"repo_id": "r1"}, self.checkouts)
        self.assertEqual(sorted(f["path"] for f in answer["files"]), ["a.txt", "new.txt"])
        self.assertIn("+two", answer["diff"])

    def test_a_repository_without_a_copy_here_and_unknown_actions_are_refused(self):
        with self.assertRaises(ValueError):
            repo_action("changes", {"repo_id": "elsewhere"}, self.checkouts)
        with self.assertRaises(ValueError):
            repo_action("rm-rf", {"repo_id": "r1"}, self.checkouts)

    def test_a_not_counted_folder_is_left_out_of_the_next_read(self):
        library = self.repo.parent
        nested = library / "build" / "_deps" / "lib-src"
        nested.mkdir(parents=True)
        git(nested, "init", "-q")
        (nested / "x.txt").write_text("x\n")
        git(nested, "add", "x.txt")
        git(nested, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-qm", "x")
        config = {"roots": [str(library)], "fleet_secret": "55" * 32, "not_counted": [str(nested)]}
        observer = IncrementalObserver(config)
        observer.inventory()
        self.assertIn(self.repo.resolve(), observer.paths)
        self.assertNotIn(nested.resolve(), observer.paths, "the person said not to count it")
        self.assertEqual(observer.not_counted, 1)


if __name__ == "__main__":
    unittest.main()
