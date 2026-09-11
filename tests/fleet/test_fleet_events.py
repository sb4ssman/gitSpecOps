"""Native idle watcher and targeted repository refresh checks."""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "git-sync-suggester"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup("sync")

from fleet_events import NativeEvents, ignored_relative
from fleet_observer import IncrementalObserver


def test_ignore_list_applies_below_the_root_only():
    """Regression: a root under an ignored name once discarded every event, silently.

    The user picks the root; only what sits *below* it may be filtered. Runs on every
    platform so the Windows-only failure cannot come back through the Linux suite.
    """
    assert ignored_relative("node_modules/pkg/file.js"), "must ignore below-root caches"
    assert ignored_relative(".venv/lib/thing.py"), "must ignore a below-root virtualenv"
    assert not ignored_relative("example/unfinished.txt"), "ordinary work must pass"
    # These are the names that made the absolute-path test fail on Windows.
    for name in ("AppData", "Library", "env", "venv"):
        assert not ignored_relative(f"{name}-project/src/main.py"), (
            f"a repository merely starting with {name!r} must not be filtered")
    assert not ignored_relative("project/README.md"), "a plain repository file must pass"


def git(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    test_ignore_list_applies_below_the_root_only()
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

            # The property under test is that the watcher falls idle -- no perpetual scanning.
            # It is NOT that the first post-refresh poll is empty: Windows reports the parent
            # directory's own modification as a second, slightly delayed notification, which
            # the production debounce (0.75s) absorbs but this test's deliberately tight 0.05s
            # does not. Let any such trailing notification drain, then require real silence.
            for _ in range(10):
                if not events.wait(timeout=0.2, debounce=0.05):
                    break
            assert events.wait(timeout=0.3, debounce=0) == set(), "watcher never became idle"

    test_new_checkout_is_detected_not_dropped()
    print("ALL-FLEET-EVENT-TESTS-PASS")



def test_new_checkout_is_detected_not_dropped():
    """A repository cloned into the library fires events that map to no known checkout.

    Those events used to be discarded, so a new repository stayed invisible until someone
    remembered to run `fleet rescan`. Detection must notice it; adding it stays explicit.
    """
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp) / "library"
        existing = root / "already-known"
        existing.mkdir(parents=True)
        git(existing, "init")
        git(existing, "remote", "add", "origin", "https://github.com/example/known.git")
        config = {"roots": [str(root)], "fleet_secret": "22" * 32,
                  "machine_id": "test-machine", "label": "Test machine"}
        observer = IncrementalObserver(config)
        assert observer.inventory() == 1

        fresh = root / "freshly-cloned"
        fresh.mkdir()
        git(fresh, "init")
        (fresh / "README.md").write_text("new\n", encoding="utf-8")

        events = {fresh / "README.md", fresh / ".git" / "HEAD"}
        assert observer.affected_repositories(events) == set(), \
            "a new checkout is not a known one"
        found = observer.detect_new_checkouts(events)
        assert found == {fresh.resolve()}, f"the new checkout must be detected: {found}"

        # An event inside a repository already observed is not a new checkout.
        assert observer.detect_new_checkouts({existing / "file.txt"}) == set()
        # Nor is something outside every configured root.
        assert observer.detect_new_checkouts({Path(temp) / "elsewhere" / "x"}) == set()

    print("new-checkout detection OK")


if __name__ == "__main__":
    main()
