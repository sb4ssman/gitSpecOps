"""Where each repository lives (the user, 2026-11-15): reports carry the library's and the folder's
names, never a path; the page groups by library and folder; `gitso machine map` draws the tree.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Elaborate._fleet.display import build_display  # noqa: E402
from Elaborate._fleet.peer import PEER_POLL_SECONDS, poll_seconds  # noqa: E402
from Special._sync.folder_map import built_in_map, mapper_map  # noqa: E402
from Special._sync.manifest import (build_manifest, fleet_id_for, merge_checkouts, place_of,  # noqa: E402
                                    validate_manifest, without_names)

FLEET = fleet_id_for("33" * 32)
NAMES = {"a" * 32: {"host": "github.com", "owner": "example", "name": "shared"}}


def repo(place, head="1" * 40):
    return {"repo_id": "a" * 32, "branch_id": "d" * 16, "has_upstream": True, "upstream_observed_at": None,
            "ahead": 0, "behind": 0, "staged": 0, "unstaged": 0, "untracked": 0, "stashes": 0,
            "operation": None, "branch": "main", "head": head, "place": place}


def report(machine, place):
    return {"manifest": build_manifest(FLEET, machine, machine, [repo(place)], carries_names=True),
            "names": NAMES, "issues": []}


class PlaceTests(unittest.TestCase):
    def test_a_place_is_the_library_and_folder_names_only(self):
        library = Path(tempfile.gettempdir()) / "Library"
        self.assertEqual(place_of(library / "Org" / "repo", [library]), {"library": "Library", "folder": "Org"})
        self.assertEqual(place_of(library / "repo", [library]), {"library": "Library", "folder": ""})
        self.assertEqual(place_of(library / "Org" / "deeper" / "repo", [library])["folder"], "Org")
        self.assertIsNone(place_of(Path(tempfile.gettempdir()) / "elsewhere" / "repo", [library]))

    def test_the_innermost_library_wins(self):
        outer = Path(tempfile.gettempdir()) / "Outer"
        inner = outer / "Inner"
        self.assertEqual(place_of(inner / "Org" / "repo", [outer, inner]), {"library": "Inner", "folder": "Org"})

    def test_a_path_is_refused_as_a_place(self):
        bad = build_manifest(FLEET, "m", "m", [repo({"library": "Lib", "folder": "Org"})], carries_names=True)
        bad["repositories"][0]["place"] = {"library": "C:\\Users", "folder": "Org"}
        with self.assertRaises(ValueError):
            validate_manifest(bad)

    def test_a_connection_without_names_carries_no_place(self):
        named = build_manifest(FLEET, "m", "m", [repo({"library": "Lib", "folder": "Org"})], carries_names=True)
        self.assertNotIn("place", without_names(named)["repositories"][0])

    def test_two_checkouts_keep_a_place_only_when_they_agree(self):
        same = merge_checkouts([repo({"library": "L", "folder": "A"}), repo({"library": "L", "folder": "A"})])
        apart = merge_checkouts([repo({"library": "L", "folder": "A"}), repo({"library": "L", "folder": "B"})])
        self.assertEqual(same[0]["place"], {"library": "L", "folder": "A"})
        self.assertIsNone(apart[0]["place"])


class PlaceGroupTests(unittest.TestCase):
    def test_the_page_gets_a_group_for_each_library_folder(self):
        document = build_display([report("one", {"library": "Github", "folder": "Archive"}),
                                  report("two", {"library": "Github", "folder": "Archive"})], FLEET)
        self.assertEqual([(g["id"], g["label"], g["host"], g["count"]) for g in document["place_groups"]],
                         [("place/Github/Archive", "Archive", "Github", 1)])
        self.assertEqual(document["rows"][0]["place_id"], "place/Github/Archive")

    def test_a_repository_without_a_place_is_grouped_as_not_shared(self):
        document = build_display([report("one", None)], FLEET)
        self.assertEqual(document["place_groups"][0]["label"], "Folder not shared")


class PollIntervalTests(unittest.TestCase):
    def test_peers_ask_every_five_minutes_unless_chosen(self):
        self.assertEqual(PEER_POLL_SECONDS, 300)
        self.assertEqual(poll_seconds({"transports": {"tailnet": {"port": 8765}}}), 300)
        self.assertEqual(poll_seconds({"transports": {"tailnet": {"port": 8765, "seconds": 60}}}), 60)


class FolderMapTests(unittest.TestCase):
    def test_the_map_shows_libraries_folders_and_repositories_only(self):
        root = Path(tempfile.gettempdir()) / "Library"
        lines = built_in_map(root, {root / "Org" / "a": "clean", root / "Org" / "b": "dirty 1: COMMIT",
                                    root / "Org" / "Deep" / "c": "clean", root / "loose": "clean"})
        self.assertEqual(lines, [str(root), "├── loose  ✓ clean", "└── Org/  (3, 1 needs something)",
                                 "    ├── a  ✓ clean", "    ├── b  ⚠ dirty 1: COMMIT",
                                 "    └── Deep/  (1, all clean)", "        └── c  ✓ clean"])

    def test_the_mappers_tree_gets_each_repositorys_state(self):
        root = Path(tempfile.gettempdir()) / "Library"
        tree = ("# Library\n\n```\n📁 Library/\n├── 📁 Org/\n│   ├── 📁 a/\n│   └── notes.txt\n"
                "└── 📁 loose/\n```\n")
        with tempfile.TemporaryDirectory() as folder:
            mapper = Path(folder) / "mapper.py"
            mapper.write_text(f"import sys\nsys.stdout.reconfigure(encoding='utf-8')\nprint({tree!r})\n",
                              encoding="utf-8")
            lines = mapper_map(mapper, root, 3, {root / "Org" / "a": "clean", root / "loose": "behind 2: PULL"})
        self.assertEqual(lines, ["📁 Library/", "├── 📁 Org/", "│   ├── 📁 a/  ✓ clean", "│   └── notes.txt",
                                 "└── 📁 loose/  ⚠ behind 2: PULL"])


if __name__ == "__main__":
    unittest.main()
