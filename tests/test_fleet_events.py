"""Native idle watcher and targeted repository refresh checks."""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "git-sync-suggester"))
from fleet_events import NativeEvents
from fleet_observer import IncrementalObserver


def git(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp) / "library"
        repo = root / "example"
        repo.mkdir(parents=True)
        git(repo, "init")
        git(repo, "remote", "add", "origin", "https://github.com/example/project.git")
        config = {"roots": [str(root)], "fleet_secret": "22" * 32,
                  "machine_id": "test-machine", "label": "Test machine"}
        observer = IncrementalObserver(config)
        assert observer.inventory() == 1
        initial = observer.report()
        assert initial["manifest"]["repositories"][0]["untracked"] == 0

        with NativeEvents([root]) as events:
            (repo / "unfinished.txt").write_text("private local work\n", encoding="utf-8")
            changed = events.wait(timeout=3, debounce=0.05)
            assert changed, "native watcher did not report a file creation"
            assert observer.affected_repositories(changed) == {repo.resolve()}
            assert observer.refresh(changed) == 1
            updated = observer.report()
            assert updated["manifest"]["repositories"][0]["untracked"] == 1
            assert events.wait(timeout=0.05, debounce=0) == set()

    print("ALL-FLEET-EVENT-TESTS-PASS")


if __name__ == "__main__":
    main()
