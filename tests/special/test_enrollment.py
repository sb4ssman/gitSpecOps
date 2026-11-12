"""Machine enrollment (this machine, its libraries, its face) apart from fleet enrollment.

Temporary profiles and invented folders only. Pins: nothing is enrolled or looked at without
consent; several libraries; no overlapping libraries; the last library cannot be removed; a
machine-only enrollment runs the peer with no transports; presentation choices are validated
and drive what App serves; a fleet key can be replaced only before anything was shared.
"""
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from App._launch import presentation  # noqa: E402
from Elaborate._fleet.cli import command_leave, load_saved, main as fleet_main  # noqa: E402
from Special._settings import SettingsError  # noqa: E402
from Special._settings.fleet import load_fleet_settings, replace_fleet_secret  # noqa: E402
from Special._sync import enrollment  # noqa: E402
from Special._sync.commands import enroll_machine_main  # noqa: E402

OTHER_KEY = "55" * 32


class EnrollmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="enrollment-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "profile"
        self.home.mkdir()
        (self.home / "settings.json").write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
        self.state = self.root / "state"
        self.libraries = []
        for name in ("code", "work"):
            folder = self.root / name
            for repo in ("one", "two") if name == "code" else ("three",):
                subprocess.run(["git", "init", "-q", str(folder / repo)], check=True)
            self.libraries.append(folder)

    def command(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = enroll_machine_main(["--settings-home", str(self.home), *args])
        return code, out.getvalue()

    def app(self):
        return load_fleet_settings(self.home).config("app")

    def test_nothing_is_enrolled_without_consent(self):
        with patch("sys.stdin.isatty", return_value=False):
            code, _out = self.command("add", str(self.libraries[0]))
        self.assertEqual(code, 2)
        self.assertIsNone(self.app())

    def test_the_notice_says_exactly_what_will_be_inventoried(self):
        notice = enrollment.inventory_notice([self.libraries[0]])
        self.assertIn(str(self.libraries[0].resolve()), notice)
        self.assertIn("Nothing outside these folders", notice)

    def test_several_libraries_and_no_overlap(self):
        self.assertEqual(self.command("add", str(self.libraries[0]), "--yes")[0], 0)
        self.assertEqual(self.command("add", str(self.libraries[1]), "--yes")[0], 0)
        self.assertEqual(self.app()["roots"], [str(path.resolve()) for path in self.libraries])
        with self.assertRaisesRegex(ValueError, "overlap"):
            enrollment.add_libraries([self.libraries[0] / "one"], home=self.home)
        self.assertEqual(self.command("remove", str(self.libraries[1]))[0], 0)
        with self.assertRaisesRegex(ValueError, "at least one library"):
            enrollment.remove_library(self.libraries[0], home=self.home)

    def test_a_machine_only_enrollment_runs_with_no_fleet(self):
        enrollment.add_libraries([self.libraries[0]], home=self.home)
        config = load_saved(self.state, home=self.home)
        self.assertEqual(config["transports"], {})
        self.assertEqual(config["presentation"], {"face": "web", "web": "loopback"})

    def test_finding_libraries_needs_consent_and_enrolls_nothing(self):
        with patch("sys.stdin.isatty", return_value=False):
            self.assertEqual(self.command("find", str(self.root))[0], 2)
        code, out = self.command("find", str(self.root), "--yes")
        self.assertEqual(code, 0)
        self.assertIn(str(self.libraries[0].resolve()), out)
        found = {item["path"]: item["repositories"] for item in enrollment.find_libraries([self.root])}
        self.assertEqual(found[str(self.libraries[0].resolve())], 2)
        self.assertIsNone(self.app(), "looking must never enroll")

    def test_presentation_is_validated_and_drives_what_app_serves(self):
        enrollment.add_libraries([self.libraries[0]], home=self.home)
        with self.assertRaisesRegex(ValueError, "web face needs the web view"):
            enrollment.set_presentation(face="web", web="off", home=self.home)
        enrollment.set_presentation(face="window", web="off", home=self.home)
        _config, serve, choice = presentation(self.state, self.home)
        self.assertIsNone(serve, "web off: nothing is served")
        self.assertEqual(choice, {"face": "window", "web": "off"})
        _config, serve, choice = presentation(self.state, self.home, face="web", web="loopback")
        self.assertIsNotNone(serve, "a run's override turns the web view on")

    def test_a_fleet_key_is_replaced_only_before_anything_was_shared(self):
        enrollment.add_libraries([self.libraries[0]], home=self.home)
        replace_fleet_secret(OTHER_KEY, home=self.home)
        self.assertEqual(self.app()["fleet_secret"], OTHER_KEY)
        synced = self.root / "synced"
        synced.mkdir()
        with redirect_stdout(io.StringIO()):
            fleet_main(["--settings-home", str(self.home), "--config-dir", str(self.state),
                        "transports", "--folder", str(synced)])
        with self.assertRaisesRegex(SettingsError, "leave it first"):
            replace_fleet_secret("66" * 32, home=self.home)
        with redirect_stdout(io.StringIO()):
            command_leave(self.state, home=self.home)
        self.assertEqual(self.app()["transports"], {})
        replace_fleet_secret("66" * 32, home=self.home)
        self.assertEqual(self.app()["roots"], [str(self.libraries[0].resolve())],
                         "leaving the fleet keeps the machine's libraries")

    def test_guided_fleet_setup_joins_an_enrolled_machine(self):
        from Elaborate._fleet.cli import guided_fleet_setup

        enrollment.add_libraries([self.libraries[0]], home=self.home)
        synced = self.root / "synced"
        synced.mkdir()
        answers = ["", str(synced), ""]  # new fleet, this synced folder, keep sharing names
        readiness = {"git": True, "github": False, "tailnet": False, "dashboard": True,
                     "port": 8760, "folders": []}
        with patch("builtins.input", side_effect=answers), redirect_stdout(io.StringIO()), \
                patch("Elaborate._fleet.cli.preflight_state", return_value=readiness):
            self.assertEqual(guided_fleet_setup(self.state, home=self.home), 0)
        config = self.app()
        self.assertEqual(config["transports"]["folder"]["path"], str(synced.resolve()))
        self.assertTrue(config["share_names"])
        self.assertEqual(config["roots"], [str(self.libraries[0].resolve())],
                         "joining a fleet never changes the machine's libraries")

    def test_fleet_setup_requires_an_enrolled_machine(self):
        with redirect_stdout(io.StringIO()), patch("sys.stderr", new_callable=io.StringIO) as errors:
            code = fleet_main(["--settings-home", str(self.home), "--config-dir", str(self.state), "setup"])
        self.assertEqual(code, 2)
        self.assertIn("enroll_machine.py add", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
