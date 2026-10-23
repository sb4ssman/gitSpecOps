"""Read what a range of history holds: every file version under every path it had, every commit
record, and the bytes of any file version. Plain reads -- no judgment about what is in them.

A range is anything `git log` accepts: `["--all"]`, a ref, `["A..B"]`, `["HEAD", "--not",
"--remotes"]`. Failures raise `CommandFailed` / `CommandTimeout`: a history that could not be
read must never look like a history with nothing in it.

**Every path, not only the first.** `git rev-list --objects` names each object once, under the
first path it meets, so a file whose content matched another file's was never seen under its own
name -- and a value in that file's *name* could not be found. Paths come from the per-commit
diffs instead (`log --raw -m --root`), which list every (path, version) pair ever introduced,
including a merge's own changes. Found while rebuilding the reader, 2026-10-20.

**What was published, not what a config makes of it.** Commit records are parsed from the raw
objects (`--pretty=raw`, no mailmap, no signature verification, no decoration), so a `.mailmap`
or a user's `log.*` settings cannot change what is reported, and no signing tool is ever run.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from Basic._run import CommandFailed, run_checked, stream

TIMEOUT_SECONDS = 1800
#: Settings that would otherwise change `git log`'s output, or make it run a signing tool.
_PLAIN_LOG = ["-c", "log.showSignature=false", "log", "--no-color", "--no-decorate",
              "--no-use-mailmap"]
_GITLINK = "160000"   # a submodule entry: a commit in another repository, not a file


def git_output(repo: Path | str, args: list[str], timeout: float = TIMEOUT_SECONDS) -> str:
    """`git <args>`'s stdout; raises `CommandFailed` / `CommandTimeout` instead of failing quietly."""
    return run_checked(["git", *args], cwd=repo, timeout=timeout).stdout


def _absent(object_id: str) -> bool:
    return not object_id or set(object_id) == {"0"}


def file_versions(repo: Path | str, revs: Iterable[str]) -> dict[str, set[str]]:
    """`{file version id: every path it appeared under}` across the range."""
    text = git_output(repo, [*_PLAIN_LOG, "--format=", "--raw", "-z", "-m", "--root",
                           "--no-renames", "--no-abbrev", *revs])
    found: dict[str, set[str]] = {}
    parts = text.split("\0")
    index = 0
    while index < len(parts):
        meta = parts[index].strip()
        if not meta.startswith(":"):
            index += 1
            continue
        path = parts[index + 1] if index + 1 < len(parts) else ""
        index += 2
        fields = meta[1:].split()   # old mode, new mode, old id, new id, status
        if len(fields) >= 5 and path and fields[1] != _GITLINK and not _absent(fields[3]):
            found.setdefault(fields[3], set()).add(path)
    return found


def files_at(repo: Path | str, rev: str) -> dict[str, str]:
    """`{path: file version id}` for every file in one commit's tree."""
    files = {}
    for entry in git_output(repo, ["ls-tree", "-r", "-z", rev]).split("\0"):
        meta, _, path = entry.partition("\t")
        fields = meta.split()
        if path and len(fields) == 3 and fields[1] == "blob":
            files[path] = fields[2]
    return files


@dataclass(frozen=True)
class Person:
    """A name and address as written into a commit, with its time."""
    name: str
    email: str
    when: int = 0
    offset: str = ""


def _person(value: str) -> Person:
    opening, closing = value.rfind(" <"), value.rfind("> ")
    if opening < 0 or closing < opening:
        return Person(value, "")
    when, _, offset = value[closing + 2:].partition(" ")
    return Person(value[:opening], value[opening + 2:closing],
                  int(when) if when.isdigit() else 0, offset)


@dataclass(frozen=True)
class Commit:
    """One commit as published: its ids, both identities, whether it is signed, its message."""
    id: str
    tree: str
    parents: tuple[str, ...]
    author: Person
    committer: Person
    signed: bool
    message: str


def _commit(record: str) -> Commit | None:
    lines = record.strip("\n").split("\n")
    headers: list[list[str]] = []
    body: list[str] = []
    in_body = False
    for line in lines:
        if in_body:
            body.append(line[4:] if line.startswith("    ") else line)
        elif not line:
            in_body = True
        elif line.startswith(" ") and headers:
            headers[-1][1] += "\n" + line[1:]   # a continued header (a signature, a mergetag)
        else:
            key, _, value = line.partition(" ")
            headers.append([key, value])
    fields: dict[str, list[str]] = {}
    for key, value in headers:
        fields.setdefault(key, []).append(value)
    if not fields.get("commit") or not fields.get("tree"):
        return None
    return Commit(
        id=fields["commit"][0].split()[0],
        tree=fields["tree"][0],
        parents=tuple(fields.get("parent", [])),
        author=_person((fields.get("author") or [""])[0]),
        committer=_person((fields.get("committer") or [""])[0]),
        signed=bool(fields.get("gpgsig") or fields.get("gpgsig-sha256")),
        message="\n".join(body),
    )


def commits(repo: Path | str, revs: Iterable[str]) -> list[Commit]:
    """Every commit in the range, newest first, as its raw object records it."""
    text = git_output(repo, [*_PLAIN_LOG, "--pretty=raw", "-z", *revs])
    return [commit for commit in map(_commit, text.split("\0")) if commit]


def read_blobs(repo: Path | str, ids: Iterable[str],
               timeout: float = TIMEOUT_SECONDS) -> Iterator[tuple[str, bytes | None]]:
    """Yield `(id, bytes)` for each file version, streamed through one `git cat-file --batch`.

    An id the repository does not hold yields `(id, None)` -- reported, never skipped, so a
    caller can say what it could not read. Anything that is not a file version is skipped.
    """
    ids = list(ids)
    feed = (f"{object_id}\n".encode("ascii") for object_id in ids)
    answered = 0
    with stream(["git", "cat-file", "--batch"], cwd=repo, timeout=timeout, feed=feed) as out:
        for _ in ids:
            header = out.stdout.readline().decode("ascii", errors="replace").split()
            if not header:
                break   # the command ended early; leaving the block reports why
            answered += 1
            if len(header) == 2 and header[1] == "missing":
                yield header[0], None
                continue
            if len(header) != 3 or not header[2].isdigit():
                raise CommandFailed(f"git cat-file --batch: unexpected header {header!r}")
            data = out.stdout.read(int(header[2]))
            out.stdout.read(1)   # the newline after each object
            if header[1] == "blob":
                yield header[0], data
    if answered < len(ids):
        raise CommandFailed(f"git cat-file --batch answered {answered} of {len(ids)} ids")
