"""Materialization plans first and never replaces a destination checkout."""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup

setup("sync")
from fleet_actions import apply_materialize, plan_materialize


def git(path, *args):
    result = subprocess.run(["git", *args], cwd=path, capture_output=True, text=True, check=False)
    if result.returncode:
        raise AssertionError(result.stderr)


def test_materialize_clones_only_an_absent_planned_destination():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        remote, source, destination = root / "team.git", root / "source", root / "destination"
        git(root, "init", "--bare", "--initial-branch=main", str(remote))
        git(root, "clone", "-q", str(remote), str(source))
        git(source, "config", "user.email", "test@example.invalid")
        git(source, "config", "user.name", "Test")
        (source / "work.txt").write_text("base\n"); git(source, "add", "work.txt")
        git(source, "commit", "-qm", "base"); git(source, "push", "-q", "-u", "origin", "main")
        destination.mkdir()
        # Plan from a normal host-shaped origin, then use the disposable local bare remote to
        # exercise clone execution without network access.
        git(source, "remote", "set-url", "origin", "https://example.invalid/team/work.git")
        plan = plan_materialize([source], destination)
        assert plan[0]["action"] == "clone"
        assert not plan[0]["target"].exists()
        plan[0]["origin"] = str(remote)
        result = apply_materialize(plan)
        assert result[0]["action"] == "cloned"
        assert (plan[0]["target"] / ".git").exists()
        assert apply_materialize(plan)[0]["action"] == "exists"


def test_materialize_refuses_an_origin_that_would_escape_its_library():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source, destination = root / "source", root / "destination"
        source.mkdir(); destination.mkdir()
        git(source, "init", "-q", "-b", "main")
        git(source, "remote", "add", "origin", "https://example.invalid/../escape.git")
        plan = plan_materialize([source], destination)
        assert plan == [{"source": source.resolve(), "name": "source", "action": "needs_review",
                         "detail": "Origin identity is not a safe destination path."}]


def main():
    test_materialize_clones_only_an_absent_planned_destination()
    test_materialize_refuses_an_origin_that_would_escape_its_library()
    print("ALL-MATERIALIZE-TESTS-PASS")


if __name__ == "__main__":
    main()
