"""`gitso machine check` reads the library folders setup keeps, and checks secrets only when asked
(2026-11-15: setup's first scan found "no folders", and the secret check took over an hour)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT, setup  # noqa: E402

setup()

from Special._sync.commands import _root_specs  # noqa: E402


def args(**overrides):
    return SimpleNamespace(**{"root": None, "recursive_root": None, "recursive": False, **overrides})


class LibraryFoldersTests(unittest.TestCase):
    def test_audit_reports_reachable_repositories_and_unavailable_scope(self):
        from Special._sync.enrollment import add_libraries

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            home, reachable, unavailable = (root / name for name in ("profile", "local", "external"))
            unavailable.mkdir()
            checkout = reachable / "example"
            subprocess.run(["git", "init", "-q", str(checkout)], check=True)
            add_libraries([reachable, unavailable], home=home)
            unavailable.rmdir()
            done = subprocess.run([sys.executable, "-B", str(ROOT / "gitso.py"), "machine", "audit",
                                   "--settings-home", str(home), "--json"],
                                  capture_output=True, text=True, encoding="utf-8", timeout=45)
            report = json.loads(done.stdout)
            self.assertNotEqual(done.returncode, 0)
            rows = {row["name"]: row["findings"] for row in report["repositories"]}
            self.assertIn("no origin", rows["example"])
            self.assertIn("nothing", rows["external"][0])

    def test_the_app_library_folders_are_read_recursively_when_nothing_else_is_saved(self):
        specs, source = _root_specs(args(), None, {"roots": ["/library"]})
        self.assertEqual([(str(spec.path), spec.recursive) for spec in specs], [(str(Path("/library")), True)])
        self.assertEqual(source, "library folders on this machine")

    def test_folders_named_on_the_command_line_come_first(self):
        specs, source = _root_specs(args(root=["/elsewhere"]), None, {"roots": ["/library"]})
        self.assertEqual(source, "command line")
        self.assertEqual([str(spec.path) for spec in specs], [str(Path("/elsewhere"))])

    def test_nothing_saved_anywhere_is_still_nowhere(self):
        self.assertEqual(_root_specs(args(), None, None), ([], "nowhere"))

    def test_the_secret_check_is_asked_for_not_default(self):
        from Special._sync import commands
        captured = {}

        def run(_name, _function, parser, argv):
            captured["args"] = parser.parse_args(argv)
            return 0
        original = commands._run
        commands._run = run
        try:
            commands.suggest_sync_main([])
            self.assertFalse(captured["args"].security)
            commands.suggest_sync_main(["--security"])
            self.assertTrue(captured["args"].security)
        finally:
            commands._run = original


if __name__ == "__main__":
    unittest.main()
