"""Snapshot restore: faithful into a disposable checkout, or refused with the target untouched."""
import base64
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup

setup("sync")
import capture
from capture import Bundle
from snapshot_restore import RestoreRefused, prepare_disposable_checkout, restore

GIT = ["-c", "user.name=Test", "-c", "user.email=test@example.invalid",
       "-c", "commit.gpgsign=false"]
PATCH_FLAGS = ["--binary", "--no-color", "--no-ext-diff", "--no-textconv",
               "--src-prefix=a/", "--dst-prefix=b/"]
REPO_ID = "a" * 32


def git(repository, *args):
    result = subprocess.run(["git", *GIT, *args], cwd=repository, capture_output=True,
                            text=True, encoding="utf-8", check=False)
    if result.returncode:
        raise AssertionError(f"git {args} failed: {result.stderr}")
    return result.stdout


def status(repository):
    return git(repository, "status", "--porcelain=v1", "-uall")


def refused(call, expect=""):
    try:
        call()
    except RestoreRefused as exc:
        assert expect in str(exc), f"expected {expect!r} in {exc}"
        return str(exc)
    raise AssertionError("expected a refusal")


def rebuilt(body, **changes):
    """A bundle with a valid checksum -- a hostile machine can compute checksums too."""
    fields = {key: body[key] for key in ("repo_id", "machine_id", "captured_at", "base_commit",
                                         "branch", "staged_patch", "unstaged_patch", "files",
                                         "notes")}
    fields.update(changes)
    return Bundle(**fields).to_dict()


def source_repository(root: Path):
    """Staged rename, deletion, binary change and new file; unstaged edit; a carried CRLF file."""
    source = root / "source"
    source.mkdir()
    git(source, "init", "-q", "-b", "main")
    (source / "docs").mkdir()
    (source / "docs" / "a.txt").write_bytes(b"doc\n")
    (source / "query.sql").write_bytes(b"select 1;\n-- remove me\nselect 2;\n")
    (source / "old name.txt").write_bytes(b"rename me\n" * 20)
    (source / "gone.txt").write_bytes(b"delete me\n")
    (source / "image.bin").write_bytes(bytes(range(256)))
    git(source, "add", "-A")
    git(source, "commit", "-qm", "base")
    base = git(source, "rev-parse", "HEAD").strip()
    git(source, "mv", "old name.txt", "new name.txt")
    git(source, "rm", "-q", "gone.txt")
    (source / "image.bin").write_bytes(bytes(reversed(range(256))))
    (source / "fresh.txt").write_bytes(b"staged new file\n")
    git(source, "add", "image.bin", "fresh.txt")
    (source / "query.sql").write_bytes(b"select 1;\nselect 2;\n")
    (source / "extra.txt").write_bytes(b"carried untracked\r\nwith crlf\r\n")
    return source, base


def other_machine(root: Path, source: Path) -> Path:
    """A second machine's repository: it has the committed base, none of the local work."""
    other = root / "other"
    git(root, "clone", "-q", str(source), str(other))
    return other


def test_round_trip_is_exact_and_touches_nothing_else():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source, base = source_repository(root)
        body = capture.capture(source, REPO_ID, "machine-a", untracked=["extra.txt"]).to_dict()
        source_status = status(source)
        other = other_machine(root, source)

        target = prepare_disposable_checkout(other, base, root / "restore")
        assert git(target, "rev-parse", "HEAD").strip() == base and status(target) == ""
        result = restore(body, target)

        assert result["verified"] and result["staged"] == 4 and result["untracked"] == 1
        assert git(target, "diff", "--staged", *PATCH_FLAGS) == body["staged_patch"]
        assert git(target, "diff", *PATCH_FLAGS) == body["unstaged_patch"]
        assert (target / "extra.txt").read_bytes() == (source / "extra.txt").read_bytes(), \
            "carried untracked files are byte-identical, CRLF included"
        assert (target / "new name.txt").exists() and not (target / "gone.txt").exists()
        assert git(target, "rev-parse", "HEAD").strip() == base, "restore never commits"
        assert status(source) == source_status, "the capturing machine is never touched"
        assert status(other) == "", "the repository the checkout came from is never touched"


def test_failure_mid_restore_rolls_back_to_base():
    """Staged changes apply, then the unstaged ones cannot: nothing may be left half-done."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source, base = source_repository(root)
        body = capture.capture(source, REPO_ID, "machine-a", untracked=["extra.txt"]).to_dict()
        broken_patch = body["unstaged_patch"].replace("\n select 1;\n", "\n select X;\n", 1)
        assert broken_patch != body["unstaged_patch"], "fixture must actually break the patch"
        broken = rebuilt(body, unstaged_patch=broken_patch)

        target = prepare_disposable_checkout(other_machine(root, source), base, root / "restore")
        refused(lambda: restore(broken, target), "returned to its base")

        assert git(target, "rev-parse", "HEAD").strip() == base
        assert status(target) == "", f"target must be clean after rollback: {status(target)!r}"
        assert (target / "old name.txt").exists() and (target / "gone.txt").exists()
        assert not (target / "fresh.txt").exists() and not (target / "new name.txt").exists()
        assert not (target / "extra.txt").exists()


def test_refusals_leave_the_target_alone():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source, base = source_repository(root)
        body = capture.capture(source, REPO_ID, "machine-a", untracked=["extra.txt"]).to_dict()
        other = other_machine(root, source)

        target = prepare_disposable_checkout(other, base, root / "first")
        hostile = rebuilt(body, files=[{"path": "../evil.txt", "size": 1,
                                        "sha256": hashlib.sha256(b"x").hexdigest(),
                                        "content_base64": base64.b64encode(b"x").decode()}])
        refused(lambda: restore(hostile, target), "cannot be restored safely")
        assert not (root / "evil.txt").exists() and status(target) == ""

        (target / "docs" / "a.txt").write_bytes(b"dirty\n")
        refused(lambda: restore(body, target), "must be clean")
        git(target, "checkout", "--", "docs/a.txt")
        (target / "stray.txt").write_bytes(b"untracked counts too\n")
        refused(lambda: restore(body, target), "must be clean")
        (target / "stray.txt").unlink()

        refused(lambda: restore(body, target / "docs"), "top folder")

        (target / "docs" / "a.txt").write_bytes(b"moved on\n")
        git(target, "commit", "-qam", "later work")
        refused(lambda: restore(body, target), "not at the snapshot's base")

        merging = prepare_disposable_checkout(other, base, root / "merging")
        (merging / ".git" / "MERGE_HEAD").write_text("0" * 40 + "\n")
        refused(lambda: restore(body, merging), "in progress")

        occupied = root / "occupied"
        occupied.mkdir()
        (occupied / "keep.txt").write_bytes(b"not yours\n")
        refused(lambda: prepare_disposable_checkout(other, base, occupied), "new or an empty")
        refused(lambda: prepare_disposable_checkout(other, "0" * 40, root / "nobase"),
                "base commit")


def test_restore_never_overwrites_an_ignored_local_file():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = root / "source"
        source.mkdir()
        git(source, "init", "-q", "-b", "main")
        (source / ".gitignore").write_bytes(b"*.local\n")
        (source / "t.txt").write_bytes(b"one\n")
        git(source, "add", "-A")
        git(source, "commit", "-qm", "base")
        base = git(source, "rev-parse", "HEAD").strip()
        (source / "notes.local").write_bytes(b"from the snapshot\n")
        # Carrying an ignored file is a deliberate, local choice; restore must still refuse to
        # overwrite whatever the target already holds under that name.
        body = capture.capture(source, REPO_ID, "machine-a", untracked=["notes.local"],
                               policy=capture.CapturePolicy(obey_gitignore=False)).to_dict()
        assert [item["path"] for item in body["files"]] == ["notes.local"]

        target = prepare_disposable_checkout(other_machine(root, source), base, root / "restore")
        (target / "notes.local").write_bytes(b"precious local file\n")
        assert status(target) == "", "an ignored file leaves status clean -- the trap"
        refused(lambda: restore(body, target), "never overwrites")
        assert (target / "notes.local").read_bytes() == b"precious local file\n"


def test_repository_apply_config_cannot_alter_restored_content():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = root / "source"
        source.mkdir()
        git(source, "init", "-q", "-b", "main")
        (source / "t.txt").write_bytes(b"one\n")
        git(source, "add", "t.txt")
        git(source, "commit", "-qm", "base")
        base = git(source, "rev-parse", "HEAD").strip()
        (source / "t.txt").write_bytes(b"one\ntrailing spaces   \n\tmixed indent \n")
        body = capture.capture(source, REPO_ID, "machine-a").to_dict()

        target = prepare_disposable_checkout(other_machine(root, source), base, root / "restore")
        git(target, "config", "apply.whitespace", "error")
        plain = subprocess.run(["git", "apply", "--check", "-"], cwd=target,
                               input=body["unstaged_patch"].encode(), capture_output=True,
                               check=False)
        assert plain.returncode, "fixture must show the hazard: this config refuses the patch"

        assert restore(body, target)["verified"]
        assert git(target, "diff", *PATCH_FLAGS) == body["unstaged_patch"]


def main():
    test_round_trip_is_exact_and_touches_nothing_else()
    test_failure_mid_restore_rolls_back_to_base()
    test_refusals_leave_the_target_alone()
    test_restore_never_overwrites_an_ignored_local_file()
    test_repository_apply_config_cannot_alter_restored_content()
    print("ALL-SNAPSHOT-RESTORE-TESTS-PASS")


if __name__ == "__main__":
    main()
