"""Private security storage in disposable Git work trees and external account-like folders.

Verify exact destinations, permissions where supported, no overwrite/fallback, masked stdout
and discarded partial files. No live profiles or security reports are read or written.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup
setup()

from Special.security import _cli, _private_files as storage
from Special.security._findings import Finding, Report, write_report


class PrivateReportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="private-reports-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.repo, self.home = self.root / "repo", self.root / "profile"
        self.repo.mkdir()
        self.home.mkdir()
        env = patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                                     "GITSPECOPS_HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        self.git("init", "-q")
        (self.repo / ".gitignore").write_text("private/\n", encoding="utf-8")
        self.git("add", "--", ".gitignore")
        self.report = Report(str(self.repo), "tree", findings=[Finding("never-publish", "leak", "private-marker", "data.txt", line=1)])

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True, timeout=30).stdout.strip()

    def test_external_report_includes_full_details_and_its_actual_artifact(self):
        path = self.home / "reports" / "scan.json"
        self.assertEqual(write_report(path, self.report), path)
        saved = json.loads(path.read_text())
        self.assertEqual(saved["findings"][0]["value"], "private-marker")
        self.assertEqual(saved["artifacts"], self.report.record()["artifacts"])
        self.assertEqual(saved["artifacts"][0]["path"], str(path))
        self.assertNotIn("private-marker", json.dumps(self.report.record()))

    def test_new_posix_file_and_parent_permissions_are_private(self):
        if os.name == "nt":
            self.skipTest("Windows storage inherits directory ACLs, not POSIX mode semantics")
        path = self.home / "one" / "two" / "scan.json"
        write_report(path, self.report)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        for parent in (path.parent, path.parent.parent):
            self.assertEqual(stat.S_IMODE(parent.stat().st_mode), 0o700)

    def test_existing_report_is_never_replaced(self):
        path = self.home / "scan.json"
        path.write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            write_report(path, self.report)
        self.assertEqual(path.read_text(), "keep")
        self.assertEqual(self.report.artifacts, [])

    def test_inside_git_requires_positive_ignore_and_untracked_target(self):
        for path in (self.repo / "public.json", self.repo / ".gitignore"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                write_report(path, self.report)
        path = self.repo / "private" / "scan.json"
        write_report(path, self.report)
        self.assertEqual(self.git("check-ignore", "--", "private/scan.json"), "private/scan.json")
        self.assertEqual(self.git("ls-files", "--", "private/scan.json"), "")

    def test_ignored_but_tracked_file_is_refused(self):
        path = self.repo / "private" / "tracked.json"
        path.parent.mkdir()
        path.write_text("keep", encoding="utf-8")
        self.git("add", "-f", "--", "private/tracked.json")
        with self.assertRaises(ValueError):
            write_report(path, self.report)
        self.assertEqual(path.read_text(), "keep")

    def test_bare_repository_is_not_external_private_storage(self):
        bare = self.root / "bare.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, capture_output=True)
        with self.assertRaises(ValueError):
            write_report(bare / "report.json", self.report)
        self.assertFalse((bare / "report.json").exists())

    def test_parent_traversal_and_linked_destinations_are_refused(self):
        with self.assertRaises(ValueError):
            write_report(self.home / "one/../scan.json", self.report)
        link = self.root / "linked-profile"
        try:
            link.symlink_to(self.home, target_is_directory=True)
        except OSError:
            self.skipTest("host does not permit directory symlink creation")
        with self.assertRaises(ValueError):
            write_report(link / "scan.json", self.report)
        self.assertFalse((self.home / "scan.json").exists())

    def test_partial_write_is_removed_and_never_advertised(self):
        path = self.home / "scan.json"
        with patch.object(storage.json, "dump", side_effect=OSError("private diagnostic")), self.assertRaises(OSError):
            write_report(path, self.report)
        self.assertFalse(path.exists())
        self.assertEqual(self.report.artifacts, [])

    def test_required_directory_failure_does_not_fall_back(self):
        blocked = self.home / "occupied"
        blocked.write_text("keep", encoding="utf-8")
        with self.assertRaises(OSError):
            write_report(blocked / "scan.json", self.report)
        self.assertEqual(blocked.read_text(), "keep")
        self.assertFalse((self.repo / "private").exists())
        self.assertEqual(self.report.artifacts, [])

    def test_cli_external_full_report_keeps_stdout_masked_and_lists_artifact(self):
        (self.repo / "data.txt").write_text("private-marker", encoding="utf-8")
        (self.home / "settings.json").write_text(json.dumps({"schema_version": 2,
             "defaults": {"security": {"never_publish": ["private-marker"]}}}), encoding="utf-8")
        path = self.home / "reports" / "scan.json"
        output = io.StringIO()
        with redirect_stdout(output):
            code = _cli.main("tree", [str(self.repo), "--json", "--out", str(path)])
        self.assertEqual(code, 1)
        record = json.loads(output.getvalue())
        self.assertEqual(len(record["artifacts"]), 1)
        self.assertNotIn("private-marker", output.getvalue())
        self.assertIn("private-marker", path.read_text())
        self.assertEqual(self.git("ls-files", "--", "data.txt"), "")

    def test_private_json_reads_reject_duplicates_nonfinite_and_oversize(self):
        path = self.home / "state.json"
        for raw in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":"' + "x" * 50 + '"}'):
            path.write_text(raw, encoding="utf-8")
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                storage.read_private_json(path, limit=30)


if __name__ == "__main__":
    unittest.main()
