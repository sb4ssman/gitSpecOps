"""`gitso` on the command path and as an alias: written, found, and removed without a trace.

Every check runs in a temporary home folder with made-up shells; the real PATH, registry and
profiles are never touched.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from _build import gitso_command as command  # noqa: E402

GITSO = command.GITSO.as_posix()


def shells(*present):
    return lambda name: f"/usr/bin/{name}" if name in present else None


class PosixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.which = shells("bash", "zsh")

    def test_launcher_is_a_readable_script_and_its_folder_goes_on_path(self):
        (self.home / ".bashrc").write_text("# mine\nexport EDITOR=vi\n", encoding="utf-8")
        command.install_launchers(self.home, "linux", self.which)
        launcher = self.home / ".gitspecops" / "bin" / "gitso"
        text = launcher.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("#!/bin/sh"))
        self.assertIn(GITSO, text)
        for name in (".profile", ".bashrc", ".zshenv"):
            self.assertIn("$HOME/.gitspecops/bin", (self.home / name).read_text(encoding="utf-8"), name)
        state = command.status(self.home, "linux", self.which)
        self.assertEqual((state["launcher"], state["on_path"]), ("here", True))

    def test_installing_twice_writes_one_block(self):
        command.install_launchers(self.home, "linux", self.which)
        command.install_launchers(self.home, "linux", self.which)
        self.assertEqual((self.home / ".profile").read_text(encoding="utf-8").count(">>> gitSpecOps path"), 1)

    def test_removing_leaves_nothing_and_keeps_the_persons_own_lines(self):
        (self.home / ".bashrc").write_text("# mine\nexport EDITOR=vi\n", encoding="utf-8")
        command.install_launchers(self.home, "linux", self.which)
        command.remove_launchers(self.home, "linux", self.which)
        self.assertFalse((self.home / ".gitspecops").exists())
        self.assertFalse((self.home / ".profile").exists(), "setup made it and only setup's lines were in it")
        self.assertEqual((self.home / ".bashrc").read_text(encoding="utf-8"), "# mine\nexport EDITOR=vi\n")
        self.assertEqual(command.status(self.home, "linux", self.which)["launcher"], "none")

    def test_aliases_go_in_each_present_shell_and_come_out_again(self):
        with patch.object(command, "powershell_profiles", return_value={}):
            command.install_aliases(self.home, "linux", self.which)
            for name in (".bashrc", ".zshrc"):
                text = (self.home / name).read_text(encoding="utf-8")
                self.assertIn("gitso()", text)
                self.assertIn(GITSO, text)
            self.assertEqual(len(command.status(self.home, "linux", self.which)["aliases"]), 2)
            command.remove_aliases(self.home, "linux", self.which)
            self.assertEqual(command.status(self.home, "linux", self.which)["aliases"], [])

    def test_a_launcher_for_another_folder_is_reported(self):
        launcher = self.home / ".gitspecops" / "bin" / "gitso"
        launcher.parent.mkdir(parents=True)
        launcher.write_text('#!/bin/sh\nexec python3 "/elsewhere/gitso.py" "$@"\n', encoding="utf-8")
        self.assertEqual(command.status(self.home, "linux", self.which)["launcher"], "elsewhere")


class WindowsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.user_path = []
        stack = [patch.object(command, "windows_path_set", side_effect=self.set_path),
                 patch.object(command, "windows_path_has", side_effect=lambda folder: folder in self.user_path),
                 patch.object(command, "powershell_profiles", return_value={})]
        for item in stack:
            item.start()
            self.addCleanup(item.stop)

    def set_path(self, folder, present):
        if present and folder not in self.user_path:
            self.user_path.append(folder)
        if not present and folder in self.user_path:
            self.user_path.remove(folder)
        return True

    def test_cmd_and_git_bash_launchers_and_the_user_path(self):
        command.install_launchers(self.home, "windows", shells())
        folder = self.home / ".gitspecops" / "bin"
        cmd = (folder / "gitso.cmd").read_text(encoding="utf-8")
        self.assertIn("goto fallback", cmd, "labels, not a parenthesised block that a path's ')' would break")
        self.assertIn(str(command.GITSO), cmd)
        self.assertTrue((folder / "gitso").read_text(encoding="utf-8").startswith("#!/bin/sh"))
        self.assertEqual(self.user_path, [folder])
        self.assertEqual(command.status(self.home, "windows", shells())["launcher"], "here")
        command.remove_launchers(self.home, "windows", shells())
        self.assertEqual(self.user_path, [])
        self.assertFalse((self.home / ".gitspecops").exists())

    def test_percent_signs_in_paths_are_escaped_for_cmd(self):
        self.assertEqual(command._cmd(r"C:\50%\python.exe"), r"C:\50%%\python.exe")


if __name__ == "__main__":
    unittest.main()
