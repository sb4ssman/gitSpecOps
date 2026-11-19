"""The commit gate reads staged bytes and the message, with no real profile or secret."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup

setup()

from _build.repo_commit_gate import check  # noqa: E402


class CommitGateTests(unittest.TestCase):
    def test_staged_material_and_message_cannot_allow_a_tailnet_shape(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo = root / "repo"
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            address = ".".join(("100", "64", "0", "3"))
            profile = root / "profile"
            profile.mkdir()
            (profile / "settings.json").write_text(
                '{"schema_version":2,"defaults":{"security":{"safe_values":["' + address + '"]}}}',
                encoding="utf-8")
            source = repo / "example.txt"
            source.write_text(address, encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "example.txt"], check=True)
            source.write_text("clean working file", encoding="utf-8")
            with patch.dict(os.environ, {"GITSPECOPS_HOME": str(profile)}):
                self.assertEqual(check(repo), (1, 0))
                subprocess.run(["git", "-C", str(repo), "add", "example.txt"], check=True)
                self.assertEqual(check(repo), (0, 0))
                message = root / "message"
                message.write_text(address, encoding="utf-8")
                self.assertEqual(check(repo, message), (1, 0))


if __name__ == "__main__":
    unittest.main()
