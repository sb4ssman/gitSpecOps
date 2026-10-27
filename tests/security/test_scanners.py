"""Offline integration of the active scanners. All writes are to invented scratch repos."""
from __future__ import annotations

import io
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT, setup

setup()
from Special.security._checks import inspect
from Special.security._contents import MEMBER_LIMIT_BYTES, image_metadata, open_archive
from Special.security._findings import Report, write_report
from Special.security._material import scan
from Special.security._me import Policy, load_policy


class Scanners(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="security-scanner-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.env = patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull,
                                          "GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0",
                                          "GITSPECOPS_HOME": str(self.root / "config")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.git("init", "-q", "-b", "main", str(self.repo), cwd=self.root)
        self.git("config", "user.name", "orbit-user@MACHINE-A")
        self.git("config", "user.email", "123+orbit-user@users.noreply.github.com")
        self.git("config", "core.autocrlf", "false")
        self.policy = Policy(identities={"never-publish": ["private-marker", "owner@example.test"]},
                             logins=["orbit-user"])
        self.write(".gitignore", "private/\n")
        self.write("readme.txt", "ordinary text\n")
        self.save("initial")

    def git(self, *args, cwd=None):
        done = subprocess.run(["git", "-C", str(cwd or self.repo), *args],
                              capture_output=True, text=True, encoding="utf-8", check=True)
        return done.stdout.strip()

    def write(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)

    def save(self, message):
        self.git("add", "-A")
        self.git("-c", "commit.gpgsign=false", "commit", "--allow-empty", "-qm", message)

    def test_same_policy_in_tree_and_history(self):
        self.write("private-marker.txt", "owner@example.test orbit-user orbit-user@MACHINE-A\n")
        self.save("add fixture")
        for material in ("tree", "history"):
            result = scan(self.repo, self.policy, material=material)
            self.assertFalse(result.gaps, result.gaps)
            self.assertTrue(any(item.value == "owner@example.test" for item in result.findings))
            self.assertTrue(any(item.value == "private-marker" and "[path]" in item.where for item in result.findings))
            self.assertFalse(any(item.value.startswith("orbit-user") for item in result.findings))

    def test_duplicate_blob_names_deleted_file_merge_and_detached_head(self):
        self.write("same.txt", "identical")
        self.write("private-marker.txt", "identical")
        self.save("two names")
        self.git("checkout", "-qb", "side")
        self.write("side.txt", "side")
        self.save("side")
        self.git("checkout", "-q", "main")
        self.write("main.txt", "main")
        self.save("main")
        self.git("merge", "--no-ff", "--no-commit", "side")
        self.write("merge.txt", "owner@example.test")
        self.save("merge")
        (self.repo / "private-marker.txt").unlink()
        self.save("removed path")
        self.git("checkout", "--detach", "-q")
        self.write("detached.txt", "private-marker")
        self.save("detached")
        result = scan(self.repo, self.policy, material="history")
        self.assertFalse(result.gaps, result.gaps)
        self.assertIn("HEAD", result.refs)
        self.assertTrue(any(item.where == "private-marker.txt [path]" for item in result.findings))
        self.assertTrue(any(item.where == "merge.txt" for item in result.findings))
        self.assertTrue(any(item.where == "detached.txt" for item in result.findings))

    def test_raw_author_and_tag_identity_not_mailmap(self):
        self.git("config", "user.email", "owner@example.test")
        self.save("private-marker in message")
        self.git("-c", "tag.gpgsign=false", "tag", "-a", "-m", "private-marker", "release")
        self.write(".mailmap", "Safe <safe@example.test> <owner@example.test>\n")
        result = scan(self.repo, self.policy, material="history")
        self.assertTrue(any(item.where == "author" and item.value == "owner@example.test" for item in result.findings))
        self.assertTrue(any("tagger" in item.where for item in result.findings))
        self.assertTrue(any(item.where == "commit message" for item in result.findings))
        self.assertEqual(result.refs["refs/tags/release"], self.git("rev-parse", "release"))

    def test_non_commit_refs_are_inspected(self):
        self.git("tag", "tree-only", "HEAD^{tree}")
        blob = subprocess.run(["git", "-C", str(self.repo), "hash-object", "-w", "--stdin"],
                              input=b"private-marker", capture_output=True, check=True).stdout.decode().strip()
        self.git("update-ref", "refs/private/blob", blob)
        result = scan(self.repo, self.policy, material="history")
        self.assertFalse(result.gaps, result.gaps)
        self.assertTrue(any(item.object_id == blob for item in result.findings))

    def test_working_files_untracked_missing_and_ignored(self):
        self.write("new.txt", "private-marker")
        self.write("private/ignored.txt", "private-marker")
        (self.repo / "readme.txt").unlink()
        result = scan(self.repo, self.policy)
        self.assertEqual(result.exit_code, 2)
        self.assertTrue(any(item.where == "new.txt" for item in result.findings))
        self.assertFalse(any("ignored.txt" in item.where for item in result.findings))
        self.assertTrue(any(item["where"] == "readme.txt" for item in result.gaps))

    def test_safe_precedence_short_watch_values_and_alias_is_not_email(self):
        policy = Policy(identities={"never-publish": ["abc", "orbit-user@example.test", "MACHINE-A", "private-marker"]},
                        safe=["private-marker"], logins=["orbit-user"])
        findings = inspect("abc orbit-user@MACHINE-A orbit-user@example.test private-marker", "fixture", policy)
        self.assertEqual({item.value for item in findings}, {"abc", "orbit-user@example.test"})

    def test_many_candidates_do_not_rescan_entire_file_for_each_safe_value(self):
        text = "person@public-domain.org\n" * 5000
        started = time.monotonic()
        findings = inspect(text, "many-candidates.txt", self.policy)
        self.assertEqual(len(findings), 5000)
        self.assertLess(time.monotonic() - started, 8, "candidate checking must remain usable on large files")

    def test_offline_credentials_and_safe_value_on_same_line(self):
        # Assemble an invented assignment so the source itself is not a credential finding.
        text = 'token="' + 'unexpected-value-123" https://user:unexpected-password@host.invalid/\n'
        findings = inspect(text, "fixture", Policy(safe=["host.invalid"]))
        self.assertEqual({item.check for item in findings}, {"assigned credential", "URL credential"})
        policy = Policy(safe=["unexpected-value-123", "unexpected-password"])
        self.assertFalse(inspect(text, "fixture", policy))

    def test_archive_directory_names_and_member_budget(self):
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, "w") as archive:
            archive.writestr("private-marker/", b"")
            archive.writestr("data.txt", b"data")
        opened = open_archive("bundle.zip", memory.getvalue())
        self.assertIn(("private-marker/", b""), opened.members)
        with patch("Special.security._contents.ENTRY_LIMIT", 1):
            self.assertTrue(any("count limit" in reason for _, reason in open_archive("bundle.zip", memory.getvalue()).skipped))

    def test_policy_sources_and_missing_or_unreadable_lists(self):
        with patch("Special.security._me.config_home", return_value=self.root / "config"):
            policy = load_policy(self.repo)
            self.assertEqual(policy.sources["safe-list"], "not-configured")
            self.assertIn("orbit-user", policy.logins)
            self.assertFalse(policy.gaps)
            missing = load_policy(self.repo, safe_file=self.root / "absent")
            self.assertTrue(missing.gaps)
            invalid = self.root / "invalid.txt"
            invalid.write_bytes(b"\xff")
            self.assertTrue(load_policy(self.repo, never_file=invalid).gaps)
            listed = self.root / "safe.txt"
            listed.write_text("# comment\nprivate-marker\n", encoding="utf-8")
            self.assertIn("private-marker", load_policy(self.repo, safe_file=listed).safe)

    def test_masking_includes_sensitive_filenames_and_private_report_is_explicit(self):
        self.write("private-marker.txt", "owner@example.test")
        result = scan(self.repo, self.policy)
        self.assertNotIn("private-marker", result.summary())
        self.assertNotIn("owner@example.test", json.dumps(result.record()))
        destination = self.repo / "private" / "scan.json"
        write_report(destination, result)
        self.assertIn("owner@example.test", destination.read_text())
        with self.assertRaises(FileExistsError):
            write_report(destination, result)
        for bad in (self.repo / "readme.txt", self.repo / "public.json", self.repo / "private/../public.json"):
            with self.assertRaises(ValueError):
                write_report(bad, result)

    def test_private_repository_path_is_masked_even_without_findings(self):
        result = Report("/private-marker/repo", "tree", private_values=("private-marker",))
        self.assertNotIn("private-marker", json.dumps(result.record()))
        self.assertNotIn("private_values", result.record(redacted=False))

    def test_working_tree_links_are_never_followed(self):
        outside = self.root / "outside.txt"
        outside.write_text("private-marker", encoding="utf-8")
        try:
            (self.repo / "link.txt").symlink_to(outside)
        except OSError:
            self.skipTest("OS does not permit creating a test symlink")
        result = scan(self.repo, self.policy)
        self.assertFalse(any(item.where == "link.txt" for item in result.findings))
        with self.assertRaises(ValueError):
            write_report(self.repo / "link.txt", result)

    def test_scan_does_not_change_repository_state(self):
        before = (self.git("rev-parse", "HEAD"), (self.repo / ".git/index").read_bytes(),
                  self.git("status", "--porcelain=v1", "-uall"))
        scan(self.repo, self.policy)
        scan(self.repo, self.policy, material="history")
        after = (self.git("rev-parse", "HEAD"), (self.repo / ".git/index").read_bytes(),
                 self.git("status", "--porcelain=v1", "-uall"))
        self.assertEqual(before, after)

    def test_ref_changes_report_incomplete(self):
        from Special.security._material import _ref_ids
        original = _ref_ids(self.repo)
        with patch("Special.security._material._ref_ids", side_effect=[original, {**original, "new-ref": "new-tip"}]):
            result = scan(self.repo, self.policy, material="history")
        self.assertEqual(result.exit_code, 2)
        self.assertTrue(any(item["where"] == "refs" for item in result.gaps))

    def test_large_blob_is_rejected_before_loading(self):
        self.write("large.txt", "x" * 101)
        self.save("large fixture")
        with patch("Special.security._material.MAX_FILE_BYTES", 100):
            result = scan(self.repo, self.policy, material="history")
        self.assertTrue(any(item["where"] == "large.txt" and "limit" in item["reason"] for item in result.gaps))

    def test_partial_clone_refuses_automatic_downloads(self):
        self.git("config", "remote.example.promisor", "true")
        result = scan(self.repo, self.policy, material="history")
        self.assertTrue(any("partial clone" in item["reason"] for item in result.gaps))

    def test_archive_and_compressed_metadata_and_corruption(self):
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, "w") as archive:
            archive.writestr("private-marker.txt", "owner@example.test")
        self.write("bundle.zip", memory.getvalue())
        body = b"author\0\0" + zlib.compress(b"owner@example.test")
        def chunk(kind, payload):
            return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"zTXt", body) + chunk(b"IEND", b"")
        self.write("picture.png", png)
        self.write("broken.zip", b"not a zip")
        result = scan(self.repo, self.policy)
        self.assertTrue(any(item.where == "bundle.zip!private-marker.txt" for item in result.findings))
        self.assertTrue(any("[metadata]" in item.where for item in result.findings))
        self.assertTrue(any(item["where"] == "broken.zip" for item in result.gaps))
        oversized = b"\x89PNG\r\n\x1a\n" + chunk(b"zTXt", b"author\0\0" + zlib.compress(b"x" * (MEMBER_LIMIT_BYTES + 1)))
        self.assertTrue(image_metadata(oversized).skipped)

    def test_archive_nesting_has_explicit_gap(self):
        def zipped(name, data):
            memory = io.BytesIO()
            with zipfile.ZipFile(memory, "w") as archive:
                archive.writestr(name, data)
            return memory.getvalue()
        opened = open_archive("a.zip", zipped("b.zip", zipped("c.zip", zipped("data.txt", b"private-marker"))))
        self.assertTrue(any("nesting" in reason for _, reason in opened.skipped))

    def test_image_gps_and_renamed_archive(self):
        # Minimal TIFF: main IFD points at a GPS IFD containing latitude-reference tag 1.
        tiff = (b"II*\0" + struct.pack("<I", 8) + struct.pack("<H", 1) +
                struct.pack("<HHII", 0x8825, 4, 1, 26) + struct.pack("<I", 0) +
                struct.pack("<H", 1) + struct.pack("<HHI4s", 1, 2, 2, b"N\0\0\0") + struct.pack("<I", 0))
        self.write("location.tiff", tiff)
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, "w") as archive:
            archive.writestr("data.txt", "private-marker")
        self.write("renamed.dat", memory.getvalue())
        result = scan(self.repo, self.policy)
        self.assertTrue(any(item.check == "image GPS position" for item in result.findings))
        self.assertTrue(any(item.where == "renamed.dat!data.txt" for item in result.findings))

    def test_read_failure_never_issues_clean_result(self):
        from Basic._run import CommandFailed
        with patch("Special.security._material.file_versions", side_effect=CommandFailed("fixture failure")):
            result = scan(self.repo, self.policy, material="history")
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(result.record()["coverage"], "incomplete")

    def test_cli_from_another_directory_uses_explicit_policy_and_masked_stdout(self):
        self.write("new.txt", "private-marker")
        watch = self.root / "watch.txt"
        watch.write_text("private-marker\n", encoding="utf-8")
        safe = self.root / "safe.txt"
        safe.write_text("", encoding="utf-8")
        done = subprocess.run([sys.executable, "-B", str(ROOT / "Special/security/scan_tree.py"),
                               str(self.repo), "--never-publish", str(watch), "--safe-file", str(safe), "--json"],
                              cwd=self.root, capture_output=True, text=True)
        self.assertEqual(done.returncode, 1, done.stderr + done.stdout)
        self.assertNotIn("private-marker", done.stdout)
        self.assertEqual(json.loads(done.stdout)["coverage"], "complete-for-selected-checks")


if __name__ == "__main__":
    unittest.main()
