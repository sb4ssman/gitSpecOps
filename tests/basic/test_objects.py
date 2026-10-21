"""Reading a history (`Basic/_objects.py`) and the facts that prove things about it later.

Offline: one scratch repository, built to hold each case a history reader can get wrong --
identical content under two names, a merge with changes of its own, a deleted file, a signed
commit, an annotated tag, a tag on a tree, a symbolic ref, an indented commit message, a
`HOST\\user` name -- and a bare folder as its remote.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Basic._facts import (identity_settings, next_commit_identity, ref_snapshot,  # noqa: E402
                          remote_refs, would_track)
from Basic._objects import commits, file_versions, files_at, read_blobs  # noqa: E402
from Basic._run import CommandFailed  # noqa: E402

FAILS: list[str] = []


def check(label: str, ok: bool) -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}")
    if not ok:
        FAILS.append(label)


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=False)
    if done.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {done.stderr}")
    return done.stdout.strip()


def write(repo: Path, name: str, text: str) -> None:
    (repo / name).write_bytes(text.encode("utf-8"))


def save(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


with tempfile.TemporaryDirectory(prefix="basic-objects-") as tmp:
    tmp = Path(tmp)
    repo = tmp / "repo"
    git(tmp, "init", "-q", "-b", "main", str(repo))
    git(repo, "config", "core.autocrlf", "false")
    git(repo, "config", "user.email", "t@example.test")
    git(repo, "config", "user.name", r"MACHINE\t")
    write(repo, ".gitignore", "private/\n")
    write(repo, "a.txt", "same\n")
    save(repo, "one")
    write(repo, "b machine-x.txt", "same\n")   # identical content, a second name
    save(repo, "two\n\n    an indented line\nlast line")
    git(repo, "checkout", "-q", "-b", "side")
    write(repo, "side.txt", "side\n")
    save(repo, "side")
    git(repo, "checkout", "-q", "main")
    write(repo, "main.txt", "main\n")
    save(repo, "main")
    git(repo, "merge", "-q", "--no-ff", "--no-commit", "side")
    write(repo, "evil.txt", "only the merge adds this\n")   # a merge's own change
    save(repo, "merge")
    git(repo, "rm", "-q", "a.txt")
    git(repo, "commit", "-q", "-m", "delete a.txt")
    git(repo, "tag", "-a", "-m", "annotated", "v1")
    git(repo, "tag", "treetag", "main^{tree}")
    # A signed commit, written by hand: no signing tool is needed to *read* a signature.
    tree, parent = git(repo, "rev-parse", "main^{tree}"), git(repo, "rev-parse", "main")
    raw = (f"tree {tree}\nparent {parent}\n"
           "author Signer <s@example.test> 1700000000 +0000\n"
           "committer Signer <s@example.test> 1700000000 +0000\n"
           "gpgsig -----BEGIN PGP SIGNATURE-----\n \n abc\n -----END PGP SIGNATURE-----\n"
           "\nsigned\n")
    # Bytes: a text-mode pipe on Windows would write "\r\n" and git would reject the object.
    signed_id = subprocess.run(["git", "-C", str(repo), "hash-object", "-w", "-t", "commit",
                                "--stdin"], input=raw.encode("utf-8"), capture_output=True,
                               check=True).stdout.decode().strip()
    git(repo, "update-ref", "refs/heads/signed", signed_id)
    git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/heads/main")

    # -- file_versions: every path, not only the first ----------------------------------------
    versions = file_versions(repo, ["--all"])
    same = git(repo, "rev-parse", "main~2:b machine-x.txt")
    check("identical content is listed under both of its names",
          versions.get(same) == {"a.txt", "b machine-x.txt"})
    evil = git(repo, "rev-parse", "main~1:evil.txt")
    check("a merge's own change is listed", versions.get(evil) == {"evil.txt"})
    every_blob = {line.split()[0] for line in git(
        repo, "cat-file", "--batch-check=%(objectname) %(objecttype)", "--batch-all-objects")
        .splitlines() if line.endswith(" blob")}
    check("every file version in the repository is found, deleted ones included",
          set(versions) == every_blob)
    check("a range limits what is read",
          set(file_versions(repo, ["main~3"])) == {git(repo, "rev-parse", "main~3:.gitignore"),
                                                   same})   # main~3 is "two"

    # -- commits: as published ---------------------------------------------------------------
    records = commits(repo, ["--all"])
    check("every commit is read", len(records) == int(git(repo, "rev-list", "--count", "--all")))
    by_message = {record.message.splitlines()[0]: record for record in records}
    check("a signed commit is recognized without running a signing tool",
          by_message["signed"].signed and not by_message["merge"].signed)
    check("a merge lists both parents", len(by_message["merge"].parents) == 2)
    two = by_message["two"]
    check("a HOST\\user name and its address are read as written",
          (two.author.name, two.author.email) == (r"MACHINE\t", "t@example.test"))
    check("a message keeps its own indentation",
          two.message == "two\n\n    an indented line\nlast line")
    check("a commit's time is read", by_message["signed"].committer.when == 1700000000)
    write(repo, ".mailmap", "Public <public@example.test> <t@example.test>\n")
    check("a .mailmap does not change what is reported",
          commits(repo, ["main~4"])[0].author.email == "t@example.test")
    (repo / ".mailmap").unlink()
    try:
        commits(repo, ["no-such-ref"])
        check("an unreadable range raises instead of coming back empty", False)
    except CommandFailed:
        check("an unreadable range raises instead of coming back empty", True)

    # -- read_blobs: streamed, nothing silently dropped --------------------------------------
    wanted = sorted(versions) + ["0" * 39 + "1", tree]
    got = dict(read_blobs(repo, wanted))
    check("every file version's bytes are read", all(got.get(i) is not None for i in versions))
    check("the content is exact", got[evil] == b"only the merge adds this\n")
    check("an id the repository lacks is reported as None, not skipped",
          "0" * 39 + "1" in got and got["0" * 39 + "1"] is None)
    check("something that is not a file version is skipped", tree not in got)

    # -- files_at and ref_snapshot -----------------------------------------------------------
    check("files_at lists a commit's files", set(files_at(repo, "main")) ==
          {".gitignore", "b machine-x.txt", "side.txt", "main.txt", "evil.txt"})
    snapshot = ref_snapshot(repo)
    check("the snapshot holds branches and commit tags",
          set(snapshot) == {"refs/heads/main", "refs/heads/side", "refs/heads/signed",
                            "refs/tags/v1"})
    v1 = snapshot["refs/tags/v1"]
    check("an annotated tag records its own object and the commit it names",
          v1.target != v1.commit and v1.commit == git(repo, "rev-parse", "main"))
    check("a snapshot records commit count, tree and files",
          snapshot["refs/heads/main"].commits == int(git(repo, "rev-list", "--count", "main"))
          and snapshot["refs/heads/main"].tree == tree
          and snapshot["refs/heads/main"].files == files_at(repo, "main"))
    check("a symbolic ref is left out", "refs/remotes/origin/HEAD" not in ref_snapshot(
        repo, ["refs/heads", "refs/remotes"], with_files=False))

    # -- remote_refs: what the remote serves now ---------------------------------------------
    bare = tmp / "remote.git"
    git(tmp, "init", "-q", "--bare", str(bare))
    git(repo, "push", "-q", str(bare), "main", "v1")
    served = remote_refs(repo, str(bare))
    check("remote_refs reads a remote's refs",
          served == {"refs/heads/main": snapshot["refs/heads/main"].commit,
                     "refs/tags/v1": v1.target})
    check("an unreachable remote is None, not empty",
          remote_refs(repo, str(tmp / "no-such-remote.git")) is None)

    # -- would_track: where private data may live --------------------------------------------
    check("an ignored folder is never tracked", not would_track(repo, repo / "private" / "x"))
    check("an ordinary path could be tracked", would_track(repo, repo / "notes" / "x.txt"))
    check("a path outside the work tree is never tracked", not would_track(repo, tmp / "x"))
    check("a path inside .git is never tracked", not would_track(repo, repo / ".git" / "x"))

    # -- identity: configured, and what the next commit would carry --------------------------
    settings = identity_settings(repo)
    check("identity settings name their scope",
          settings["user.email"].value == "t@example.test" and settings["user.email"].scope ==
          "local")
    check("the next commit's identity is read",
          next_commit_identity(repo)["author"] == (r"MACHINE\t", "t@example.test"))
    bare_repo = tmp / "unconfigured"
    git(tmp, "init", "-q", str(bare_repo))
    saved = {key: os.environ.get(key) for key in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM")}
    os.environ["GIT_CONFIG_GLOBAL"] = str(tmp / "no-global-config")
    os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
    try:
        unset = identity_settings(bare_repo)
        check("an identity set nowhere is None, with no invented default",
              unset == {"user.name": None, "user.email": None})
        guessed = next_commit_identity(bare_repo)
        check("what git would guess instead is still reported (or None), never raised",
              set(guessed) == {"author", "committer"})
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

if FAILS:
    print(f"\n{len(FAILS)} FAILED")
    raise SystemExit(1)
print("\nALL-OBJECTS-TESTS-PASS")
