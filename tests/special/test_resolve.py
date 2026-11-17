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
        # An entry is a folder: everything inside it is left out too (an agent's run folders).
        config["not_counted"] = [str(library / "build")]
        observer = IncrementalObserver(config)
        observer.inventory()
        self.assertNotIn(nested.resolve(), observer.paths)
        self.assertIn(self.repo.resolve(), observer.paths)

    def test_the_settings_list_and_a_folder_not_to_count_use_this_profile(self):
        import json
        from Special._sync import enrollment
        library = self.repo.parent
        home = library.parent / (library.name + "-profile")
        home.mkdir()
        self.addCleanup(lambda: __import__("shutil").rmtree(home, ignore_errors=True))
        (home / "settings.json").write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
        enrollment.add_libraries([library], home=home)
        self.assertEqual(repo_action("not-counted-list", {}, self.checkouts, home=home), {"not_counted": []})
        (library / "runs").mkdir()
        answer = repo_action("not-counted-folder", {"path": str(library / "runs")}, self.checkouts, home=home)
        self.assertEqual(answer["not_counted"], [str((library / "runs").resolve())])
        with self.assertRaises(ValueError, msg="outside every library"):
            repo_action("not-counted-folder", {"path": str(home)}, self.checkouts, home=home)
        again = repo_action("count-again", {"path": answer["not_counted"][0]}, self.checkouts, home=home)
        self.assertEqual(again["not_counted"], [])

    def test_safe_to_delete_needs_every_commit_remote_and_every_file_elsewhere(self):
        library = self.repo.parent
        remote = library / "remote.git"
        git(library, "init", "-q", "--bare", str(remote))
        git(self.repo, "remote", "add", "origin", str(remote))
        git(self.repo, "push", "-q", "origin", "HEAD")
        second = library / "second"
        git(library, "clone", "-q", str(remote), str(second))
        both = lambda repo_id: [self.repo, second]
        listed = repo_action("copies", {"repo_id": "r1"}, both)["copies"]
        self.assertEqual([copy["checkout"] for copy in listed], [0, 1])
        clean = repo_action("retire-check", {"repo_id": "r1", "checkout": 1}, both)
        self.assertTrue(clean["safe"], clean["verdict"])
        (second / "note.txt").write_text("only here\n")
        only = repo_action("retire-check", {"repo_id": "r1", "checkout": 1}, both)
        self.assertFalse(only["safe"])
        self.assertEqual(only["files"][0]["elsewhere"], "only here")
        (self.repo / "note.txt").write_text("only here\n")
        same = repo_action("retire-check", {"repo_id": "r1", "checkout": 1}, both)
        self.assertTrue(same["safe"], "the same file is in the other copy")
        git(second, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-qm", "local", "--allow-empty")
        ahead = repo_action("retire-check", {"repo_id": "r1", "checkout": 1}, both)
        self.assertFalse(ahead["safe"], "a commit on no remote")
        self.assertIn("Not safe", ahead["verdict"])

    def test_a_failed_read_is_an_error_never_an_empty_answer(self):
        import shutil
        shutil.rmtree(self.repo / ".git", ignore_errors=True)
        with self.assertRaises(ValueError):
            repo_action("changes", {"repo_id": "r1"}, self.checkouts)


if __name__ == "__main__":
    unittest.main()
