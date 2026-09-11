"""SQLite state owned by the foreground fleet host, never opened across a network share."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from aggregate import parse_timestamp
from manifest import validate_manifest

MAX_REPORT_BYTES = 8 * 1024 * 1024


def validate_report(report: dict, machine_id: str, fleet_id: str) -> dict:
    if not isinstance(report, dict) or set(report) != {"manifest", "names", "issues"}:
        raise ValueError("report must contain manifest, names and issues")
    manifest = validate_manifest(report["manifest"])
    if manifest["machine_id"] != machine_id or manifest["fleet_id"] != fleet_id:
        raise ValueError("report does not belong to this device and fleet")
    now = datetime.now(timezone.utc)
    moment = parse_timestamp(manifest["observed_at"])
    if moment is None or (moment - now).total_seconds() > 60:
        raise ValueError("invalid or future observation time; check the device clock")
    seen = set()
    for repo in manifest["repositories"]:
        if repo["repo_id"] in seen:
            raise ValueError("multiple worktrees share an identity; select non-overlapping roots")
        seen.add(repo["repo_id"])
        for key in ("staged", "unstaged", "untracked", "stashes", "ahead", "behind"):
            value = repo.get(key)
            if value is None and key in ("ahead", "behind"):
                continue
            if type(value) is not int or value < 0:
                raise ValueError(f"invalid {key} count")
        if repo.get("operation") not in (None, "merge", "rebase", "cherry-pick", "revert", "bisect"):
            raise ValueError("invalid operation")
    names = report["names"]
    if not isinstance(names, dict) or set(names) != seen:
        raise ValueError("names must correspond exactly to observed repositories")
    for value in names.values():
        if not isinstance(value, dict) or set(value) != {"host", "owner", "name"}:
            raise ValueError("only repository host/owner/name may accompany live reports")
        if any(not isinstance(v, str) or not v or len(v) > 255 for v in value.values()):
            raise ValueError("invalid repository name")
    if not isinstance(report["issues"], list) or len(report["issues"]) > 1000:
        raise ValueError("invalid observation issues")
    if any(not isinstance(v, str) or len(v) > 500 for v in report["issues"]):
        raise ValueError("invalid observation issue")
    return report


class FleetStore:
    def __init__(self, path: Path, fleet_id: str):
        self.path, self.fleet_id = Path(path), fleet_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS reports (machine_id TEXT PRIMARY KEY, "
                       "observed_at TEXT NOT NULL, received_at TEXT NOT NULL, body TEXT NOT NULL)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def put(self, machine_id: str, report: dict):
        validate_report(report, machine_id, self.fleet_id)
        observed = report["manifest"]["observed_at"]
        with self.connect() as db:
            old = db.execute("SELECT observed_at FROM reports WHERE machine_id=?",
                             (machine_id,)).fetchone()
            if old and parse_timestamp(observed) < parse_timestamp(old[0]):
                raise ValueError("older report refused; current state was retained")
            db.execute("INSERT OR REPLACE INTO reports VALUES (?, ?, ?, ?)",
                       (machine_id, observed, datetime.now(timezone.utc).isoformat(),
                        json.dumps(report)))

    def touch(self, machine_id: str, observed_at: str):
        """Record a tiny authenticated liveness heartbeat without replacing report content."""
        moment = parse_timestamp(observed_at)
        now = datetime.now(timezone.utc)
        if moment is None or (moment - now).total_seconds() > 60:
            raise ValueError("invalid or future heartbeat time; check the device clock")
        with self.connect() as db:
            current = db.execute("SELECT observed_at FROM reports WHERE machine_id=?",
                                 (machine_id,)).fetchone()
            if current is None:
                raise ValueError("a report is required before heartbeat")
            if moment < parse_timestamp(current[0]):
                raise ValueError("older heartbeat refused")
            db.execute("UPDATE reports SET observed_at=?, received_at=? WHERE machine_id=?",
                       (observed_at, now.isoformat(), machine_id))

    def reports(self):
        with self.connect() as db:
            reports = []
            for observed_at, body in db.execute(
                    "SELECT observed_at, body FROM reports ORDER BY machine_id"):
                report = json.loads(body)
                # The stored body changes only with repository facts; liveness has its own
                # small column update and is overlaid for freshness calculations here.
                report["manifest"]["observed_at"] = observed_at
                reports.append(report)
            return reports
