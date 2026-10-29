"""Common catalog/menu/dispatch contracts and real --help routes; no live operations.

    python tests/repo/test_gitso.py
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT, setup
setup()
import gitso


class GitsoTests(unittest.TestCase):
    def test_catalog_and_docs_never_import_or_dispatch_operations(self):
        for arguments in (["commands", "--json"], ["docs"], ["docs", "scan-tree"], ["--help"]):
            output = io.StringIO()
            with self.subTest(arguments=arguments), \
                 patch.object(gitso.importlib, "import_module", side_effect=AssertionError("unexpected import")), \
                 patch.object(gitso, "dispatch", side_effect=AssertionError("unexpected operation")), redirect_stdout(output):
                self.assertEqual(gitso.main(arguments), 0)
            self.assertTrue(output.getvalue())
            if arguments == ["commands", "--json"]:
                self.assertEqual(len(json.loads(output.getvalue())["commands"]), 16)

    def test_catalog_is_unique_and_descriptions_come_from_actual_source(self):
        self.assertEqual(len({command.name for command in gitso.COMMANDS}), len(gitso.COMMANDS))
        for command in gitso.COMMANDS:
            with self.subTest(command=command.name):
                self.assertTrue((ROOT / command.script).is_file())
                self.assertTrue(command.documentation())
                self.assertEqual(command.record()["description"], command.documentation().splitlines()[0])

    def test_dispatch_passes_exact_arguments_and_security_material_without_global_argv(self):
        calls = []
        command = next(command for command in gitso.COMMANDS if command.name == "scan-history")
        before = list(sys.argv)
        with patch.object(gitso.importlib, "import_module", return_value=SimpleNamespace(
                main=lambda *args: calls.append(args) or 1)):
            self.assertEqual(gitso.dispatch(command, ["folder with spaces", "--engine", "none"]), 1)
        self.assertEqual(calls, [("history", ["folder with spaces", "--engine", "none"])])
        self.assertEqual(sys.argv, before)

    def test_unattended_empty_invocation_is_help_not_a_menu_or_operation(self):
        with patch.object(sys.stdin, "isatty", return_value=False), \
             patch.object(gitso, "menu", side_effect=AssertionError("unexpected prompt")), \
             patch.object(gitso, "dispatch", side_effect=AssertionError("unexpected operation")), redirect_stdout(io.StringIO()):
            self.assertEqual(gitso.main([]), 0)

    def test_unattended_interactive_operations_do_not_prompt(self):
        with patch.object(sys.stdin, "isatty", return_value=False), \
             patch.object(gitso, "dispatch", side_effect=AssertionError("unexpected operation")), redirect_stderr(io.StringIO()):
            for name in ("duplicate-org", "archive-manager", "inventory-export", "inventory-restore"):
                with self.subTest(name=name):
                    self.assertEqual(gitso.main([name]), 2)
            self.assertEqual(gitso.main(["menu"]), 2)

    def test_selected_updater_preserves_its_saved_default_invocation(self):
        with patch.object(sys.stdin, "isatty", return_value=False), patch.object(gitso, "dispatch", return_value=0) as dispatch:
            self.assertEqual(gitso.main(["update-archive"]), 0)
        self.assertEqual(dispatch.call_args.args[1], [])

    def test_invalid_command_and_cancelled_menu_do_not_dispatch(self):
        with patch.object(gitso, "dispatch", side_effect=AssertionError("unexpected operation")), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(gitso.main(["unknown"]), 2)
            self.assertEqual(gitso.main(["docs", "unknown"]), 2)
            with patch.object(sys.stdin, "isatty", return_value=True), patch("builtins.input", return_value=""):
                self.assertEqual(gitso.main(["menu"]), 0)

    def test_every_public_help_route_works_outside_checkout_without_profile_creation(self):
        with tempfile.TemporaryDirectory(prefix="gitso-help-") as temporary:
            home = Path(temporary) / "profile"
            environment = dict(os.environ, GITSPECOPS_HOME=str(home), PYTHONDONTWRITEBYTECODE="1")
            environment.pop("GITSPECOPS_SYNC_HOME", None)
            for command in gitso.COMMANDS:
                with self.subTest(command=command.name):
                    result = subprocess.run([sys.executable, "-B", str(ROOT / "gitso.py"), command.name, "--help"],
                                            cwd=temporary, env=environment, text=True, capture_output=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertTrue(result.stdout)
                    self.assertFalse(home.exists())


if __name__ == "__main__":
    unittest.main()
