"""The page's grouping switch (fleet_view.js regroup), run in Node when it is installed.

Library and folder is the default; GitHub owner is the other choice. Every view reads `groups` and
each row's `group_id`, so this one transform is what regroups the list, Security and the map."""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

VIEW = Path(__file__).resolve().parents[2] / "App" / "_web" / "skins" / "_common" / "fleet_view.js"
DATA = {
    "groups": [{"id": "github.com/someone", "label": "someone", "host": "github.com", "count": 2, "attention": 1}],
    "place_groups": [{"id": "place/Github/Archive", "label": "Archive", "host": "Github", "count": 1, "attention": 0},
                     {"id": "place/unknown", "label": "Folder not shared", "host": "Other machines", "count": 1,
                      "attention": 1}],
    "rows": [{"id": "a", "group_id": "github.com/someone", "namespace": "someone", "place_id": "place/Github/Archive",
              "identity": {"host": "github.com"}},
             {"id": "b", "group_id": "github.com/someone", "namespace": "someone", "place_id": "place/unknown",
              "identity": {"host": "github.com"}}],
}


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class RegroupTests(unittest.TestCase):
    def run_node(self, mode):
        script = (f"import {{regroup}} from {json.dumps(VIEW.as_uri())};"
                  f"console.log(JSON.stringify(regroup({json.dumps(DATA)}, {json.dumps(mode)})));")
        done = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True,
                              timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_by_library_and_folder_the_rows_move_into_folder_groups(self):
        data = self.run_node("place")
        self.assertEqual([group["id"] for group in data["groups"]], ["place/Github/Archive", "place/unknown"])
        self.assertEqual([(row["group_id"], row["namespace"], row["group_host"]) for row in data["rows"]],
                         [("place/Github/Archive", "Archive", "Github"),
                          ("place/unknown", "Folder not shared", "Other machines")])

    def test_by_owner_nothing_moves(self):
        data = self.run_node("owner")
        self.assertEqual(data["groups"], DATA["groups"])
        self.assertEqual({row["group_id"] for row in data["rows"]}, {"github.com/someone"})


if __name__ == "__main__":
    unittest.main()
