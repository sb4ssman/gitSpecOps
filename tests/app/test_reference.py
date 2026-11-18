"""The page's Reference (2026-11-17): the catalog by layer, each manual, the documents.

Pins: every gitso command is in exactly one layer; a manual and a document are answered by
their listed names only; anything else, a path included, is refused.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

import gitso  # noqa: E402
from App._web.reference import reference  # noqa: E402


class ReferenceTests(unittest.TestCase):
    def test_the_catalog_holds_every_command_once_by_layer(self):
        catalog = reference({})
        listed = [entry["command"] for layer in catalog["layers"] for entry in layer["commands"]]
        self.assertEqual(sorted(listed), sorted(command.name for command in gitso.COMMANDS))
        self.assertEqual(catalog["layers"][0]["id"], "Basic")
        self.assertIn("README", [doc["id"] for doc in catalog["documents"]])
        self.assertTrue(all(item["url"].startswith("https://") for item in catalog["links"]))

    def test_a_manual_and_a_document_are_read_by_their_listed_names(self):
        self.assertIn("Fetch", reference({"command": "fetch"})["text"])
        self.assertTrue(reference({"document": "README"})["text"])

    def test_anything_else_is_refused(self):
        for bad in ({"document": "../settings.json"}, {"document": "C:/Windows/win.ini"}, {"command": "rm"},
                    {"path": "x"}, {"command": "fetch", "document": "README"}, []):
            with self.assertRaises(ValueError, msg=bad):
                reference(bad)


if __name__ == "__main__":
    unittest.main()
