"""Setup's release installer: only a checksum-verified program is written; nothing touches the network."""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from _build import release_install  # noqa: E402
from Basic._paths import find_program  # noqa: E402


def archive(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class ReleaseInstallTests(unittest.TestCase):
    def setUp(self):
        self.tools = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tools, ignore_errors=True)
        patcher = patch.dict(os.environ, {"GITSPECOPS_TOOLS": str(self.tools)})
        patcher.start()
        self.addCleanup(patcher.stop)
        system = patch.object(release_install, "system", return_value=("windows", "amd64"))
        system.start()
        self.addCleanup(system.stop)

    def release(self, tag="v3.99.9", data=None, listed_sum=None):
        name = f"trufflehog_{tag.lstrip('v')}_windows_amd64.tar.gz"
        sums_name = f"trufflehog_{tag.lstrip('v')}_checksums.txt"
        blob = archive(data or {"trufflehog.exe": b"program", "README.md": b"readme"})
        digest = listed_sum or hashlib.sha256(blob).hexdigest()
        pages = {
            "https://api.github.com/repos/trufflesecurity/trufflehog/releases/latest": json.dumps({
                "tag_name": tag, "assets": [
                    {"name": name, "browser_download_url": f"https://example.invalid/{name}"},
                    {"name": sums_name, "browser_download_url": f"https://example.invalid/{sums_name}"}]}).encode(),
            f"https://example.invalid/{name}": blob,
            f"https://example.invalid/{sums_name}": f"{digest}  {name}\n".encode(),
        }
        return pages.__getitem__

    def test_a_verified_release_writes_only_the_program_where_gitspecops_finds_it(self):
        result = release_install.install("trufflehog", fetch=self.release())
        self.assertIn("trufflehog 3.99.9 installed", result)
        self.assertEqual(sorted(p.name for p in self.tools.iterdir()), ["trufflehog.exe"])
        self.assertEqual((self.tools / "trufflehog.exe").read_bytes(), b"program")
        if os.name == "nt":
            with patch("shutil.which", return_value=None):
                self.assertEqual(find_program("trufflehog"), str(self.tools / "trufflehog.exe"))

    def test_a_checksum_mismatch_installs_nothing(self):
        with self.assertRaisesRegex(RuntimeError, "checksum does not match"):
            release_install.install("trufflehog", fetch=self.release(listed_sum="0" * 64))
        self.assertEqual(list(self.tools.iterdir()), [])

    def test_a_major_version_gitspecops_does_not_read_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, "does not read yet"):
            release_install.install("trufflehog", fetch=self.release(tag="v4.0.0"))
        self.assertEqual(list(self.tools.iterdir()), [])

    def test_an_archive_without_the_program_installs_nothing(self):
        with self.assertRaisesRegex(RuntimeError, "not in the archive"):
            release_install.install("trufflehog", fetch=self.release(data={"other.exe": b"x"}))
        self.assertEqual(list(self.tools.iterdir()), [])

    def test_a_file_missing_from_the_checksum_list_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, "not in the release's checksum file"):
            release_install.verify(b"data", "a.tar.gz", b"abc  b.tar.gz\n")

    def test_only_https_downloads(self):
        with self.assertRaisesRegex(RuntimeError, "https"):
            release_install._https("http://example.invalid/x")


if __name__ == "__main__":
    unittest.main()
