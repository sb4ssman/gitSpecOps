"""Snapshot store: confined writes, bounded storage, honest durability states."""
from datetime import datetime, timedelta, timezone
import gzip
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup

setup("sync")
import snapshot_store
from capture import Bundle
from snapshot_store import SnapshotStore, StoreRefused, validate_location

START = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
REPO_A = "a" * 32
REPO_B = "b" * 32


class Clock:
    def __init__(self):
        self.now = START

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)


def bundle(machine="machine-a", repo=REPO_A, text="change", at=START):
    return Bundle(repo_id=repo, machine_id=machine, captured_at=at.isoformat(),
                  base_commit="c" * 40, branch="main", staged_patch=f"+{text}\n",
                  unstaged_patch="").to_dict()


def refused(call, expect=""):
    try:
        call()
    except StoreRefused as exc:
        assert expect in str(exc), f"expected {expect!r} in {exc}"
        return
    raise AssertionError("expected a refusal")


def test_write_read_round_trip_and_skip_identical():
    with tempfile.TemporaryDirectory() as temp:
        clock = Clock()
        store = SnapshotStore(temp, "machine-a", clock=clock)
        result = store.write(bundle())
        assert result["written"]
        body = store.read("machine-a", REPO_A, result["version"])
        assert body["staged_patch"] == "+change\n"

        # Recapturing identical content later writes nothing: a timestamp is not new work.
        clock.advance(minutes=5)
        again = store.write(bundle(at=clock.now))
        assert not again["written"] and again["version"] == result["version"]
        assert len(store.versions()) == 1

        clock.advance(minutes=5)
        assert store.write(bundle(text="more", at=clock.now))["written"]
        assert len(store.versions()) == 2


def test_writes_are_confined_to_own_machine():
    with tempfile.TemporaryDirectory() as temp:
        store = SnapshotStore(temp, "machine-a", clock=Clock())
        refused(lambda: store.write(bundle(machine="machine-b")), "only store its own")
        refused(lambda: SnapshotStore(temp, "../escape"), "invalid machine id")
        refused(lambda: store.read("machine-a", "../../etc", "20260101T120000Z-" + "0" * 16),
                "invalid repository id")
        refused(lambda: store.read("machine-a", REPO_A, "../../x"), "invalid snapshot version")

        other = SnapshotStore(temp, "machine-b", clock=Clock())
        written = other.write(bundle(machine="machine-b"))
        plan = {"machine_id": "machine-b", "versions": [[REPO_A, written["version"]]]}
        refused(lambda: store.delete(plan), "only remove this machine's")
        assert len(other.versions()) == 1, "one machine can never delete another's copy"


def test_untrusted_bundles_are_verified_before_use():
    with tempfile.TemporaryDirectory() as temp:
        store = SnapshotStore(temp, "machine-a", clock=Clock())
        version = store.write(bundle())["version"]
        path = store._bundle_path("machine-a", REPO_A, version)

        body = json.loads(gzip.decompress(path.read_bytes()))
        body["staged_patch"] = "+tampered\n"
        path.write_bytes(gzip.compress(json.dumps(body).encode()))
        refused(lambda: store.read("machine-a", REPO_A, version), "checksum does not match")

        path.write_bytes(b"\x1f\x8b not really gzip")
        refused(lambda: store.read("machine-a", REPO_A, version), "corrupt or truncated")

        # A valid bundle copied under another repository's directory is not believed there.
        genuine = gzip.compress(json.dumps(bundle()).encode())
        misplaced = store._bundle_path("machine-a", REPO_B, version)
        misplaced.parent.mkdir(parents=True)
        misplaced.write_bytes(genuine)
        refused(lambda: store.read("machine-a", REPO_B, version), "does not belong")

        # A decompression bomb is bounded rather than allocated.
        bomb = gzip.compress(b" " * (snapshot_store.MAX_DECODED_BYTES + 10))
        path.write_bytes(bomb)
        refused(lambda: store.read("machine-a", REPO_A, version), "size a bundle may decode")


def test_superseded_versions_are_pruned_but_newest_survives():
    with tempfile.TemporaryDirectory() as temp:
        clock = Clock()
        store = SnapshotStore(temp, "machine-a", clock=clock)
        pruned = []
        for index in range(snapshot_store.MAX_VERSIONS_PER_REPO + 3):
            clock.advance(seconds=1)
            result = store.write(bundle(text=f"edit {index}", at=clock.now))
            pruned += result["pruned"]
        versions = store.versions(repo_id=REPO_A)
        assert len(versions) == snapshot_store.MAX_VERSIONS_PER_REPO
        assert len(pruned) == 3, "pruning is reported to the caller, never silent"
        newest = store.read("machine-a", REPO_A, versions[-1].version)
        assert "edit 12" in newest["staged_patch"]


def test_retention_expires_and_warns_before_the_last_copy_goes():
    with tempfile.TemporaryDirectory() as temp:
        clock = Clock()
        store = SnapshotStore(temp, "machine-a", clock=clock)
        store.write(bundle())
        clock.advance(days=6, hours=12)
        warnings = store.expiring(within=timedelta(days=1))
        assert [v.repo_id for v in warnings] == [REPO_A], "the last copy must warn before expiry"
        clock.advance(days=1)
        removed = store.expire()
        assert len(removed) == 1 and store.versions() == []


def test_quota_refuses_rather_than_deleting_a_last_copy():
    with tempfile.TemporaryDirectory() as temp:
        clock = Clock()
        store = SnapshotStore(temp, "machine-a", clock=clock)
        original = snapshot_store.MAX_STORE_BYTES
        try:
            store.write(bundle(repo=REPO_A))
            one = store.used_bytes()
            snapshot_store.MAX_STORE_BYTES = one + one // 2  # room for one bundle, not two
            clock.advance(seconds=1)
            refused(lambda: store.write(bundle(repo=REPO_B, at=clock.now)), "store is full")
            assert [v.repo_id for v in store.versions()] == [REPO_A], \
                "the only copy of another repository must survive a full store"

            # A superseded version, by contrast, is fair game to make room.
            snapshot_store.MAX_STORE_BYTES = one * 2 + one // 2
            clock.advance(seconds=1)
            store.write(bundle(repo=REPO_A, text="newer", at=clock.now))
            clock.advance(seconds=1)
            result = store.write(bundle(repo=REPO_B, at=clock.now))
            assert result["written"] and len(result["pruned"]) == 1
            assert {v.repo_id for v in store.versions()} == {REPO_A, REPO_B}
        finally:
            snapshot_store.MAX_STORE_BYTES = original


def test_durability_needs_an_acknowledgement_from_another_machine():
    with tempfile.TemporaryDirectory() as temp:
        source = SnapshotStore(temp, "machine-a", clock=Clock())
        receiver = SnapshotStore(temp, "machine-b", clock=Clock())
        version = source.write(bundle())["version"]

        assert source.status(REPO_A, version) == "written", "a folder write is not durability"
        refused(lambda: source.acknowledge("machine-a", REPO_A, version), "its own snapshot")

        receiver.acknowledge("machine-a", REPO_A, version)
        assert source.acknowledgements(REPO_A, version) == ["machine-b"]
        assert source.status(REPO_A, version) == "recoverable elsewhere"

        # An acknowledgement of different content does not count.
        ack = receiver._ack_path("machine-b", "machine-a", REPO_A, version)
        record = json.loads(ack.read_text())
        record["bundle_checksum"] = "0" * 64
        ack.write_text(json.dumps(record))
        assert source.status(REPO_A, version) == "written"


def test_deletion_is_previewed_and_exact():
    with tempfile.TemporaryDirectory() as temp:
        clock = Clock()
        store = SnapshotStore(temp, "machine-a", clock=clock)
        store.write(bundle(repo=REPO_A))
        clock.advance(seconds=1)
        store.write(bundle(repo=REPO_B, at=clock.now))
        plan = store.plan_deletion(REPO_A)
        assert plan["count"] == 1 and plan["bytes"] > 0 and "cannot erase" in plan["note"]
        clock.advance(seconds=1)
        store.write(bundle(repo=REPO_A, text="after preview", at=clock.now))
        removed = store.delete(plan)
        assert len(removed) == 1, "a plan removes only what it listed"
        assert {v.repo_id for v in store.versions()} == {REPO_A, REPO_B}


def test_location_rules():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        library, sync, status = root / "library", root / "sync", root / "sync" / "status"
        for folder in (library, status):
            folder.mkdir(parents=True)
        (library / "inside").mkdir()

        refused(lambda: validate_location(library / "inside", roots=[library]), "overlaps")
        refused(lambda: validate_location(root, roots=[library]), "overlaps")
        refused(lambda: validate_location(root / "missing"), "existing folder")

        warnings = validate_location(sync, status_folder=status, roots=[library])
        assert any("status manifests" in w for w in warnings)
        assert any("shared" in w for w in warnings), "sharing is always asked about"
        separate = root / "elsewhere"
        separate.mkdir()
        assert not any("status manifests" in w
                       for w in validate_location(separate, status_folder=status))


def main():
    test_write_read_round_trip_and_skip_identical()
    test_writes_are_confined_to_own_machine()
    test_untrusted_bundles_are_verified_before_use()
    test_superseded_versions_are_pruned_but_newest_survives()
    test_retention_expires_and_warns_before_the_last_copy_goes()
    test_quota_refuses_rather_than_deleting_a_last_copy()
    test_durability_needs_an_acknowledgement_from_another_machine()
    test_deletion_is_previewed_and_exact()
    test_location_rules()
    print("ALL-SNAPSHOT-STORE-TESTS-PASS")


if __name__ == "__main__":
    main()
