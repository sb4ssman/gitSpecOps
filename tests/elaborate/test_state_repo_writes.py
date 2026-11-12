"""The GitHub state repository is written only when something changed, never as a heartbeat.

Pins (the user, 2026-11-12): every write there is a commit kept forever, so unchanged state is
not re-sent; a change waits for the transport's slot (30 minutes by default) and is written
once. A synced folder keeps its free heartbeat. No network: the transports are fakes.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Elaborate._fleet.peer import TransportPublisher  # noqa: E402


class Fake:
    def __init__(self):
        self.writes = []

    def write_own_manifest(self, machine_id, manifest, compress=False):
        self.writes.append(manifest["observed_at"])
        return "ok"


class StateRepoWrites(unittest.TestCase):
    def setUp(self):
        self.clock = [0.0]
        self.publisher = TransportPublisher({"folder": {"path": ".", "seconds": 300},
                                             "repo": {"name": "someone/state", "seconds": 1800}},
                                            clock=lambda: self.clock[0])
        self.folder, self.repo = Fake(), Fake()
        for entry in self.publisher.entries:
            entry["transport"] = self.folder if entry["name"] == "folder" else self.repo

    def publish(self, at, changed, stamp):
        self.clock[0] = at
        self.publisher.publish({"machine_id": "m", "observed_at": stamp}, changed, log=lambda _m: None)

    def test_unchanged_state_is_never_committed_again(self):
        self.publish(0, True, "first")
        for minute in range(31, 600, 30):  # ten hours of nothing changing
            self.publish(minute * 60, False, f"quiet {minute}")
        self.assertEqual(self.repo.writes, ["first"], "no heartbeat commits")
        self.assertGreater(len(self.folder.writes), 10, "the synced folder keeps its heartbeat")

    def test_a_change_waits_for_the_slot_and_is_written_once(self):
        self.publish(0, True, "first")
        self.publish(100, True, "changed early")
        self.assertEqual(self.repo.writes, ["first"], "not before the 30-minute slot")
        self.publish(1700, True, "changed again")
        self.clock[0] = 1800
        self.publisher.flush(log=lambda _m: None)
        self.assertEqual(self.repo.writes, ["first", "changed again"], "the newest state, once")
        self.clock[0] = 3600
        self.publisher.flush(log=lambda _m: None)
        self.assertEqual(len(self.repo.writes), 2, "nothing left to write")

    def test_a_failed_write_waits_for_the_next_slot(self):
        def offline(*_args, **_kwargs):
            raise OSError("no network")
        self.repo.write_own_manifest = offline
        self.publish(0, True, "first")
        self.repo.write_own_manifest = Fake.write_own_manifest.__get__(self.repo)
        self.clock[0] = 60
        self.publisher.flush(log=lambda _m: None)
        self.assertEqual(self.repo.writes, [], "no retry before the slot")
        self.clock[0] = 1800
        self.publisher.flush(log=lambda _m: None)
        self.assertEqual(self.repo.writes, ["first"], "delivered once GitHub is reachable again")


if __name__ == "__main__":
    unittest.main()
