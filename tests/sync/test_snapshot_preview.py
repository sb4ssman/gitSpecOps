"""Snapshot preview: faithful listings from real patches, and hostile bundles caught."""
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
from snapshot_preview import base_available, parse_patch, path_problem, preview

GIT = ["-c", "user.name=Test", "-c", "user.email=test@example.invalid",
       "-c", "commit.gpgsign=false"]


def git(repository, *args):
    result = subprocess.run(["git", *GIT, *args], cwd=repository, capture_output=True, text=True,
                            check=False)
    if result.returncode:
        raise AssertionError(f"git {args} failed: {result.stderr}")
    return result.stdout


def carried(path, data: bytes, size=None, digest=None):
    return {"path": path, "size": len(data) if size is None else size,
            "sha256": digest or hashlib.sha256(data).hexdigest(),
            "content_base64": base64.b64encode(data).decode()}


def bundle_with(**fields):
    values = {"repo_id": "a" * 32, "machine_id": "machine-a", "captured_at": "now",
              "base_commit": "c" * 40, "branch": "main", "staged_patch": "",
              "unstaged_patch": ""}
    values.update(fields)
    return Bundle(**values).to_dict()


def test_real_repository_round_trip():
    """Every awkward case at once, straight from real git output."""
    with tempfile.TemporaryDirectory() as temp:
        repository = Path(temp) / "work"
        repository.mkdir()
        git(repository, "init", "-q", "-b", "main")
        (repository / "query.sql").write_bytes(b"select 1;\n-- remove me\nselect 2;\n")
        (repository / "old name.txt").write_bytes(b"rename me\n" * 20)
        (repository / "gone.txt").write_bytes(b"delete me\n")
        (repository / "image.bin").write_bytes(bytes(range(256)))
        (repository / "caf\u00e9.txt").write_bytes(b"accent\n")
        git(repository, "add", "-A")
        git(repository, "commit", "-qm", "base")
        base = git(repository, "rev-parse", "HEAD").strip()

        # Staged: rename a name with a space, delete, change binary content.
        git(repository, "mv", "old name.txt", "new name.txt")
        git(repository, "rm", "-q", "gone.txt")
        (repository / "image.bin").write_bytes(bytes(reversed(range(256))))
        git(repository, "add", "image.bin")
        # Unstaged: remove a line that itself reads like a file header, edit a quoted name.
        (repository / "query.sql").write_bytes(b"select 1;\nselect 2;\n")
        (repository / "caf\u00e9.txt").write_bytes(b"accent changed\n")
        (repository / "extra.txt").write_bytes(b"untracked\n")

        body = capture.capture(repository, "a" * 32, "machine-a",
                               untracked=["extra.txt"]).to_dict()
        view = preview(body)
        assert view["restorable"], view["problems"]
        assert view["base_commit"] == base

        staged = {item["path"]: item for item in view["staged"]}
        assert staged["new name.txt"]["change"] == "renamed"
        assert staged["new name.txt"]["from"] == "old name.txt"
        assert staged["gone.txt"]["change"] == "deleted"
        assert staged["image.bin"]["binary"] is True

        unstaged = {item["path"]: item for item in view["unstaged"]}
        # "--- remove me" inside a hunk must not have been read as a file header.
        assert set(unstaged) == {"query.sql", "caf\u00e9.txt"}, unstaged
        assert view["untracked"] == [{"path": "extra.txt", "size": len(b"untracked\n"),
                                      "mode": 0o100644}]

        assert base_available(repository, base)
        assert not base_available(repository, "0" * 40)
        assert not base_available(repository, "not-a-commit")


def test_path_rules_hold_on_every_platform():
    for bad in ("../escape", "a/../../b", "/etc/passwd", "C:/windows", "a\\b", ".git/config",
                "sub/.GIT/hooks/x", "CON", "aux.txt", "lpt1.log", "trailing.", "space ",
                "a//b", "./x", "what?.txt", "pipe|name", "nul\0byte", ""):
        assert path_problem(bad), f"{bad!r} must be refused"
    for good in ("src/main.py", "caf\u00e9.txt", "new name.txt", ".github/workflows/ci.yml",
                 "console.log", "a.b.c/d-e_f"):
        assert not path_problem(good), f"{good!r} should be allowed"


def test_hostile_bundles_are_not_restorable():
    """A checksum proves the bytes are what a machine wrote -- not that they are safe."""
    data = b"payload\n"
    cases = {
        "traversal in a carried file": bundle_with(files=[carried("../evil.txt", data)]),
        "digest mismatch": bundle_with(files=[carried("ok.txt", data, digest="0" * 64)]),
        "size mismatch": bundle_with(files=[carried("ok.txt", data, size=999)]),
        "case collision": bundle_with(files=[carried("Readme.md", data),
                                             carried("README.md", data)]),
        "invalid base64": bundle_with(files=[{**carried("ok.txt", data),
                                              "content_base64": "not base64!!"}]),
        "bad base commit": bundle_with(base_commit="HEAD"),
        "traversal in a patch": bundle_with(staged_patch=(
            "diff --git a/../x b/../x\n--- a/../x\n+++ b/../x\n@@ -0,0 +1 @@\n+x\n")),
        "truncated hunk": bundle_with(unstaged_patch=(
            "diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -1,3 +1,3 @@\n context\n")),
        "binary without content": bundle_with(staged_patch=(
            "diff --git a/i.bin b/i.bin\nindex 1..2 100644\nBinary files a/i.bin and b/i.bin "
            "differ\n")),
        "carried file collides with a patched file": bundle_with(
            staged_patch="diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -1 +1 @@\n-a\n+b\n",
            files=[carried("F", data)]),
        "symbolic link": bundle_with(staged_patch=(
            "diff --git a/link b/link\nnew file mode 120000\nindex 0000000..1111111\n"
            "--- /dev/null\n+++ b/link\n@@ -0,0 +1 @@\n+../../outside\n"
            "\\ No newline at end of file\n")),
        "submodule": bundle_with(staged_patch=(
            "diff --git a/sub b/sub\nnew file mode 160000\nindex 0000000..2222222\n"
            "--- /dev/null\n+++ b/sub\n@@ -0,0 +1 @@\n+Subproject commit " + "3" * 40 + "\n")),
    }
    for name, body in cases.items():
        view = preview(body)
        assert not view["restorable"], f"{name}: expected problems"
        assert view["problems"], name


def test_parser_is_not_fooled_by_hunk_content():
    patch = ("diff --git a/notes.md b/notes.md\n--- a/notes.md\n+++ b/notes.md\n"
             "@@ -1,2 +1,2 @@\n---- not a header\n++++ b/also not a header\n"
             " \n")
    entries = parse_patch(patch)
    assert [entry["path"] for entry in entries] == ["notes.md"]


def main():
    test_real_repository_round_trip()
    test_path_rules_hold_on_every_platform()
    test_hostile_bundles_are_not_restorable()
    test_parser_is_not_fooled_by_hunk_content()
    print("ALL-SNAPSHOT-PREVIEW-TESTS-PASS")


if __name__ == "__main__":
    main()
