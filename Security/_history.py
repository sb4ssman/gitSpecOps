"""Read everything a repository's history publishes: every file version, every path, every
commit message, and every author and committer identity. Read-only.

A pushed commit is readable forever by anyone who can read the repository, whatever the current
files say -- and a commit's *metadata* (author email, a `HOST\\user` name) is published as surely
as its content. The 2026-09-11 audit of this repository scanned file content only and missed
the largest exposure: a personal email address on most commits.
"""
from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

from Basic._run import run_git
from Security._patterns import find

_TIMEOUT = 600
#: GitHub's own committer for web-UI commits: not the person's address.
GITHUB_WEB_COMMITTER = "noreply@github.com"
NOREPLY_SUFFIX = "@users.noreply.github.com"


@dataclass
class Identity:
    """One author/committer name+email pair as published, and where it appears."""
    name: str
    email: str
    commits: int = 0
    first: str = ""
    last: str = ""

    @property
    def concern(self) -> str:
        """Why this identity is personal data, or "" when it is not."""
        if self.email.lower() == GITHUB_WEB_COMMITTER:
            return ""
        reasons = []
        if not self.email.lower().endswith(NOREPLY_SUFFIX):
            reasons.append("a real email address")
        if "\\" in self.name:
            reasons.append("a machine name in the name (HOST\\user)")
        return " and ".join(reasons)


@dataclass
class Exposure:
    """Every place one value appears in history."""
    kind: str
    value: str
    paths: set = field(default_factory=set)      # file content: the paths of blobs holding it
    in_paths: set = field(default_factory=set)   # the value is part of a file *name*
    commits: set = field(default_factory=set)    # commit messages holding it
    current: bool = False                         # still in a file at a scanned tip


@dataclass
class HistoryReport:
    refs: list[str]
    objects: int = 0
    blobs: int = 0
    commits: int = 0
    signed: int = 0                                  # commits carrying a signature
    paths: set = field(default_factory=set)          # every path ever published
    binary: dict = field(default_factory=dict)       # path -> blob count read as binary
    exposures: dict = field(default_factory=dict)    # (kind, value) -> Exposure
    identities: dict = field(default_factory=dict)   # (name, email) -> Identity

    def exposure(self, kind: str, value: str) -> Exposure:
        return self.exposures.setdefault((kind, value), Exposure(kind, value))

    def personal_identities(self) -> list[Identity]:
        return [identity for identity in self.identities.values() if identity.concern]


def public_refs(repo: Path) -> list[str]:
    """What the world can read: every remote-tracking ref, as of the last fetch (maybe none)."""
    proc = run_git(repo, ["for-each-ref", "--format=%(refname)", "refs/remotes"])
    refs = [ref for ref in proc.stdout.split() if not ref.endswith("/HEAD")]
    return refs


def _git(repo: Path, args: list[str]) -> str:
    proc = run_git(repo, args, timeout=_TIMEOUT)
    if proc.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def _blobs(repo: Path, refs: list[str]) -> tuple[int, dict[str, set]]:
    """(object count, {blob sha: paths it was published under})."""
    lines = _git(repo, ["rev-list", "--objects", *refs]).splitlines()
    paths: dict[str, set] = {}
    for line in lines:
        sha, _, path = line.partition(" ")
        if path:
            paths.setdefault(sha, set()).add(path)
    return len(lines), paths


def _read_blobs(repo: Path, shas: list[str]):
    """Yield (sha, text) for every blob, through one `git cat-file --batch` process.

    A direct subprocess on purpose: `_run` collects all output at once, and a batch reader
    streams. Bounded the same way -- killed if it outlives the timeout. Ids are fed from a
    thread: written all at once, they deadlock as soon as both pipes fill.
    """
    proc = subprocess.Popen(["git", "-C", str(repo), "cat-file", "--batch"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)

    def feed():
        try:
            for sha in shas:
                proc.stdin.write(f"{sha}\n".encode("ascii"))
            proc.stdin.close()
        except OSError:
            pass

    threading.Thread(target=feed, daemon=True).start()
    try:
        for sha in shas:
            header = proc.stdout.readline().decode("ascii", errors="replace").split()
            if len(header) < 3 or header[1] == "missing":
                continue
            size = int(header[2])
            data = proc.stdout.read(size)
            proc.stdout.read(1)  # the newline after each object
            if header[1] == "blob":
                yield sha, data.decode("utf-8", errors="replace"), b"\0" in data[:8000]
    finally:
        proc.stdout.close()
        try:
            proc.wait(timeout=_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()


def _tips(repo: Path, refs: list[str]) -> set[str]:
    """The commits `refs` point at; `--all` means every ref, as it does for rev-list."""
    if "--all" in refs:
        listing = _git(repo, ["for-each-ref", "--format=%(objectname) %(objecttype)"])
        return {line.split()[0] for line in listing.splitlines() if line.endswith(" commit")}
    return {_git(repo, ["rev-parse", f"{ref}^{{commit}}"]).strip() for ref in refs}


def _commit_records(repo: Path, refs: list[str]):
    """Yield (sha, author name, author email, committer name, committer email, date, message)."""
    text = _git(repo, ["log", "--format=%H%x00%an%x00%ae%x00%cn%x00%ce%x00%aI%x00%B%x01", *refs])
    for record in text.split("\x01"):
        parts = record.strip("\n").split("\x00")
        if len(parts) == 7:
            yield tuple(parts)


def scan_history(repo: Path, refs: list[str], patterns: dict) -> HistoryReport:
    """Everything `refs` publish, matched against `patterns` (see `_patterns`)."""
    repo = Path(repo)
    report = HistoryReport(refs=list(refs))
    report.objects, paths_of = _blobs(repo, refs)
    at_tips = {parts[2] for tip in _tips(repo, refs) for parts in
               (line.split() for line in _git(repo, ["ls-tree", "-r", tip]).splitlines())
               if len(parts) >= 3 and parts[1] == "blob"}
    report.blobs = 0
    report.paths = {path for paths in paths_of.values() for path in paths}
    for sha, text, binary in _read_blobs(repo, sorted(paths_of)):
        report.blobs += 1
        if binary:
            # Still scanned (strings survive in bytecode and many formats), but compressed or
            # encoded content -- archives, images -- cannot be read this way. Reported, so no
            # one mistakes "nothing found" for "inspected".
            for path in paths_of[sha]:
                report.binary[path] = report.binary.get(path, 0) + 1
        for found in find(text, patterns):
            exposure = report.exposure(found.kind, found.value)
            exposure.paths.update(paths_of[sha])
            exposure.current = exposure.current or sha in at_tips
    for path in {p for paths in paths_of.values() for p in paths}:
        for found in find(path, patterns):
            report.exposure(found.kind, found.value).in_paths.add(path)
    for sha, an, ae, cn, ce, date, message in _commit_records(repo, refs):
        report.commits += 1
        for name, email in ((an, ae), (cn, ce)):
            identity = report.identities.setdefault((name, email), Identity(name, email))
            identity.commits += 1
            identity.first = min(identity.first or date, date)
            identity.last = max(identity.last, date)
        for found in find(message, patterns):
            report.exposure(found.kind, found.value).commits.add(sha)
    report.signed = sum(1 for line in _git(repo, ["log", "--pretty=raw", *refs]).splitlines()
                        if line.startswith("gpgsig"))
    return report
