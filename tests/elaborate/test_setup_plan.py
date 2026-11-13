"""The setup engine: detect, choose, plan, apply. A throwaway profile and library only.

Pins: building a plan changes nothing; choices equal to the current state plan nothing; a
library to add is one change whose review says what will be read; applying it enrolls the
machine and leaves nothing more to plan; impossible choices are named before review.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Elaborate._fleet import setup_plan  # noqa: E402

OFFLINE = {"git": True, "github": False, "tailnet": False, "dashboard": True, "port": 8760, "folders": []}


class SetupPlanTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="setup-plan-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.home, self.state_dir, self.library = root / "profile", root / "state", root / "code"
        self.home.mkdir()
        (self.home / "settings.json").write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.library / "one")], check=True)
        for target in (patch("Elaborate._fleet.cli.preflight_state", return_value=dict(OFFLINE)),
                       patch("Elaborate._fleet.autostart.status", return_value={"supported": True, "enabled": False})):
            target.start()
            self.addCleanup(target.stop)

    def detect(self):
        return setup_plan.detect(self.home, self.state_dir)

    def plan(self, current, choices):
        return setup_plan.plan(current, choices, self.home, self.state_dir)

    def test_choices_equal_to_the_current_state_plan_nothing(self):
        before = (self.home / "settings.json").read_text(encoding="utf-8")
        current = self.detect()
        self.assertFalse(current.enrolled)
        choices = setup_plan.choices_from(current)
        choices.start_at_login = current.start_at_login
        self.assertEqual(self.plan(current, choices), [])
        self.assertEqual((self.home / "settings.json").read_text(encoding="utf-8"), before, "detecting changes nothing")

    def test_adding_a_library_is_one_reviewed_change_and_applying_it_enrolls(self):
        current = self.detect()
        choices = setup_plan.choices_from(current)
        choices.start_at_login = current.start_at_login
        choices.libraries = [str(self.library)]
        changes = self.plan(current, choices)
        self.assertEqual([change.key for change in changes], ["libraries"])
        self.assertIn("Never file contents", " ".join(changes[0].review))
        self.assertFalse(self.detect().enrolled, "planning changed nothing")
        changes[0].apply()
        after = self.detect()
        self.assertTrue(after.enrolled)
        self.assertEqual(after.libraries, [str(self.library.resolve())])
        again = setup_plan.choices_from(after)
        self.assertEqual(self.plan(after, again), [], "applied: nothing left to plan")

    def test_impossible_choices_are_named_before_review(self):
        current = self.detect()
        choices = setup_plan.choices_from(current)
        choices.fleet_mode, choices.fleet_key = "join", "short"
        found = " ".join(setup_plan.problems(current, choices))
        self.assertIn("needs a library folder", found)
        self.assertIn("way to share", found)
        self.assertIn("64-character fleet key", found)
        choices.fleet_mode = "keep"
        choices.web = "tailnet"
        self.assertIn("add one first", " ".join(setup_plan.problems(current, choices)))
        self.assertNotIn("web", [change.key for change in self.plan(current, choices)],
                         "the web view's reach waits for a library")


if __name__ == "__main__":
    unittest.main()
