"""The mark (hub and ring): geometry, SVG, the two signals in the display document, the tray.

Pins: the mark fills its square without leaving it at every size and state; unknown states are
refused, including on the /v1/mark.svg route; "this machine" and "the fleet" are independent;
the fleet is "none" until a fleet is joined; the tray tooltip fits Windows' 127 characters.
"""
import os
import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from App._mark.geometry import STATES, Dot, Line, mark  # noqa: E402
from App._mark.svg import mark_response, svg  # noqa: E402
from App._tray.model import snapshot_from_display  # noqa: E402
from Elaborate._fleet.display import mark_state  # noqa: E402


def machine(mid, freshness="current", count=2):
    return {"id": mid, "label": mid.upper(), "freshness": freshness, "repository_count": count}


def row(cells):
    return {"cells": {mid: {"present": True, "state": state} for mid, state in cells.items()}}


class MarkTests(unittest.TestCase):
    def test_the_mark_fills_its_square_and_never_leaves_it(self):
        for size in (16, 24, 32, 256):
            drawing = mark("ok", "attention", size)
            xs, ys = [], []
            for item in drawing.items:
                if isinstance(item, Line):
                    pad = (item.width + 1.6 * drawing.scale) / 2
                    xs += [item.x1 - pad, item.x2 + pad, item.x1 + pad, item.x2 - pad]
                    ys += [item.y1 - pad, item.y2 + pad, item.y1 + pad, item.y2 - pad]
                else:
                    self.assertIsInstance(item, Dot)
                    pad = item.r + 0.8 * drawing.scale
                    xs += [item.x - pad, item.x + pad]
                    ys += [item.y - pad, item.y + pad]
            self.assertGreaterEqual(min(xs + ys), -0.01, size)
            self.assertLessEqual(max(xs + ys), 32.01, size)
            self.assertGreater(max(max(xs) - min(xs), max(ys) - min(ys)), 30.5, f"{size}: fills the square")

    def test_every_state_pair_draws_and_parses(self):
        for m in STATES:
            for f in STATES:
                for size in (16, 64):
                    ElementTree.fromstring(svg(m, f, size))
        hub = mark("error", "ok").items[-1]
        self.assertEqual((hub.state, mark("error", "ok").items[0].state), ("error", "ok"), "two independent parts")

    def test_unknown_states_and_sizes_are_refused(self):
        with self.assertRaises(ValueError):
            mark("green", "ok")
        self.assertEqual(mark_response({"machine": ["ok"], "fleet": ["none"], "size": ["32"]})[0], 200)
        for bad in ({"machine": ["<script>"]}, {"fleet": ["red"]}, {"size": ["9999"]}, {"size": ["x"]}):
            self.assertEqual(mark_response(bad)[0], 400, bad)

    def test_this_machine_and_the_fleet_are_separate_signals(self):
        rows = [row({"me": "dirty", "lap": "synced"}), row({"me": "synced", "lap": "synced"})]
        alone = mark_state(rows, [machine("me")], [], {"machine_id": "me"})
        self.assertEqual(alone["machine"]["state"], "attention")
        self.assertEqual(alone["fleet"]["state"], "none", "no fleet joined")
        joined = {"machine_id": "me", "transport_config": {"folder": {"path": "x"}}}
        waiting = mark_state(rows, [machine("me")], [], joined)
        self.assertEqual(waiting["fleet"]["state"], "starting")
        fleet = mark_state(rows, [machine("me"), machine("lap")], [], joined)
        self.assertEqual((fleet["machine"]["state"], fleet["fleet"]["state"]), ("attention", "ok"))
        stale = mark_state(rows, [machine("me"), machine("lap", "stale")], [], joined)
        self.assertEqual(stale["fleet"]["state"], "attention")
        self.assertIn("LAP: not reporting", stale["fleet"]["text"])
        clean = mark_state([row({"me": "synced"})], [machine("me", count=1)], [], {"machine_id": "me"})
        self.assertEqual(clean["machine"]["state"], "ok")
        unknown = mark_state(rows, [machine("me")], [], {})
        self.assertEqual(unknown["machine"]["state"], "starting", "a view without a machine id")

    def test_the_tray_reads_both_signals_and_keeps_the_tooltip_short(self):
        document = {"contract": {"name": "gitspecops.fleet.display", "version": 1},
                    "summary": {"repositories": 168, "attention": 44, "machines": 1},
                    "mark": {"machine": {"state": "attention", "text": "44 of 168 need attention, 2 problems"},
                             "fleet": {"state": "none", "text": "not in a fleet"}}}
        snapshot = snapshot_from_display(document, "u", "prime")
        self.assertEqual((snapshot.machine, snapshot.fleet), ("attention", "none"))
        self.assertLessEqual(len(snapshot.tooltip()), 127)
        self.assertIn("Fleet: not in a fleet", snapshot.tooltip())
        older = snapshot_from_display({**document, "mark": None}, "u", "prime")
        self.assertEqual((older.machine, older.fleet), ("attention", "none"), "a peer from before the mark")

    def test_working_frames_light_from_the_outside_in(self):
        from App._mark.geometry import FRAMES
        lit_parts = []
        for frame in range(len(FRAMES)):
            lit_parts.append({item.part for item in mark("ok", "attention", 32, frame).items if item.lit})
        self.assertEqual(lit_parts, [set(), {"node"}, {"node", "rim"}, {"node", "rim", "spoke"},
                                     {"node", "rim", "spoke", "hub"}])
        animated = svg("starting", "none", 64, working=True)
        ElementTree.fromstring(animated)
        self.assertIn("@keyframes w-hub", animated)
        self.assertEqual(mark_response({"working": ["1"]})[0], 200)
        self.assertEqual(mark_response({"working": ["yes"]})[0], 400)

    def test_the_tray_shows_what_the_peer_is_doing(self):
        document = {"contract": {"name": "gitspecops.fleet.display", "version": 1},
                    "summary": {"repositories": 168, "attention": 0, "machines": 1},
                    "mark": {"machine": {"state": "ok", "text": "168 repositories in sync"},
                             "fleet": {"state": "none", "text": "not in a fleet"}},
                    "activity": {"phase": "fetching", "text": "fetching remotes (read-only): 168 repositories"}}
        busy = snapshot_from_display(document, "u", "prime")
        self.assertTrue(busy.working)
        self.assertTrue(busy.tooltip().startswith("gitSpecOps: fetching remotes"))
        self.assertLessEqual(len(busy.tooltip()), 127)
        calm = snapshot_from_display({**document, "activity": {"phase": "idle", "text": "watching 168"}}, "u", "prime")
        self.assertFalse(calm.working)

    def test_qt_paints_the_mark(self):
        try:
            import PySide6  # noqa: F401
        except ImportError:
            self.skipTest("PySide6 not installed")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6 import QtGui

        from App._mark.qt import icon, pixmap
        app = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([])
        image = pixmap("ok", "attention", 16).toImage()
        self.assertGreater(image.pixelColor(8, 8).alpha(), 0, "the hub is painted")
        self.assertFalse(icon("starting", "none").isNull())
        del app


if __name__ == "__main__":
    unittest.main()
