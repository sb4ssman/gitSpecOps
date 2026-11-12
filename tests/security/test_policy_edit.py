"""Editing the protected-value lists from the web view, on a disposable profile only.

Pins: tightening needs no extra word; loosening needs LOOSEN; matching ignores case; a value to
remove must still be there; other settings survive; an allowance equal to a protected value is
refused by the shared writer.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Special._security._policy_edit import policy_change, policy_view  # noqa: E402


class PolicyEditTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="policy-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.document = {"schema_version": 2,
                         "defaults": {"security": {"never_publish": ["private-marker"], "engines": ["gitleaks"]}}}
        (self.home / "settings.json").write_text(json.dumps(self.document), encoding="utf-8")

    def saved(self):
        return json.loads((self.home / "settings.json").read_text(encoding="utf-8"))

    def test_tightening_needs_no_word_and_ignores_case_duplicates(self):
        view = policy_change(self.home, {"list": "never_publish", "add": ["Firstname", "PRIVATE-MARKER"]})
        self.assertEqual(view["lists"]["never_publish"], ["private-marker", "Firstname"])
        self.assertEqual(self.saved()["defaults"]["security"]["engines"], ["gitleaks"], "other settings survive")

    def test_loosening_needs_the_typed_word(self):
        with self.assertRaisesRegex(ValueError, "type LOOSEN"):
            policy_change(self.home, {"list": "never_publish", "remove": ["private-marker"]})
        with self.assertRaisesRegex(ValueError, "type LOOSEN"):
            policy_change(self.home, {"list": "safe_values", "add": ["St_Something"], "confirm": "loosen"})
        self.assertEqual(policy_view(self.home)["lists"]["never_publish"], ["private-marker"])
        view = policy_change(self.home, {"list": "safe_values", "add": ["St_Something"], "confirm": "LOOSEN"})
        self.assertEqual(view["lists"]["safe_values"], ["St_Something"])
        view = policy_change(self.home, {"list": "safe_values", "remove": ["st_something"]})
        self.assertEqual(view["lists"]["safe_values"], [], "removing an allowance tightens: no word")

    def test_refusals(self):
        for bad in ({"list": "engines", "add": ["x"]}, {"list": "never_publish"}, {"list": "never_publish", "add": [""]},
                    {"list": "never_publish", "add": ["x" * 201]}, {"list": "never_publish", "add": ["x"], "path": "/"}):
            with self.assertRaises(ValueError, msg=bad):
                policy_change(self.home, bad)
        with self.assertRaisesRegex(ValueError, "not in the list"):
            policy_change(self.home, {"list": "never_publish", "remove": ["gone"], "confirm": "LOOSEN"})
        with self.assertRaisesRegex(ValueError, "not saved"):
            policy_change(self.home, {"list": "safe_values", "add": ["Private-Marker"], "confirm": "LOOSEN"})


if __name__ == "__main__":
    unittest.main()
