"""docs/COMMANDS.md is exactly what the command headers say: change a header, regenerate the page."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from _build import command_docs  # noqa: E402


class CommandDocsTests(unittest.TestCase):
    def test_the_page_matches_the_headers(self):
        on_disk = command_docs.TARGET.read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertEqual(on_disk, command_docs.render(),
                         "docs/COMMANDS.md is stale: run python _build/command_docs.py --write")

    def test_every_command_has_a_section(self):
        page = command_docs.render()
        import gitso
        for command in gitso.COMMANDS:
            self.assertIn(f"### {command.name}\n", page)


if __name__ == "__main__":
    unittest.main()
