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
        self.launchers = stack.enter_context(patch.object(subject, "write_launchers", return_value=[]))
        self.environment = stack.enter_context(patch.object(subject, "build_environment", return_value=True))
        self.prerequisites = stack.enter_context(patch.object(subject, "report_prerequisites"))
        # The run screen's steps: never a real environment build in a test.
        self.environment_step = stack.enter_context(
            patch.object(subject, "build_environment_step", return_value=("ok", ".venv ready", "")))
        stack.enter_context(patch.object(subject, "check_environment_step", return_value=("ok", "runs", "")))
        self.prerequisites_step = stack.enter_context(
            patch.object(subject, "prerequisites_step", return_value=("ok", "git, gh", "")))

    def assert_no_actions(self):
        self.launchers.assert_not_called()
        self.environment.assert_not_called()
        self.prerequisites.assert_not_called()
        self.environment_step.assert_not_called()
        self.prerequisites_step.assert_not_called()

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
        self.environment_step.assert_called_once()
        self.prerequisites_step.assert_called_once()
        self.assertIn("[4/4] Prerequisites", self.output.getvalue(), "a run screen with numbered steps")

    def test_launchers_do_not_build_an_environment(self):
        self.assertEqual(subject.main(["launchers"]), 0)
        self.launchers.assert_called_once()
        self.environment.assert_not_called()
        self.environment_step.assert_not_called()
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

    # --- the wizard: start, customize, review, apply, done -------------------------------
    def wizard(self, answers, current, changes=None):
        """Run the wizard on a made-up computer: nothing real is detected or changed."""
        from Elaborate._fleet.setup_plan import Change
        self.applied = []
        changes = changes if changes is not None else [
            Change("login", "Start at sign-in", ["one entry"], lambda: self.applied.append("login") or "added")]
        with patch.object(subject, "detect_current", return_value=current), \
                patch.object(subject, "plan_for", return_value=changes), \
                patch.object(subject, "_tray_running", return_value=True), \
                patch.object(subject, "start_tray") as tray:
            self.tray = tray
            return self.interactive(answers)

    def fresh_computer(self):
        from Elaborate._fleet.setup_plan import Current
        return Current(libraries=["/code"], start_at_login=False)

    def test_exit_at_the_start_changes_nothing(self):
        self.assertEqual(self.wizard(["0"], self.fresh_computer()), 0)
        self.assertEqual(self.applied, [])
        self.assert_no_actions()
        self.assertIn("Ready to install", self.output.getvalue())

    def test_review_lists_the_changes_and_cancel_changes_nothing(self):
        self.assertEqual(self.wizard(["1", "0", "0"], self.fresh_computer()), 0)
        out = self.output.getvalue()
        self.assertIn("These changes will be made", out)
        self.assertIn("Start at sign-in: one entry", out)
        self.assertIn("Not changed: your repositories", out)
        self.assertEqual(self.applied, [], "nothing is applied until [I]")
        self.assert_no_actions()

    def test_apply_installs_then_makes_every_planned_change(self):
        self.assertEqual(self.wizard(["1", "i", ""], self.fresh_computer()), 0)
        self.launchers.assert_called_once()
        self.environment_step.assert_called_once()
        self.assertEqual(self.applied, ["login"])
        out = self.output.getvalue()
        self.assertIn("[4/4] Start at sign-in", out, "install steps and the change, on one run screen")
        self.assertIn("gitSpecOps is set up.", out)

    def test_a_first_setup_needs_a_library_before_it_can_apply(self):
        from Elaborate._fleet.setup_plan import Current
        # No library: [1] opens the library screen first; leaving it empty, review offers no [I].
        # Then: Back (to Customize), Back without changes, the review again: Cancel, then Exit.
        self.assertEqual(self.wizard(["1", "0", "b", "0", "0", "0"], Current(start_at_login=False)), 0)
        out = self.output.getvalue()
        self.assertIn("Add a library folder", out)
        self.assertNotIn("[I] Install", out)
        self.assertEqual(self.applied, [])

    def test_customize_back_without_changes_keeps_the_old_choices(self):
        from Elaborate._fleet import setup_plan
        seen = []
        real = setup_plan.plan

        def recording(current, choices, *args, **kwargs):
            seen.append(choices.web)
            return []
        with patch.object(subject, "detect_current", return_value=self.fresh_computer()), \
                patch.object(subject, "plan_for", side_effect=lambda c, ch: recording(c, ch)):
            # Customize, web view -> Tailscale, then "Back without changes", then exit.
            self.interactive(["2", "2", "2", "0", "0"])
        self.assertTrue(seen and set(seen) == {"loopback"}, seen)
        self.assertIs(real, setup_plan.plan)

    def test_end_of_input_cancels_without_setup(self):
        self.assertEqual(self.wizard([EOFError()], self.fresh_computer()), 0)
        self.assertIn("cancelled", self.output.getvalue())
        self.assertEqual(self.applied, [])
        self.assert_no_actions()

    def test_a_set_up_computer_offers_apply_and_uninstall(self):
        from Elaborate._fleet.setup_plan import Current
        current = Current(enrolled=True, machine="Box", libraries=["/code"], start_at_login=True)
        self.assertEqual(self.wizard(["0"], current, changes=[]), 0)
        out = self.output.getvalue()
        self.assertIn("gitSpecOps is set up on this computer", out)
        self.assertIn("[1] Review and apply", out)
        self.assertIn("[U] Uninstall gitSpecOps", out)


if __name__ == "__main__":
    unittest.main()
