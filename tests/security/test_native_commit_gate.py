"""Exercise Git's literal commit command with both local hook policies."""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup

setup()

from Special._security._native_gate_cli import _runtime, main  # noqa: E402


class NativeCommitGateTests(unittest.TestCase):
    def test_runtime_archive_is_independent_of_the_clock(self):
        with patch("zipfile.time.localtime", return_value=(2026, 1, 1, 0, 0, 0, 0, 1, 0)):
            preview = _runtime()
        with patch("zipfile.time.localtime", return_value=(2026, 1, 1, 0, 0, 4, 0, 1, 0)):
            self.assertEqual(_runtime(), preview)

    def test_plain_commit_and_local_only(self):
        with tempfile.TemporaryDirectory() as root:
            repo = Path(root) / "repo"
            profile = Path(root) / "profile"
            repo.mkdir()
            profile.mkdir()
            protected = "synthetic-protected-" + "privacy-marker"
            (profile / "settings.json").write_text(json.dumps(
                {"schema_version": 2, "defaults": {"security": {"never_publish": [protected]}}}),
                encoding="utf-8")

            def git(*args, check=True):
                return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=check)

            def install(mode):
                argv = [str(repo), "--settings-home", str(profile), "--mode", mode, "--json"]
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(main(argv), 0)
                token = json.loads(output.getvalue())["plan_id"]
                result = io.StringIO()
                with contextlib.redirect_stdout(result):
                    code = main([*argv, "--apply", token])
                self.assertEqual(code, 0, result.getvalue())

            git("init", "-q")
            git("config", "user.name", "gate-check")
            git("config", "user.email", "gate-check@users.noreply.github.com")
            install("scan")
            path = repo / "example.txt"
            path.write_text(protected, encoding="utf-8")
            git("add", path.name)
            result = git("commit", "-m", "Staged change", check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("gitso security: blocked (1 finding(s), 0 coverage gap(s)).", result.stderr)
            self.assertNotEqual(git("rev-parse", "--verify", "HEAD", check=False).returncode, 0)

            path.write_text("safe text", encoding="utf-8")
            git("add", path.name)
            result = git("commit", "-m", protected, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("gitso security: blocked", result.stderr)
            git("commit", "-m", "Safe change")
            head = git("rev-parse", "HEAD").stdout

            install("local-only")
            path.write_text("local patch", encoding="utf-8")
            git("add", path.name)
            result = git("commit", "-m", "Local patch", check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("checkout is local-only", result.stderr)
            self.assertEqual(git("rev-parse", "HEAD").stdout, head)
            git("stash", "push", "-m", "Local patch")
            git("stash", "pop")
            self.assertEqual(path.read_text(encoding="utf-8"), "local patch")


if __name__ == "__main__":
    unittest.main()
