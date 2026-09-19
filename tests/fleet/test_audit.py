"""Fleet audit stays a report: it notices local-only danger without changing Git."""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup

setup("sync")
from fleet_actions import audit_repositories, render_audit


def git(path, *args):
    result = subprocess.run(["git", *args], cwd=path, capture_output=True, text=True, check=False)
    if result.returncode:
        raise AssertionError(result.stderr)


def test_audit_reports_without_mutating():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        clean, local = root / "clean", root / "local"
        for repo in (clean, local):
            repo.mkdir(); git(repo, "init", "-q", "-b", "main")
            git(repo, "config", "user.email", "test@example.invalid")
            git(repo, "config", "user.name", "Test")
            (repo / "file.txt").write_text("base\n"); git(repo, "add", "file.txt")
            git(repo, "commit", "-qm", "base")
        git(clean, "remote", "add", "origin", "https://example.invalid/team/clean.git")
        git(clean, "branch", "--set-upstream-to", "origin/main") if False else None
        # No upstream and no origin are separate, actionable observations.
        (local / "file.txt").write_text("changed\n")
        before = (local / "file.txt").read_bytes()
        rows = {item["name"]: item for item in audit_repositories([clean, local])}
        assert "no upstream" in rows["clean"]["findings"]
        assert "no origin" in rows["local"]["findings"]
        assert "tracked changes" in rows["local"]["findings"]
        assert (local / "file.txt").read_bytes() == before
        assert "No remote, branch, index, or working file was changed" in render_audit(list(rows.values()))


def main():
    test_audit_reports_without_mutating()
    print("ALL-AUDIT-TESTS-PASS")


if __name__ == "__main__":
    main()
