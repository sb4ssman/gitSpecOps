"""Catch-up stays a narrow fast-forward operation, even over a mixed repository library."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "git-sync-suggester"))
sys.path.insert(0, str(ROOT / "git-sync-suggester" / "app"))

from fleet_actions import apply_catchup, plan_catchup, render_catchup


def git(path: Path, *args: str) -> None:
    result = subprocess.run(["git", *args], cwd=path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def make_remote(root: Path, name: str):
    remote = root / f"{name}.git"
    git(root, "init", "--bare", "-q", "-b", "main", str(remote))
    seed = root / f"{name}-seed"
    git(root, "clone", "-q", str(remote), str(seed))
    git(seed, "config", "user.email", "test@example.invalid")
    git(seed, "config", "user.name", "Test")
    (seed / "base.txt").write_text("base\n", encoding="utf-8")
    git(seed, "add", "base.txt")
    git(seed, "commit", "-qm", "base")
    git(seed, "push", "-q", "-u", "origin", "main")
    return remote


def test_clean_behind_only_is_the_only_apply_candidate():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        remote = make_remote(root, "work")
        local, other = root / "local", root / "other"
        git(root, "clone", "-q", str(remote), str(local))
        git(root, "clone", "-q", str(remote), str(other))
        git(other, "config", "user.email", "test@example.invalid")
        git(other, "config", "user.name", "Test")
        (other / "remote.txt").write_text("new\n", encoding="utf-8")
        git(other, "add", "remote.txt")
        git(other, "commit", "-qm", "remote")
        git(other, "push", "-q", "origin", "main")

        plan = plan_catchup([local])
        assert plan[0]["action"] == "pull", plan
        assert "No working tree changed" in render_catchup(plan)
        result = apply_catchup(plan)
        assert result[0]["action"] == "pulled", result
        assert (local / "remote.txt").read_text(encoding="utf-8") == "new\n"


def test_dirty_ahead_and_diverged_repositories_never_pull():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        remote = make_remote(root, "mixed")
        dirty, ahead, diverged, other = (root / "dirty", root / "ahead", root / "diverged",
                                         root / "other")
        for folder in (dirty, ahead, diverged, other):
            git(root, "clone", "-q", str(remote), str(folder))
            git(folder, "config", "user.email", "test@example.invalid")
            git(folder, "config", "user.name", "Test")
        (dirty / "scratch.txt").write_text("do not touch\n", encoding="utf-8")
        (diverged / "local.txt").write_text("local\n", encoding="utf-8")
        git(diverged, "add", "local.txt")
        git(diverged, "commit", "-qm", "local")
        (other / "remote.txt").write_text("remote\n", encoding="utf-8")
        git(other, "add", "remote.txt")
        git(other, "commit", "-qm", "remote")
        git(other, "push", "-q", "origin", "main")
        git(ahead, "pull", "-q", "--ff-only")
        (ahead / "ahead.txt").write_text("local\n", encoding="utf-8")
        git(ahead, "add", "ahead.txt")
        git(ahead, "commit", "-qm", "ahead")

        plan = plan_catchup([dirty, ahead, diverged])
        assert {item["action"] for item in plan} == {"dirty", "ahead", "diverged"}, plan
        result = apply_catchup(plan)
        assert [item["action"] for item in result] == [item["action"] for item in plan]
        assert (dirty / "scratch.txt").exists()


def main():
    test_clean_behind_only_is_the_only_apply_candidate()
    test_dirty_ahead_and_diverged_repositories_never_pull()
    print("ALL-CATCHUP-TESTS-PASS")


if __name__ == "__main__":
    main()
