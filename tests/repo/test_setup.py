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

    def test_menu_item_three_builds_the_environment_only(self):
        self.assertEqual(self.interactive(["3", "", "0"]), 0)
        self.environment.assert_called_once()
        self.prerequisites.assert_called_once()

    def test_every_menu_item_comes_back_to_the_menu(self):
        """Item 4 used to print its check and quit setup. Every item is a visit now."""
        with patch.object(subject.sys, "stdin", SimpleNamespace(isatty=lambda: True)), \
                patch("builtins.input", side_effect=["4", "", "4", "", "0"]) as prompt:
            self.assertEqual(subject.main([]), 0)
        self.assertEqual(self.prerequisites.call_count, 2)
        prompts = [call.args[0] for call in prompt.call_args_list]
        self.assertEqual(sum("go back to the setup menu" in text for text in prompts), 2)
        self.assertEqual(self.output.getvalue().count("[4] Check prerequisites"), 3)

    def test_a_named_action_runs_once_and_exits(self):
        self.assertEqual(subject.main(["check"]), 0)
        self.assertNotIn("[4] Check prerequisites", self.output.getvalue())

    def test_an_item_that_fails_says_so_and_comes_back(self):
        self.environment.return_value = False
        self.assertEqual(self.interactive(["3", "", "0"]), 0)
        self.assertIn("That item did not finish", self.output.getvalue())

    def test_an_item_stopped_with_ctrl_c_comes_back_to_the_menu(self):
        self.prerequisites.side_effect = KeyboardInterrupt
        with patch.object(subject.sys, "stdin", SimpleNamespace(isatty=lambda: True)), \
                patch("builtins.input", side_effect=["4", "", "0"]):
            self.assertEqual(subject.main([]), 0)
        self.assertIn("Stopped.", self.output.getvalue())

    def test_menu_item_two_runs_one_command_then_returns_to_setup(self):
        import gitso
        with patch.object(gitso, "menu", return_value=0) as command_menu:
            self.assertEqual(self.interactive(["2", "0"]), 0)
        command_menu.assert_called_once_with(cancel="go back to setup")
        out = self.output.getvalue()
        self.assertIn("Back to setup.", out)
        self.assertEqual(out.count("[2] Run one command, without setting anything up"), 2,
                         "the setup menu must come back after the command menu")
        self.assert_no_actions()

    def test_a_blank_answer_in_the_command_menu_goes_back_to_setup(self):
        import gitso
        with patch.object(subject.sys, "stdin", SimpleNamespace(isatty=lambda: True)), \
                patch("builtins.input", side_effect=["2", "", "0"]) as prompt, \
                patch.object(gitso, "dispatch", side_effect=AssertionError("nothing may run")):
            self.assertEqual(subject.main([]), 0)
        prompts = [call.args[0] for call in prompt.call_args_list]
        self.assertEqual(len(prompts), 3, "setup menu, command menu, setup menu again")
        self.assertIn("leave blank to go back to setup", prompts[1])
        self.assert_no_actions()

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
                "login": "on", "login_elsewhere": "", "client": "", "clients": {},
                "protected": {"never_publish": ["x"]},
                "engines": [], "gitleaks": None, "betterleaks": None, "trufflehog": None,
                "gitso_command": {"launcher": "none", "on_path": False, "folder": "/home/x/.gitspecops/bin",
                                  "aliases": [], "in_this_terminal": False},
                "alias_targets": ["/home/x/.bashrc"], "powershell_profiles_run": None}
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

    def area(self, area, answers, **overrides):
        plan = self.walk.Plan(enrolled_after=True, venv_after=True)
        with patch("builtins.input", side_effect=answers):
            area(self.found(**overrides), plan)
        return plan

    def test_start_at_sign_in_turned_off_elsewhere_is_shown_and_can_be_turned_back_on(self):
        plan = self.area(self.walk.area_app, ["t"], login="elsewhere", login_elsewhere="Task Manager (Startup apps)")
        out = self.output.getvalue()
        self.assertIn("off: turned off in Task Manager (Startup apps)", out)
        self.assertIn("[T] Turn it back on", out)
        self.assertEqual([c.review for c in plan.changes],
                         ["Start at sign-in: turn it back on in Task Manager (Startup apps)"])

    def test_start_at_sign_in_can_be_removed(self):
        plan = self.area(self.walk.area_app, ["r"], login="on")
        self.assertEqual([c.review for c in plan.changes], ["Start at sign-in: remove the entry"])

    def test_keeping_start_at_sign_in_changes_nothing(self):
        self.assertEqual(self.area(self.walk.area_app, [""], login="on").changes, [])

    def test_without_tailscale_the_fleet_does_not_ask_about_it(self):
        self.area(self.walk.area_fleet, ["n"], tailscale=None, tailnet=False)
        out = self.output.getvalue()
        self.assertIn("not installed (optional)", out)
        self.assertNotIn("operate over Tailscale?", out)

    def test_a_fleet_member_can_start_operating_over_tailscale(self):
        plan = self.area(self.walk.area_fleet, ["t", "n"], tailscale="tailscale", tailnet=True,
                         fleet={"folder": {}})
        self.assertEqual([c.review for c in plan.changes], ["Fleet: operate over Tailscale"])
        self.assertIn("Also open this machine's map in a browser", self.output.getvalue())

    def test_starting_a_fleet_over_tailscale(self):
        plan = self.area(self.walk.area_fleet, ["1", "y", "y", "n"], tailscale="tailscale", tailnet=True)
        self.assertEqual([c.review for c in plan.changes], ["Fleet: start a fleet, operating over Tailscale"])

    def test_gitso_can_be_put_on_the_command_path_with_an_optional_alias(self):
        plan = self.area(self.walk.area_gitso, ["a", "y"])
        self.assertEqual([c.title for c in plan.changes], ["The gitso command", "gitso alias"])
        self.assertIn("/home/x/.gitspecops/bin", plan.changes[0].review)
        self.assertIn("/home/x/.bashrc", plan.changes[1].review)
        self.assertNotIn("uv tool", self.output.getvalue())

    def test_gitso_in_place_can_be_kept_or_removed(self):
        here = {"launcher": "here", "on_path": True, "folder": "/home/x/.gitspecops/bin",
                "aliases": ["/home/x/.bashrc"], "in_this_terminal": True}
        self.assertEqual(self.area(self.walk.area_gitso, ["", ""], gitso_command=here).changes, [])
        plan = self.area(self.walk.area_gitso, ["r", "n"], gitso_command=here)
        self.assertEqual([c.review.split(":")[0] for c in plan.changes], ["gitso command", "gitso alias"])

    def test_protected_values_are_masked_on_screen(self):
        self.assertEqual(self.walk.masked("someone@example.invalid"), "so" + "*" * 20 + "d")


if __name__ == "__main__":
    unittest.main()
