"""Retirement needs an exact, freshly reachable commit -- not a clean status guess."""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup

setup("sync")
from capture import capture
from retirement import RetirementRefused, prove_retirement


def git(path, *args):
    result = subprocess.run(["git", *args], cwd=path, capture_output=True, text=True, check=False)
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


def refused(call, text):
    try:
        call()
    except RetirementRefused as exc:
        assert text in str(exc), str(exc)
        return
    raise AssertionError("expected retirement proof to refuse")


def make_repository(root: Path):
    remote, repository = root / "remote.git", root / "work"
    git(root, "init", "--bare", "--initial-branch=main", str(remote))
    git(root, "clone", "-q", str(remote), str(repository))
    git(repository, "config", "user.email", "test@example.invalid")
    git(repository, "config", "user.name", "Test")
    # The proof is byte-exact for carried files.  Avoid a machine-global line-ending rule
    # changing an untracked file between capture and the test commit.
    git(repository, "config", "core.autocrlf", "false")
    (repository / "tracked.txt").write_text("base\n")
    git(repository, "add", "tracked.txt")
    git(repository, "commit", "-qm", "base")
    git(repository, "push", "-q", "-u", "origin", "main")
    return repository


def test_exact_snapshot_commit_reachable_after_fresh_fetch_is_proof():
    with tempfile.TemporaryDirectory() as temporary:
        repository = make_repository(Path(temporary))
        (repository / "tracked.txt").write_text("saved change\n")
        git(repository, "add", "tracked.txt")
        (repository / "new.txt").write_text("carried\n")
        body = capture(repository, "a" * 32, "machine-a", untracked=["new.txt"]).to_dict()

        # Make the real commit that represents both stages of the saved snapshot, then publish.
        git(repository, "add", "tracked.txt", "new.txt")
        git(repository, "commit", "-qm", "save work")
        git(repository, "push", "-q")
        result = prove_retirement(repository, body)
        assert result["proof"].startswith("fresh upstream tree exactly")
        assert len(result["remote_commit"]) == 40


def test_unpushed_or_different_content_never_retires_a_snapshot():
    with tempfile.TemporaryDirectory() as temporary:
        repository = make_repository(Path(temporary))
        (repository / "tracked.txt").write_text("saved change\n")
        body = capture(repository, "a" * 32, "machine-a").to_dict()
        git(repository, "add", "tracked.txt")
        git(repository, "commit", "-qm", "local only")
        refused(lambda: prove_retirement(repository, body), "does not yet contain")

        git(repository, "push", "-q")
        (repository / "tracked.txt").write_text("different\n")
        git(repository, "add", "tracked.txt")
        git(repository, "commit", "-qm", "different work")
        git(repository, "push", "-q")
        refused(lambda: prove_retirement(repository, body), "does not yet contain")


def main():
    test_exact_snapshot_commit_reachable_after_fresh_fetch_is_proof()
    test_unpushed_or_different_content_never_retires_a_snapshot()
    print("ALL-RETIREMENT-TESTS-PASS")


if __name__ == "__main__":
    main()
