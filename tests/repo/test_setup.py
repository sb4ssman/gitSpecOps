"""Setup selection is explicit; fixtures never generate launchers or build environments."""
from __future__ import annotations

import io
import sys
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

import setup_gitspecops as subject  # noqa: E402


class SetupTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.output, self.errors = io.StringIO(), io.StringIO()
        stack.enter_context(redirect_stdout(self.output))
        stack.enter_context(redirect_stderr(self.errors))
        stack.enter_context(patch.object(subject.sys, "stdin", SimpleNamespace(isatty=lambda: False)))
        self.launchers = stack.enter_context(patch.object(subject, "write_launchers"))
        self.environment = stack.enter_context(patch.object(subject, "build_environment", return_value=True))
        self.prerequisites = stack.enter_context(patch.object(subject, "report_prerequisites"))

    def assert_no_actions(self):
        self.launchers.assert_not_called()
        self.environment.assert_not_called()
        self.prerequisites.assert_not_called()

    def interactive(self, answers):
        with patch.object(subject.sys, "stdin", SimpleNamespace(isatty=lambda: True)), \
                patch("builtins.input", side_effect=answers):
            return subject.main([])

    def test_help_never_runs_setup(self):
        with self.assertRaises(SystemExit) as stopped:
            subject.main(["--help"])
        self.assertEqual(stopped.exception.code, 0)
        self.assertIn("bootstrap", self.output.getvalue())
        self.assert_no_actions()

    def test_unattended_run_requires_an_action(self):
        self.assertEqual(subject.main([]), 2)
        self.assertIn("Name a setup action", self.errors.getvalue())
        self.assert_no_actions()

    def test_bootstrap_remains_available_explicitly(self):
        self.assertEqual(subject.main(["bootstrap"]), 0)
        self.launchers.assert_called_once()
        self.environment.assert_called_once()
        self.prerequisites.assert_called_once()

    def test_launchers_do_not_build_an_environment(self):
        self.assertEqual(subject.main(["launchers"]), 0)
        self.launchers.assert_called_once()
        self.environment.assert_not_called()
        self.prerequisites.assert_not_called()

    def test_environment_failure_is_reported(self):
        self.environment.return_value = False
        self.assertEqual(subject.main(["environment"]), 1)
        self.launchers.assert_not_called()
        self.prerequisites.assert_not_called()

    def test_check_only_checks_prerequisites(self):
        self.assertEqual(subject.main(["check"]), 0)
        self.prerequisites.assert_called_once()
        self.launchers.assert_not_called()
        self.environment.assert_not_called()

    def test_guided_selection_runs_only_the_selected_item(self):
        self.assertEqual(self.interactive(["2", "1"]), 0)
        self.launchers.assert_called_once()
        self.environment.assert_not_called()
        self.prerequisites.assert_not_called()

    def test_back_and_invalid_selection_then_exit_do_nothing(self):
        self.assertEqual(self.interactive(["2", "0", "unexpected", "0"]), 0)
        self.assertIn("nothing has been changed", self.output.getvalue())
        self.assert_no_actions()

    def test_end_of_input_cancels_without_setup(self):
        self.assertEqual(self.interactive([EOFError()]), 0)
        self.assertIn("cancelled", self.output.getvalue())
        self.assert_no_actions()


if __name__ == "__main__":
    unittest.main()
