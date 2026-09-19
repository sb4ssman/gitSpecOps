"""The enabled medium tier captures after events and proves a second machine can read it."""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup

setup("sync")
from fleet_config import new_config, validate
from recovery_runtime import RecoveryRuntime
from snapshot_store import SnapshotStore

SECRET = "55" * 32
REPO_ID = "a" * 32


def git(path, *args):
    result = subprocess.run(["git", *args], cwd=path, capture_output=True, text=True, check=False)
    if result.returncode:
        raise AssertionError(result.stderr)


class Observer:
    def __init__(self, repository):
        self.repository = repository

    def local_repositories(self):
        return {REPO_ID: self.repository}

    def namespaces(self):
        return {REPO_ID: "example.invalid/team"}


def test_event_capture_is_acknowledged_by_another_peer():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        repository, recovery = root / "library" / "checkout", root / "snapshots"
        repository.mkdir(parents=True)
        recovery.mkdir()
        git(repository, "init", "-q", "-b", "main")
        git(repository, "config", "user.email", "test@example.invalid")
        git(repository, "config", "user.name", "Test")
        git(repository, "config", "core.autocrlf", "false")
        (repository / "tracked.txt").write_text("base\n")
        git(repository, "add", "tracked.txt")
        git(repository, "commit", "-qm", "base")
        (repository / "tracked.txt").write_text("saved\n")
        (repository / "new.txt").write_text("untracked\n")

        config = new_config("machine-a", "A", [root / "library"], SECRET)
        config["baskets"]["capture"] = {"mode": "all"}
        config["recovery"] = {"location": str(recovery), "confirmed": True, "policies": {}}
        validate(config)
        source = RecoveryRuntime(config, Observer(repository), log=lambda *_: None)
        assert source.enabled and source.capture_paths([repository]) == 1
        version = SnapshotStore(recovery, "machine-a").versions()[0]
        assert source.store.status(REPO_ID, version.version) == "written"

        peer = {**config, "machine_id": "machine-b", "label": "B"}
        receiver = RecoveryRuntime(peer, Observer(repository), log=lambda *_: None)
        assert receiver.acknowledge_available() == 1
        assert source.store.status(REPO_ID, version.version) == "recoverable elsewhere"


def main():
    test_event_capture_is_acknowledged_by_another_peer()
    print("ALL-RECOVERY-RUNTIME-TESTS-PASS")


if __name__ == "__main__":
    main()
