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
        self.assertIn("environment", self.output.getvalue())
        self.assert_no_actions()

    def test_unattended_run_requires_an_action(self):
        self.assertEqual(subject.main([]), 2)
        self.assertIn("Name a setup action", self.errors.getvalue())
        self.assert_no_actions()

    def test_the_environment_item_remains_available_explicitly(self):
        self.assertEqual(subject.main(["environment"]), 0)
        self.environment.assert_called_once()
        self.prerequisites.assert_called_once()

    def test_setup_writes_no_shortcuts(self):
        self.assertFalse(hasattr(subject, "write_launchers"), "setup must not generate shortcut launchers")
        with self.assertRaises(SystemExit):
            subject.main(["launchers"])

    def test_environment_failure_is_reported(self):
        self.environment.return_value = False
        self.assertEqual(subject.main(["environment"]), 1)
        self.prerequisites.assert_called_once()  # what is missing is shown either way

    def test_check_only_checks_prerequisites(self):
        self.assertEqual(subject.main(["check"]), 0)
        self.prerequisites.assert_called_once()
        self.environment.assert_not_called()

    def test_setup_builds_up_in_gitspecops_own_order(self):
        import setup_walkthrough as walk
        self.assertEqual(walk.AREAS, ("Requirements", "The gitso command", "This machine", "Protection",
                                      "Scanners", "Archives", "Fleet", "The desktop app",
                                      "Desktop Git app", "Running the app"))
        self.assertEqual([f.__name__ for f in walk.AREA_STEPS],
                         ["area_requirements", "area_gitso", "area_machine", "area_protection",
                          "area_scanners", "area_archives", "area_fleet", "area_environment",
                          "area_client", "area_app"])

    def test_uninstall_is_on_the_menu(self):
        self.assertEqual(self.interactive(["0"]), 0)
        self.assertIn("[5] Uninstall", self.output.getvalue())

    def test_menu_item_two_lists_every_part_and_zero_goes_back(self):
        self.assertEqual(self.interactive(["2", "0", "", "0"]), 0)
        out = self.output.getvalue()
        self.assertIn("[4] Protection", out)
        self.assertIn("[10] Running the app", out)
        self.assert_no_actions()

    def test_every_menu_item_comes_back_to_the_menu(self):
        """Item 4 used to print its check and quit setup. Every item is a visit now."""
        with patch.object(subject.sys, "stdin", SimpleNamespace(isatty=lambda: True)), \
                patch("builtins.input", side_effect=["4", "", "4", "", "0"]) as prompt:
            self.assertEqual(subject.main([]), 0)
        self.assertEqual(self.prerequisites.call_count, 2)
        prompts = [call.args[0] for call in prompt.call_args_list]
        self.assertEqual(sum("go back to the setup menu" in text for text in prompts), 2)
        self.assertEqual(self.output.getvalue().count("[4] Check this computer"), 3)

    def test_a_named_action_runs_once_and_exits(self):
        self.assertEqual(subject.main(["check"]), 0)
        self.assertNotIn("[4] Check this computer", self.output.getvalue())

    def test_an_item_that_fails_says_so_and_comes_back(self):
        self.prerequisites.side_effect = SystemExit(1)
        self.assertEqual(self.interactive(["4", "", "0"]), 0)
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
            self.assertEqual(self.interactive(["3", "0"]), 0)
        command_menu.assert_called_once_with(cancel="go back to setup")
        out = self.output.getvalue()
        self.assertIn("Back to setup.", out)
        self.assertEqual(out.count("[3] Use the commands without installing anything"), 2,
                         "the setup menu must come back after the command menu")
        self.assert_no_actions()

    def test_a_blank_answer_in_the_command_menu_goes_back_to_setup(self):
        import gitso
        with patch.object(subject.sys, "stdin", SimpleNamespace(isatty=lambda: True)), \
                patch("builtins.input", side_effect=["3", "", "0"]) as prompt, \
                patch.object(gitso, "dispatch", side_effect=AssertionError("nothing may run")):
            self.assertEqual(subject.main([]), 0)
        prompts = [call.args[0] for call in prompt.call_args_list]
        self.assertEqual(len(prompts), 3, "setup menu, command menu, setup menu again")
        self.assertIn("press Enter to go back to setup", prompts[1])
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
        base = {"git": "git", "gh": "gh", "gh_signed_in": True, "gh_login": "someone", "gh_id": "", "uv": "uv",
                "gitso": None, "tailscale": None, "venv": True, "desktop": True, "git_name": "",
                "git_email": "", "user": "", "enrolled": True, "machine": "Box", "libraries": ["/code"],
                "web": "loopback", "face": "web", "fleet": {}, "tailnet": False, "synced_folders": [],
                "login": "on", "login_elsewhere": "", "client": "", "clients": {},
                "protected": {"never_publish": ["x"]},
                "engines": [], "gitleaks": None, "betterleaks": None, "trufflehog": None,
                "gitso_command": {"launcher": "none", "on_path": False, "folder": "/home/x/.gitspecops/bin",
                                  "aliases": [], "in_this_terminal": False},
                "alias_targets": ["/home/x/.bashrc"], "powershell_profiles_run": None, "archives": [],
                "app_running": False}
        base.update(overrides)
        return base

    def run_walk(self, answers, **overrides):
        with patch("builtins.input", side_effect=answers), \
                patch.object(self.walk, "install_command", return_value=None):
            return self.walk.walkthrough(detector=lambda: self.found(**overrides))

    def test_stopping_at_the_first_question_changes_nothing(self):
        # Requirements asks nothing here (all present); the gitso command asks first.
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

    def test_a_step_running_a_program_keeps_its_number_and_name_beside_the_result(self):
        plan = self.walk.Plan()
        plan.add("Install gitleaks", "gitleaks", lambda: print("\rDownloading 8 MB") or "installed", loud=True)
        self.assertTrue(self.walk.apply(plan))
        lines = self.output.getvalue().splitlines()
        result = next(line for line in lines if "installed" in line and "changed" in line)
        self.assertIn("[1/1] Install gitleaks", result)

    def test_the_alias_offer_warns_about_a_profile_in_onedrive(self):
        self.area(self.walk.area_gitso, ["a", "n"],
                  alias_targets=["C:/Users/x/OneDrive/Documents/PowerShell/profile.ps1"])
        self.assertIn("in OneDrive", self.output.getvalue())

    def test_a_failed_step_is_reported_and_the_rest_still_run(self):
        plan = self.walk.Plan()
        plan.add("Breaks", "breaks", lambda: (_ for _ in ()).throw(RuntimeError("no network")))
        plan.add("Works", "works", lambda: self.applied.append("works") or "done")
        self.assertFalse(self.walk.apply(plan))
        self.assertEqual(self.applied, ["works"])
        out = self.output.getvalue()
        self.assertIn("FAILED", out)
        self.assertIn("Not finished", out)

    def area(self, area, answers, **overrides):
        plan = self.walk.Plan(enrolled_after=True, venv_after=True, desktop_after=True)
        with patch("builtins.input", side_effect=answers):
            area(self.found(**overrides), plan)
        return plan

    def test_start_at_sign_in_turned_off_elsewhere_is_shown_and_can_be_turned_back_on(self):
        plan = self.area(self.walk.area_app, ["t", "n"], login="elsewhere", login_elsewhere="Task Manager (Startup apps)")
        out = self.output.getvalue()
        self.assertIn("off: turned off in Task Manager (Startup apps)", out)
        self.assertIn("[T] Turn it back on", out)
        self.assertEqual([c.review for c in plan.changes],
                         ["Start at sign-in: turn it back on in Task Manager (Startup apps)"])

    def test_start_at_sign_in_can_be_removed(self):
        plan = self.area(self.walk.area_app, ["r", "n"], login="on")
        self.assertEqual([c.review for c in plan.changes], ["Start at sign-in: remove the entry"])

    def test_keeping_start_at_sign_in_changes_nothing(self):
        self.assertEqual(self.area(self.walk.area_app, ["", "n"], login="on").changes, [])

    def test_starting_the_app_is_offered_and_is_the_last_step(self):
        with patch("builtins.input", side_effect=["", "y", "0"]):
            self.walk.walkthrough(detector=lambda: self.found(), only=self.walk.AREAS.index("Running the app"))
        out = self.output.getvalue()
        self.assertIn("Start the app when setup finishes?", out)
        bullets = [line for line in out.splitlines() if line.strip().startswith(". ")]
        self.assertIn("Start the app (tray icon and map)", bullets[-1])

    def test_a_running_app_is_not_started_again(self):
        plan = self.area(self.walk.area_app, [""], login="on", app_running=True)
        self.assertFalse(plan.start_app)
        self.assertIn("The app is running", self.output.getvalue())

    def test_without_the_desktop_app_there_is_no_app_to_start(self):
        plan = self.walk.Plan(enrolled_after=True, venv_after=True, desktop_after=False)
        with patch("builtins.input", side_effect=[]):
            self.walk.area_app(self.found(), plan)
        self.assertFalse(plan.start_app)
        self.assertIn("needs the desktop app (step 8)", self.output.getvalue())

    def test_the_app_is_checked_to_be_still_running_after_it_starts(self):
        import subprocess
        alive = type("P", (), {"wait": lambda self, timeout: (_ for _ in ()).throw(subprocess.TimeoutExpired("x", 1))})()
        dead = type("P", (), {"wait": lambda self, timeout: 1})()
        with patch.object(self.walk.subprocess, "Popen", return_value=alive):
            self.assertIn("running", self.walk._start_app(wait=0))
        with patch.object(self.walk.subprocess, "Popen", return_value=dead):
            with self.assertRaisesRegex(RuntimeError, "stopped at once"):
                self.walk._start_app(wait=0)

    def test_the_desktop_app_question_says_it_is_the_tray_icon_and_map(self):
        plan = self.walk.Plan()
        with patch("builtins.input", side_effect=["y"]):
            self.walk.area_environment(self.found(desktop=False), plan)
        out = self.output.getvalue()
        self.assertIn("Install the desktop app, the tray icon and map?", out)
        self.assertTrue(plan.desktop_after)
        self.assertIn("tray icon and map", plan.changes[0].review)

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

    def test_public_commit_identity_is_shown_and_never_offered_for_protection(self):
        # The handle@machine name and the no-reply email are on every commit: protecting either
        # would hold every commit. Only the computer's user name is offered, shown in full.
        plan = self.area(self.walk.area_protection, ["y", "n"], git_name="someone@Box",
                         git_email="42+someone@users.noreply.github.com", user="pat", gh_id="42")
        out = self.output.getvalue()
        self.assertEqual(out.count("(public)"), 2)
        self.assertNotIn("Protect your git", out)
        self.assertIn("Protect this computer's user name, pat?", out)
        self.assertEqual([c.review for c in plan.changes], ["Protect pat (whole word only)"])

    def test_a_private_email_can_be_swapped_for_the_no_reply_address_and_then_protected(self):
        plan = self.area(self.walk.area_protection, ["y", "y", "n"], git_name="someone",
                         git_email="pat@example.invalid", gh_id="42")
        self.assertEqual([c.review for c in plan.changes], [
            "Git email: commit as 42+someone@users.noreply.github.com (git config --global user.email)",
            "Protect pat@example.invalid (anywhere in text)"])

    def test_a_private_email_kept_in_use_is_not_protected(self):
        plan = self.area(self.walk.area_protection, ["n", "n"], git_email="pat@example.invalid", gh_id="42")
        self.assertEqual(plan.changes, [])
        self.assertIn("that would hold every commit", self.output.getvalue())

    def test_without_a_github_sign_in_the_no_reply_address_can_be_pasted(self):
        plan = self.area(self.walk.area_protection, ["7+pat@users.noreply.github.com", "y", "y", "n"],
                         gh_login="", git_email="pat@example.invalid")
        self.assertIn("https://github.com/settings/emails", self.output.getvalue())
        self.assertEqual([c.title for c in plan.changes], ["Git email", "Protected value"])

    def test_a_pasted_address_that_is_not_a_no_reply_address_changes_nothing(self):
        plan = self.area(self.walk.area_protection, ["pat@example.invalid", "n"], gh_login="",
                         git_email="pat@example.invalid")
        self.assertEqual(plan.changes, [])
        self.assertIn("not a GitHub no-reply address", self.output.getvalue())

    def test_a_private_git_name_can_be_swapped_for_the_github_handle(self):
        plan = self.area(self.walk.area_protection, ["y", "y", "n"], git_name="Pat Example")
        self.assertEqual([c.review for c in plan.changes], [
            "Git name: commit as someone (git config --global user.name)",
            "Protect Pat Example (anywhere in text)"])

    def test_an_added_name_needs_no_matching_question_and_a_short_word_gets_a_plain_one(self):
        plan = self.area(self.walk.area_protection, ["a", "Pat Example", "a", "pat", "y", "n"])
        self.assertEqual([c.review for c in plan.changes],
                         ["Protect Pat Example (anywhere in text)", "Protect pat (whole word only)"])
        out = self.output.getvalue()
        self.assertEqual(out.count("only as a separate word?"), 1)
        self.assertIn("Match pat only as a separate word?", out)

    def test_one_part_runs_only_that_part(self):
        with patch("builtins.input", side_effect=["n", "0"]):
            self.assertEqual(self.walk.walkthrough(detector=lambda: self.found(), only=self.walk.AREAS.index("Protection")), 0)
        out = self.output.getvalue()
        self.assertIn("Setup  4/10:  Protection", out)
        self.assertNotIn("Setup  1/10", out)
        self.assertIn("Your full name as you write it", out)
        self.assertIn("settings.json", out)

    def test_the_part_picker_takes_only_a_listed_number(self):
        with patch("builtins.input", side_effect=["11", "x", "7"]):
            self.assertEqual(self.walk.choose_part(), 6)
        self.assertEqual(self.output.getvalue().count("Choose a number from the list."), 2)

    def test_every_scanner_is_offered_the_same_way_and_yes_is_the_only_question(self):
        # No package for trufflehog here: it is offered from its checked GitHub release instead.
        def command(name):
            return None if name == "trufflehog" else ["installer", name]
        from _build import release_install
        with patch.object(self.walk, "install_command", side_effect=command),                 patch.object(release_install, "available", return_value=True):
            plan = self.area(self.walk.area_scanners, ["y", "n", "y"])
        out = self.output.getvalue()
        self.assertEqual(out.count("Install "), 3)
        self.assertIn("Install trufflehog?", out)
        self.assertNotIn("in every scan?", out)
        self.assertEqual([c.title for c in plan.changes],
                         ["Install gitleaks", "Install trufflehog", "Scanners used"])
        self.assertIn("checks its SHA-256", plan.changes[1].review)
        self.assertEqual(plan.changes[2].review, "Scanners used in scans: gitleaks, trufflehog")

    def test_a_scanner_with_no_package_and_no_release_says_there_is_nothing_to_decide(self):
        from _build import release_install
        with patch.object(self.walk, "install_command", return_value=None),                 patch.object(release_install, "available", return_value=False):
            plan = self.area(self.walk.area_scanners, [])
        self.assertIn("Setup cannot install trufflehog on this system", self.output.getvalue())
        self.assertEqual(plan.changes, [])

    def test_an_installed_scanner_is_asked_about_once(self):
        from _build import release_install
        with patch.object(self.walk, "install_command", return_value=None),                 patch.object(release_install, "available", return_value=False):
            plan = self.area(self.walk.area_scanners, ["y"], gitleaks="gitleaks")
        self.assertIn("gitleaks is already installed. Use it in every scan?", self.output.getvalue())
        self.assertEqual([c.review for c in plan.changes], ["Scanners used in scans: gitleaks"])

    def uninstall_found(self):
        return self.found(login="on", fleet={"tailnet": {}},
                          gitso_command={"launcher": "here", "on_path": True, "folder": "/home/x/.gitspecops/bin",
                                         "aliases": ["/home/x/.bashrc"], "in_this_terminal": True})

    def run_uninstall(self, answers, settings_exist=True):
        import os
        import tempfile
        temp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, temp, ignore_errors=True)
        home = temp / "settings"
        if settings_exist:
            home.mkdir()
        with patch.dict(os.environ, {"GITSPECOPS_HOME": str(home), "GITSPECOPS_TOOLS": str(temp / "tools")}), \
                patch.object(self.walk, "find_app_processes", return_value=[11]), \
                patch.object(self.walk, "_archive_task_present", return_value=False), \
                patch.object(self.walk, "apply", return_value=True) as applied, \
                patch("builtins.input", side_effect=answers):
            code = self.walk.uninstall(detector=self.uninstall_found)
        return code, applied

    def test_uninstall_lists_every_removal_and_cancel_changes_nothing(self):
        code, applied = self.run_uninstall(["n", "0"])
        self.assertEqual(code, 0)
        applied.assert_not_called()
        out = self.output.getvalue()
        for text in ("Stop the app: end its 1 process(es)", "Start at sign-in: remove the entry",
                     "Fleet: leave", "gitso alias: remove", "gitso command: delete it", "Not removed:"):
            self.assertIn(text, out)
        self.assertNotIn("Settings: delete", out)

    def test_uninstall_deletes_settings_only_when_asked_and_stops_the_app_first(self):
        _code, applied = self.run_uninstall(["y", "u"])
        plan = applied.call_args.args[0]
        titles = [c.title for c in plan.changes]
        # The reverse of setup's order: the App first, Basic (the gitso command) last.
        self.assertEqual(titles, ["Stop the app", "Start at sign-in", "Desktop app", "Settings",
                                  "gitso alias", "The gitso command"])
        self.assertNotIn("Fleet", titles, "deleting the settings leaves the fleet with them")

    def test_public_identity_rules(self):
        self.assertTrue(self.walk.public_git_name("Someone@Box", "someone"))
        self.assertTrue(self.walk.public_git_name("someone", "someone"))
        self.assertFalse(self.walk.public_git_name("someone-else", "someone"))
        self.assertFalse(self.walk.public_git_name("Pat", ""))
        self.assertTrue(self.walk.public_git_email("noreply@github.com"))
        self.assertFalse(self.walk.public_git_email("pat@example.invalid"))
        self.assertEqual(self.walk.noreply_address("someone", "42"), "42+someone@users.noreply.github.com")
        self.assertEqual(self.walk.noreply_address("someone", ""), "")

    def test_an_archive_is_planned_after_reading_its_folder_and_changes_nothing_yet(self):
        folder = Path(__file__).resolve().parent
        proposal = {"root": str(folder), "repositories": ["one", "two"]}
        with patch("Special._archive.manager.registration_plan", return_value=proposal) as read:
            plan = self.area(self.walk.area_archives, ["p", str(folder), "2", "", "y"])
        read.assert_called_once()
        self.assertEqual(read.call_args.args[2], "sync")
        self.assertEqual([change.title for change in plan.changes], ["Archive", "Monthly refresh"])
        self.assertIn("2 repositories", plan.changes[0].review)
        self.assertIn("Nothing is pulled or cloned now", plan.changes[0].review)

    def test_no_archives_asks_nothing_more(self):
        self.assertEqual(self.area(self.walk.area_archives, [""]).changes, [])


if __name__ == "__main__":
    unittest.main()
