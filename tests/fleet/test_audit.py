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
        # No upstream and no origin are separate, actionable observations.
        (local / "file.txt").write_text("changed\n")
        before = (local / "file.txt").read_bytes()
        rows = {item["name"]: item for item in audit_repositories([clean, local])}
        assert "no upstream" in rows["clean"]["findings"]
        assert "no origin" in rows["local"]["findings"]
        assert "tracked changes" in rows["local"]["findings"]
        assert (local / "file.txt").read_bytes() == before
        assert "No remote, branch, index, or working file was changed" in render_audit(list(rows.values()))


def test_the_command_audits_what_the_observer_skips():
    """Was: the command audited only the observer's inventory, which drops a repository with no
    origin -- so "no origin", the finding the audit exists for, could never be reported."""
    import io
    import json
    from argparse import Namespace
    from contextlib import redirect_stdout

    from fleet_app import command_audit
    from fleet_config import new_config

    with tempfile.TemporaryDirectory() as temporary:
        library = Path(temporary) / "lib"
        repos = {name: library / name for name in ("only-here", ".hidden-notes")}
        for repo in repos.values():
            repo.mkdir(parents=True); git(repo, "init", "-q", "-b", "main")
            git(repo, "config", "user.email", "test@example.invalid")
            git(repo, "config", "user.name", "Test")
            (repo / "file.txt").write_text("base\n"); git(repo, "add", "file.txt")
            git(repo, "commit", "-qm", "base")
        (repos["only-here"] / "file.txt").write_text("changed\n")
        git(repos["only-here"], "stash", "-q")
        out = io.StringIO()
        with redirect_stdout(out):
            code = command_audit(Namespace(json=True), new_config("m", "M", [library], "22" * 32))
        rows = {row["name"]: row["findings"] for row in json.loads(out.getvalue())}
        assert code == 1, "findings must make the audit exit non-zero"
        assert set(rows) == {"only-here", ".hidden-notes"}, rows
        assert "no origin" in rows["only-here"] and "1 stash(es)" in rows["only-here"], rows
        assert any("on no remote" in finding for finding in rows[".hidden-notes"]), rows


def main():
    test_audit_reports_without_mutating()
    test_the_command_audits_what_the_observer_skips()
    print("ALL-AUDIT-TESTS-PASS")


if __name__ == "__main__":
    main()
