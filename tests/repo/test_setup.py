"""Setup selection is explicit; fixtures never build environments, and setup writes no shortcuts."""
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

from _build import setup_gitspecops as subject  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_build"))  # setup_walkthrough beside setup


class SetupTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.output, self.errors = io.StringIO(), io.StringIO()
        stack.enter_context(redirect_stdout(self.output))
        stack.enter_context(redirect_stderr(self.errors))
        stack.enter_context(patch.object(subject.sys, "stdin", SimpleNamespace(isatty=lambda: False)))
        self.environment = stack.enter_context(patch.object(subject, "build_environment", return_value=True))
        self.prerequisites = stack.enter_context(patch.object(subject, "report_prerequisites"))

    def assert_no_actions(self):
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
        self.environment.assert_called_once()
        self.prerequisites.assert_called_once()

    def test_setup_writes_no_shortcuts(self):
        self.assertFalse(hasattr(subject, "write_launchers"), "setup must not generate shortcut launchers")
        with self.assertRaises(SystemExit):
            subject.main(["launchers"])

    def test_environment_failure_is_reported(self):
        self.environment.return_value = False
        self.assertEqual(subject.main(["environment"]), 1)
        self.prerequisites.assert_not_called()

    def test_check_only_checks_prerequisites(self):
        self.assertEqual(subject.main(["check"]), 0)
        self.prerequisites.assert_called_once()
        self.environment.assert_not_called()

    def test_menu_item_two_builds_the_environment_only(self):
        self.assertEqual(self.interactive(["2"]), 0)
        self.environment.assert_called_once()
        self.prerequisites.assert_called_once()

    def test_the_walkthrough_is_the_first_and_default_item(self):
        with patch.object(subject.sys, "stdin", SimpleNamespace(isatty=lambda: True)), \
                patch("builtins.input", side_effect=["0"]) as prompt:
            self.assertIsNone(subject.choose_action())
        self.assertIn("[1] Walk me through everything", self.output.getvalue())
        self.assertIn("Choose [1]:", prompt.call_args.args[0])

    def test_invalid_selection_then_exit_do_nothing(self):
        self.assertEqual(self.interactive(["unexpected", "0"]), 0)
        self.assertIn("nothing has been changed", self.output.getvalue())
        self.assert_no_actions()

    def test_end_of_input_cancels_without_setup(self):
        self.assertEqual(self.interactive([EOFError()]), 0)
        self.assertIn("cancelled", self.output.getvalue())
        self.assert_no_actions()


class WalkthroughTests(unittest.TestCase):
    """The walkthrough on a made-up computer: nothing real is detected, installed or changed."""

    def setUp(self):
        import setup_walkthrough
        self.walk = setup_walkthrough
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.output = io.StringIO()
        stack.enter_context(redirect_stdout(self.output))
        self.applied = []

    def found(self, **overrides):
        base = {"git": "git", "gh": "gh", "gh_signed_in": True, "gh_login": "someone", "uv": "uv",
                "gitso": None, "tailscale": None, "venv": True, "desktop": True, "git_name": "",
                "git_email": "", "user": "", "enrolled": True, "machine": "Box", "libraries": ["/code"],
                "web": "loopback", "face": "web", "fleet": {}, "tailnet": False, "synced_folders": [],
                "login": True, "client": "", "clients": {}, "protected": {"never_publish": ["x"]},
                "engines": [], "gitleaks": None, "betterleaks": None, "trufflehog": None}
        base.update(overrides)
        return base

    def run_walk(self, answers, **overrides):
        with patch("builtins.input", side_effect=answers), \
                patch.object(self.walk, "install_command", return_value=None):
            return self.walk.walkthrough(detector=lambda: self.found(**overrides))

    def test_stopping_at_the_first_question_changes_nothing(self):
        # Requirements asks nothing here (all present); the environment area asks first.
        self.assertEqual(self.run_walk(["0"]), 0)
        self.assertIn("Walkthrough stopped", self.output.getvalue())
        self.assertIn("Nothing has been changed", self.output.getvalue())

    def test_a_missing_git_stops_before_any_question(self):
        self.assertEqual(self.run_walk([], git=None), 0)
        self.assertIn("Git is required", self.output.getvalue())

    def test_review_lists_every_change_and_cancel_applies_nothing(self):
        plan = self.walk.Plan()
        plan.add("Start at sign-in", "Start at sign-in: add one entry", lambda: self.applied.append("login"))
        with patch("builtins.input", side_effect=["0"]):
            self.assertEqual(self.walk.review(plan, enrolled=False), "0")
        out = self.output.getvalue()
        self.assertIn("These changes will be made", out)
        self.assertIn("Start at sign-in: add one entry", out)
        self.assertIn("[I] Install", out)
        self.assertEqual(self.applied, [])

    def test_apply_runs_each_change_as_a_numbered_step(self):
        plan = self.walk.Plan()
        plan.add("First", "first", lambda: self.applied.append(1) or "done")
        plan.add("Second", "second", lambda: self.applied.append(2) or "done")
        self.assertTrue(self.walk.apply(plan))
        self.assertEqual(self.applied, [1, 2])
        self.assertIn("[2/2] Second", self.output.getvalue())

    def test_a_failed_step_is_reported_and_the_rest_still_run(self):
        plan = self.walk.Plan()
        plan.add("Breaks", "breaks", lambda: (_ for _ in ()).throw(RuntimeError("no network")))
        plan.add("Works", "works", lambda: self.applied.append("works") or "done")
        self.assertFalse(self.walk.apply(plan))
        self.assertEqual(self.applied, ["works"])
        out = self.output.getvalue()
        self.assertIn("FAILED", out)
        self.assertIn("Setup incomplete", out)

    def test_protected_values_are_masked_on_screen(self):
        self.assertEqual(self.walk.masked("someone@example.invalid"), "so" + "*" * 20 + "d")


if __name__ == "__main__":
    unittest.main()
