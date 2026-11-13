"""A read-only security audit of chosen repositories: working files and every commit, masked.

Why:          before a repository is published, everything ever committed matters, not only what
              is about to be pushed. The web view needs that for a whole organization at once,
              with progress, without blocking the page.
Reads:        each chosen repository's working files and every commit reachable from its local
              refs; the shared security policy; optionally installed secret-scanning engines.
May change:   nothing. No fetch, no report file, no settings; results live in memory only.
Results:      per checkout, the same masked records the terminal scans print; job progress.
Layer:        Special: this machine, once.
Status:       working

The audit accepts repository ids the observer already knows, never a path from a client.
Engines are used only when asked for and installed; a missing one is a coverage gap, never a
silent pass. Nothing here installs anything.
"""
from __future__ import annotations

import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

from Basic._objects import git_output
from Basic._run import CommandFailed
from Special._settings import SECURITY_ENGINES, SettingsError, select_home
from Special._security._material import scan
from Special._security._me import load_policy

MAX_REPOSITORIES = 1000
#: What each optional engine adds, in plain words, and where it comes from (shown, never run).
ENGINE_NOTES = {
    "gitleaks": ("Gitleaks 8", "A widely used rule set for keys and tokens in files and history.",
                 "https://github.com/gitleaks/gitleaks"),
    "betterleaks": ("Betterleaks 1", "The successor to Gitleaks, by its original author; version 1 reports "
                    "in the same form as Gitleaks. Version 2 is not supported yet.",
                    "https://github.com/betterleaks/betterleaks"),
    "trufflehog": ("TruffleHog 3", "Hundreds of credential detectors; run here without checking "
                   "found credentials against their providers.", "https://github.com/trufflesecurity/trufflehog"),
}


def engines_status() -> list[dict]:
    """Which optional engines are installed on this machine (on PATH). Only looks."""
    return [{"engine": name, "label": ENGINE_NOTES[name][0], "about": ENGINE_NOTES[name][1],
             "home_page": ENGINE_NOTES[name][2], "installed": shutil.which(name) is not None}
            for name in SECURITY_ENGINES]


def _without_path(record: dict) -> dict:
    """The web view gets findings, not where the library lives on disk."""
    record.pop("repository", None)
    return record


def audit_checkout(repo, *, history=True, engines=(), settings_home=None, expected_settings=None) -> dict:
    """One checkout: working files, then (optionally) every reachable commit. Never clearance."""
    result = {"schema_version": 1, "scope": "local-audit", "action_clearance": False,
              "observed_at": datetime.now(timezone.utc).isoformat(), "check_status": "incomplete",
              "working_tree": None, "history": None, "gaps": []}
    try:
        home = select_home(settings_home, component="security")[0]
        if expected_settings is not None:
            expected_settings.verify()
            if home.resolve() != expected_settings.home.resolve():
                raise SettingsError("selected common profile changed")
        repo = Path(repo).absolute()
        if Path(git_output(repo, ["rev-parse", "--show-toplevel"]).strip()).resolve() != repo.resolve():
            raise ValueError("select root")
        policy = load_policy(repo, home=home)
        tree = scan(repo, policy, material="tree", engines=list(engines))
        result["working_tree"] = _without_path(tree.record())
        statuses = [tree.check_status]
        if history:
            past = scan(repo, policy, material="history", engines=list(engines))
            result["history"] = _without_path(past.record())
            statuses.append(past.check_status)
        if any(item.get("severity") == "high"
               for record in (result["working_tree"], result["history"]) if record
               for item in record.get("findings", [])):
            statuses.append("blocked")  # a scan with gaps reports itself incomplete; the finding still stands
        # A known high-severity finding outranks "not everything could be checked": the person
        # must see "blocked" first, with the gaps listed alongside.
        result["check_status"] = next((status for status in ("blocked", "incomplete", "review-required")
                                       if status in statuses), "passed")
    except (SettingsError, CommandFailed, OSError, ValueError):
        result["gaps"].append({"where": "audit", "reason": "Security scope, policy or material could not be checked; no clearance."})
        result["check_status"] = "incomplete"
    return result


def _payload(payload) -> tuple[list[str], bool, list[str]]:
    if not isinstance(payload, dict) or not set(payload) <= {"repo_ids", "history", "engines"}:
        raise ValueError("send repo_ids, and optionally history and engines")
    ids = payload.get("repo_ids")
    if (not isinstance(ids, list) or not ids or len(ids) > MAX_REPOSITORIES
            or any(not isinstance(item, str) or not item for item in ids) or len(set(ids)) != len(ids)):
        raise ValueError(f"choose between 1 and {MAX_REPOSITORIES} distinct repositories")
    history = payload.get("history", True)
    engines = payload.get("engines", [])
    if not isinstance(history, bool):
        raise ValueError("history must be true or false")
    if (not isinstance(engines, list) or len(set(engines)) != len(engines)
            or any(item not in SECURITY_ENGINES for item in engines)):
        raise ValueError("engines must be distinct names from: " + ", ".join(SECURITY_ENGINES))
    return ids, history, engines


class AuditJobs:
    """One audit at a time, kept in memory for the local web view: progress, then results.

    `checkouts(repo_id)` yields this machine's observed copies of a repository; ids it does not
    know are reported as such, never resolved from anything the client sent."""

    def __init__(self, checkouts, *, settings=lambda: (None, None), runner=audit_checkout):
        self.checkouts = checkouts
        self.settings = settings
        self.runner = runner
        self.lock = threading.Lock()
        self.job = None
        self.serial = 0

    def start(self, payload) -> dict:
        ids, history, engines = _payload(payload)
        with self.lock:
            if self.job and self.job["state"] == "running":
                raise ValueError("an audit is already running; stop it or wait for it")
            self.serial += 1
            self.job = {"id": self.serial, "state": "running", "history": history, "engines": engines,
                        "total": len(ids), "done": 0, "current": None, "results": [], "stop": False,
                        "started_at": datetime.now(timezone.utc).isoformat(), "finished_at": None}
            job = self.job
        threading.Thread(target=self._run, args=(job, ids), name="security-audit", daemon=True).start()
        return self.status()

    def _run(self, job, ids):
        home, expected = self.settings()
        for repo_id in ids:
            if job["stop"]:
                job["state"] = "stopped"
                break
            job["current"] = repo_id
            try:
                paths = list(self.checkouts(repo_id) or [])
            except (OSError, ValueError, KeyError):
                paths = []
            if not paths:
                job["results"].append({"repo_id": repo_id, "checkout": 0, "security": {
                    "check_status": "incomplete", "working_tree": None, "history": None,
                    "gaps": [{"where": "audit", "reason": "No checkout of this repository on this machine."}]}})
            for number, path in enumerate(paths, 1):
                record = self.runner(path, history=job["history"], engines=job["engines"],
                                     settings_home=home, expected_settings=expected)
                job["results"].append({"repo_id": repo_id, "checkout": number, "security": record})
            job["done"] += 1
        else:
            job["state"] = "finished"
        job["current"] = None
        job["finished_at"] = datetime.now(timezone.utc).isoformat()

    def status(self, payload=None) -> dict:
        with self.lock:
            if self.job is None:
                return {"audit": None}
            view = {key: value for key, value in self.job.items() if key not in ("stop", "results")}
            view["results"] = list(self.job["results"])
            return {"audit": view}

    def stop(self, payload=None) -> dict:
        with self.lock:
            if self.job and self.job["state"] == "running":
                self.job["stop"] = True
        return self.status()
