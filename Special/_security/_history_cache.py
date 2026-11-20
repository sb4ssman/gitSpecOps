"""Private, per-checkout checkpoints for fleet audits. Never used by commit or push gates."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from contextlib import closing
from pathlib import Path

from Basic._objects import git_output
from Basic._paths import find_program
from Basic._run import CommandFailed, run_git
from Special._security._findings import Report
from Special._security._material import _history_limits, _ref_ids
from Special._security._me import policy_revision
from Special._security._private_files import private_path

try:
    import sqlite3
except ImportError:
    sqlite3 = None

SQLITE_AVAILABLE = sqlite3 is not None
_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


def _digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _snapshot(repo, policy, engines):
    if policy.gaps:
        return None
    report = Report("", "history")
    if not _history_limits(report, repo) or report.gaps:
        return None
    refs = _ref_ids(repo)
    if not refs or any(not _OID.fullmatch(oid) for oid in refs.values()):
        return None
    bins = {name: find_program(name) for name in ("git", *engines)}
    if not all(bins.values()):
        return None
    source = Path(__file__).resolve().parent
    basic = source.parents[1] / "Basic"
    files = sorted(source.rglob("*.py")) + [basic / "_objects.py", basic / "_run.py"]
    # Keep configuration and environment fingerprints local, even though they are digests.
    config = git_output(repo, ["config", "--null", "--list"])
    environment = {name: value for name, value in os.environ.items()
                   if name.startswith(("GIT_", "GITLEAKS_", "BETTERLEAKS_", "TRUFFLEHOG_"))}
    data = [policy_revision(policy), sys.version, sys.platform, config, environment,
            [(name, _digest(path)) for name, path in bins.items()],
            [(path.relative_to(basic.parent).as_posix(), _digest(path)) for path in files]]
    fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return fingerprint, refs


class Checkpoint:
    def __init__(self, repo, home, policy, engines):
        self.repo, self.policy, self.engines = repo, policy, tuple(engines)
        self.path = private_path(home / "security-history.sqlite3")
        for suffix in ("-journal", "-wal", "-shm"):
            private_path(self.path.with_name(self.path.name + suffix))
        self.key = hashlib.sha256(os.fsencode(os.path.normcase(str(repo.resolve())))).hexdigest()
        self.snapshot = _snapshot(repo, policy, self.engines)
        self.previous = None
        self.refresh_batches = False

    def _connect(self):
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(descriptor)
        return sqlite3.connect(self.path, timeout=3)

    @staticmethod
    def batch_key(entries):
        return hashlib.sha256(json.dumps(entries, ensure_ascii=True).encode()).hexdigest()

    def has_clean_batch(self, key):
        if self.snapshot is None or self.engines or self.refresh_batches or not self.path.is_file():
            return False
        try:
            with closing(self._connect()) as connection:
                return connection.execute(
                    "SELECT 1 FROM batches_v1 WHERE checkout=? AND fingerprint=? AND batch=?",
                    (self.key, self.snapshot[0], key)).fetchone() is not None
        except CACHE_ERRORS:
            return False

    def save_clean_batch(self, key):
        if self.snapshot is None or self.engines:
            return
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute("""CREATE TABLE IF NOT EXISTS batches_v1 (
                                   checkout TEXT, fingerprint TEXT, batch TEXT,
                                   PRIMARY KEY (checkout, fingerprint, batch))""")
                connection.execute("INSERT OR IGNORE INTO batches_v1 VALUES (?, ?, ?)",
                                   (self.key, self.snapshot[0], key))
        except CACHE_ERRORS:
            pass

    def current(self, scanned_refs=None):
        return (self.snapshot is not None
                and (scanned_refs is None or scanned_refs == self.snapshot[1])
                and self.snapshot == _snapshot(self.repo, self.policy, self.engines))

    def lookup(self):
        if self.snapshot is None or not self.path.is_file():
            return None, ()
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT refs, report FROM history_v1 WHERE checkout=? AND fingerprint=?",
                                     (self.key, self.snapshot[0])).fetchone()
        if row is None:
            return None, ()
        refs, record = map(json.loads, row)
        if (not isinstance(refs, dict) or not isinstance(record, dict)
                or record.get("coverage") != "complete-for-selected-checks" or record.get("gaps")):
            return None, ()
        current = self.snapshot[1]
        if refs == current and self.current():
            record["checkpoint"] = {"mode": "reused", "reused_commits": record["commits"], "new_commits": 0}
            return record, ()

        # External engines consume batches which may include adjacent fragments. Keep their
        # complete-scan semantics when refs change. Also retain findings by scanning from scratch
        # whenever the previous scan had any, even if a person accepted all of them.
        if self.engines or record.get("findings") or record.get("check_status") != "passed":
            return None, ()
        if not refs or not refs.keys() <= current.keys():
            return None, ()
        tips = set()
        for ref, old in refs.items():
            if not isinstance(old, str) or not _OID.fullmatch(old):
                return None, ()
            new = current[ref]
            if git_output(self.repo, ["cat-file", "-t", old]).strip() != "commit":
                return None, ()
            if old != new and run_git(self.repo, ["merge-base", "--is-ancestor", old, new]).returncode:
                return None, ()
            tips.add(old)
        self.previous = record
        return None, tuple(sorted(tips))

    def finish(self, record, scanned_refs, baseline):
        new = record["commits"]
        reused = self.previous["commits"] if baseline else 0
        if reused:
            for key in ("commits", "files", "archives"):
                record[key] += self.previous[key]
        record["checkpoint"] = {"mode": "incremental" if baseline else "full",
                                "reused_commits": reused, "new_commits": new}
        if record["coverage"] != "complete-for-selected-checks" or not self.current(scanned_refs):
            return
        refs = self.snapshot[1]
        with closing(self._connect()) as connection, connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS history_v1 (
                               checkout TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                               refs TEXT NOT NULL, report TEXT NOT NULL)""")
            connection.execute("""INSERT INTO history_v1 VALUES (?, ?, ?, ?)
                               ON CONFLICT(checkout) DO UPDATE SET fingerprint=excluded.fingerprint,
                               refs=excluded.refs, report=excluded.report""",
                               (self.key, self.snapshot[0], json.dumps(refs), json.dumps(record)))


CACHE_ERRORS = (CommandFailed, OSError, ValueError, KeyError, TypeError)
if SQLITE_AVAILABLE:
    CACHE_ERRORS += (sqlite3.Error,)
