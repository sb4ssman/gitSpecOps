"""A read-only security audit of chosen repositories: working files and every commit, masked.

Why:          before a repository is published, everything ever committed matters, not only what
              is about to be pushed. The web view needs that for a whole organization at once,
              with progress, without blocking the page.
Reads:        each chosen repository's working files and every commit reachable from its local
              refs; the shared security policy; optionally installed secret-scanning engines.
May change:   browser audits can save masked history after opt-in in the private settings profile.
Results:      per checkout, the same masked records the terminal scans print; job progress.
Layer:        Special: this machine, once.
Status:       working

The audit accepts repository ids the observer already knows, never a path from a client.
Engines are used only when asked for and installed; a missing one is a coverage gap, never a
silent pass. Nothing here installs anything.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import mmap
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

from _os.current import process as child_process

from Basic._objects import git_output
from Basic._paths import find_program
from Basic._run import CommandFailed
from Special._settings import SECURITY_ENGINES, SettingsError, resolve_settings, select_home
from Special._security._history_cache import CACHE_ERRORS, SQLITE_AVAILABLE, Checkpoint
from Special._security._material import scan
from Special._security._me import load_policy

MAX_REPOSITORIES = 1000
MAX_RUNNERS = 8
#: What each optional engine adds, in plain words, and where it comes from (shown, never run).
ENGINE_NOTES = {
    "gitleaks": ("Gitleaks 8", "A widely used rule set for keys and tokens in files and history.",
                 "https://github.com/gitleaks/gitleaks"),
    "betterleaks": ("Betterleaks 1", "From the makers of Gitleaks, including its original author; version 1 reports "
                    "in the same form as Gitleaks. Version 2 is not supported yet.",
                    "https://github.com/betterleaks/betterleaks"),
    "trufflehog": ("TruffleHog 3", "Hundreds of credential detectors; run here without checking "
                   "found credentials against their providers.", "https://github.com/trufflesecurity/trufflehog"),
}


#: Each engine's package with each system's package tool. Suggested to the person, never run here.
INSTALL_PACKAGES = {
    "gitleaks": {"winget": "Gitleaks.Gitleaks", "brew": "gitleaks", "apt": "gitleaks"},
    "betterleaks": {"winget": "Betterleaks.Betterleaks", "brew": "betterleaks"},
    "trufflehog": {"brew": "trufflehog"},
}


def install_suggestion(engine: str) -> str | None:
    """The command that installs `engine` on this system, to show; None when there is none."""
    tool = ("winget" if sys.platform == "win32" else "brew" if sys.platform == "darwin"
            else "apt" if shutil.which("apt-get") else "")
    package = INSTALL_PACKAGES.get(engine, {}).get(tool)
    if not package or not shutil.which("apt-get" if tool == "apt" else tool):
        return None
    return {"winget": f"winget install --id {package} --exact", "brew": f"brew install {package}",
            "apt": f"sudo apt-get install {package}"}[tool]


def engines_status() -> list[dict]:
    """Which optional engines are installed on this machine (on PATH), and how to install a
    missing one here. Only looks."""
    status = []
    for name in SECURITY_ENGINES:
        installed = find_program(name) is not None
        status.append({"engine": name, "label": ENGINE_NOTES[name][0], "about": ENGINE_NOTES[name][1],
                       "home_page": ENGINE_NOTES[name][2], "installed": installed,
                       "install": None if installed else install_suggestion(name)})
    return status


def _without_path(record: dict) -> dict:
    """The web view gets findings, not where the library lives on disk."""
    record.pop("repository", None)
    return record


def audit_checkout(repo, *, history=True, engines=(), settings_home=None, expected_settings=None,
                   values: dict | None = None, step=None, cache=False, fresh=False, history_workers=1) -> dict:
    """One checkout: working files, then (optionally) every reachable commit. Never clearance.
    `step(text)` hears each phase as it starts, for the page's status line (2026-11-17)."""
    step = step or (lambda _text: None)
    result = {"scope": "local-audit", "action_clearance": False,
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
        scanners = " and ".join(["built-in checks", *engines])
        step(f"working files ({scanners})")
        tree = scan(repo, policy, material="tree", engines=list(engines))
        step("preparing the masked working-file report")
        result["working_tree"] = _without_path(tree.record())
        # Each finding's real value, in finding order, into the caller's own holder (never the
        # masked result): the person at this machine may reveal one at a time (the user, 2026-11-16).
        if values is not None:
            values["working_tree"] = [finding.value for finding in tree.findings]
            # The full private reports, for Accept (a review needs one): memory only until used.
            values["reports"] = {"working_tree": tree.record(redacted=False)}
        statuses = [tree.check_status]
        if history:
            if cache is None:
                cache = resolve_settings(home=home).values["security"]["audit_history_cache"]
            past, masked = _audit_history(repo, home, policy, engines, scanners, step, cache, fresh, history_workers)
            result["history"] = masked
            if values is not None and past is not None and past.findings:
                values["history"] = [finding.value for finding in past.findings]
                values["reports"]["history"] = past.record(redacted=False)
            statuses.append(masked["check_status"])
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


def _audit_history(repo, home, policy, engines, scanners, step, cache, fresh, workers):
    checkpoint, baseline = None, ()
    if cache and SQLITE_AVAILABLE:
        step("checking local history coverage")
        try:
            checkpoint = Checkpoint(repo, home, policy, engines)
            checkpoint.refresh_batches = fresh
        except CACHE_ERRORS:
            pass
        if checkpoint is not None and not fresh:
            try:
                record, baseline = checkpoint.lookup()
                if record is not None:
                    return None, record
            except CACHE_ERRORS:
                pass  # A full scan can recreate an uninitialized database.

    if baseline:
        step(f"commits outside the saved history ({scanners})")
        past = scan(repo, policy, material="history", engines=list(engines), _audit_baseline=baseline,
                    _audit_workers=workers, _audit_receipts=checkpoint if not engines else None)
        try:
            still_current = checkpoint.current(past.refs)
        except CACHE_ERRORS:
            still_current = False
        if not still_current:
            baseline, checkpoint = (), None
    if not baseline:
        commits = git_output(repo, ["rev-list", "--all", "--count"]).strip()
        step(f"every commit: {commits} commits ({scanners})")
        past = scan(repo, policy, material="history", engines=list(engines), _audit_workers=workers,
                    _audit_receipts=checkpoint if not engines else None)
    step("preparing the masked history report")
    record = _without_path(past.record())
    if checkpoint is not None:
        try:
            checkpoint.finish(record, past.refs, baseline)
        except CACHE_ERRORS:
            pass  # The audit result stands even when its optional cache is unavailable.
    return past, record


ROOT = Path(__file__).resolve().parents[2]
#: Open findings sent to the page per part (files, history) of one checkout. FlowNode's history
#: held 18,640, and sending them all on every refresh froze the page (2026-11-17).
SHOWN = 300


def _trimmed(entry: dict) -> dict:
    """One result as the page polls it: open findings first, at most SHOWN per part, with the
    true count beside them. Finding ids stay the same, so Show and Accept still find them."""
    security = dict(entry["security"])
    for material in ("working_tree", "history"):
        record = security.get(material)
        if not record:
            continue
        findings = record.get("findings") or []
        open_ = [f for f in findings if f.get("classification") != "quiet" and not f.get("review_id")]
        security[material] = {**record, "findings": open_[:SHOWN], "findings_open": len(open_)}
    return {**entry, "security": security}


def audit_in_process(repo, *, history=True, engines=(), settings_home=None, expected_settings=None,
                     values: dict | None = None, should_stop=None, step=None, fresh=False, history_workers=1,
                     worker_budget=None) -> dict:
    """The same audit in a process of its own (2026-11-17): a large history (FlowNode: 1,547
    commits) took the app's process for many minutes, so the page stopped answering and looked
    crashed. Now the app keeps answering whatever a repository takes, Stop ends the audit at
    once, and nothing a repository holds can take the app down. Values come back on a pipe."""
    options = dict(history=history, engines=engines, settings_home=settings_home, values=values,
                   should_stop=should_stop, step=step, fresh=fresh, history_workers=history_workers)
    if worker_budget is None:
        return _run_audit_worker(repo, **options)
    descriptor, filename = tempfile.mkstemp(prefix="gitso-audit-budget-")
    try:
        with os.fdopen(descriptor, "w+b") as file:
            file.write(bytes([worker_budget()]))
            file.flush()
            with mmap.mmap(file.fileno(), 1) as capacity:
                return _run_audit_worker(repo, **options, worker_budget=worker_budget,
                                         budget_file=filename, capacity=capacity)
    finally:
        Path(filename).unlink(missing_ok=True)


def _run_audit_worker(repo, *, history, engines, settings_home, values, should_stop, step, fresh,
                      history_workers, worker_budget=None, budget_file=None, capacity=None):
    import json
    import subprocess

    argv = [sys.executable, "-m", "Special._security._audit", str(repo), "--history", "1" if history else "0"]
    for engine in engines or ():
        argv += ["--engine", engine]
    if settings_home:
        argv += ["--settings-home", str(settings_home)]
    if fresh:
        argv.append("--fresh")
    argv += ["--history-workers", str(history_workers)]
    if budget_file is not None:
        argv += ["--worker-budget-file", budget_file]
    child = subprocess.Popen(argv, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             stdin=subprocess.DEVNULL, **child_process.spawn_options())
    errors: list[bytes] = []

    def listen():
        # The child's phases arrive on stderr as "STEP <text>" lines; anything else is kept for
        # the message if it fails.
        for line in child.stderr:
            if line.startswith(b"STEP "):
                if step is not None:
                    step(line[5:].decode("utf-8", "replace").strip())
            else:
                errors.append(line)
    listener = threading.Thread(target=listen, daemon=True)
    listener.start()
    reader = threading.Thread(target=lambda: setattr(child, "answer", (child.stdout.read(), child.wait())), daemon=True)
    reader.start()
    while reader.is_alive():
        if capacity is not None:
            capacity[0] = worker_budget()
        if should_stop is not None and should_stop():
            child_process.kill_tree(child)
            reader.join(10)
            listener.join(5)
            for pipe in (child.stdout, child.stderr):
                pipe.close()
            return {"scope": "local-audit", "action_clearance": False, "check_status": "incomplete",
                    "observed_at": datetime.now(timezone.utc).isoformat(), "working_tree": None,
                    "history": None, "gaps": [{"where": "audit", "reason": "Stopped before it finished."}]}
        reader.join(0.5)
    listener.join(5)
    for pipe in (child.stdout, child.stderr):
        pipe.close()
    out, err = getattr(child, "answer", (b"", None))[0], b"".join(errors)
    try:
        answer = json.loads(out.decode("utf-8"))
    except ValueError:
        tail = (err or b"").decode("utf-8", "replace").strip().splitlines()[-1:] or ["no answer"]
        return {"scope": "local-audit", "action_clearance": False, "check_status": "incomplete",
                "observed_at": datetime.now(timezone.utc).isoformat(), "working_tree": None, "history": None,
                "gaps": [{"where": "audit", "reason": f"The audit stopped unexpectedly ({tail[0][:200]}); no clearance."}]}
    if values is not None:
        values.update(answer.get("values") or {})
    return answer["result"]


def _payload(payload) -> tuple[list[str], bool, list[str], int, bool]:
    if not isinstance(payload, dict) or not set(payload) <= {"repo_ids", "history", "engines", "runners", "fresh"}:
        raise ValueError("send repo_ids and optional audit settings")
    fresh = payload.get("fresh", False)
    if type(fresh) is not bool:
        raise ValueError("fresh must be true or false")
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
    runners = payload.get("runners", 1)
    if type(runners) is not int or not 1 <= runners <= MAX_RUNNERS:
        raise ValueError(f"choose between 1 and {MAX_RUNNERS} simultaneous runners")
    return ids, history, engines, runners, fresh


def coverage_receipt(audit, machine_id, secret=None):
    """Build an allowlisted snapshot. Shared data never becomes a local scan checkpoint.

    When `secret` is given, the receipt is HMAC-signed so a receiving machine can
    verify it came from the expected sender and was not altered in transit.
    """
    checkouts = []
    for entry in audit["results"]:
        result = entry["security"]
        # Observer IDs are opaque hex. Never put a path, an organization or a name in this file.
        if not re.fullmatch(r"[0-9a-f]{32}", entry["repo_id"]):
            continue
        coverage = {"repository_id": entry["repo_id"], "checkout": entry["checkout"],
                    "status": result["check_status"], "audit_gaps": len(result.get("gaps") or [])}
        for material in ("working_tree", "history"):
            record = result.get(material)
            if record:
                checkpoint = record.get("checkpoint", {})
                coverage[material] = {"coverage": record["coverage"], "commits": record["commits"],
                                      "gaps": len(record.get("gaps") or []),
                                      "commits_reused": checkpoint.get("reused_commits", 0),
                                      "commits_scanned": checkpoint.get("new_commits", record["commits"])}
        checkouts.append(coverage)
    receipt = {"schema_version": 1, "kind": "gitso-audit-coverage", "action_clearance": False,
               "machine_id": machine_id, "started_at": audit["started_at"], "finished_at": audit["finished_at"],
               "state": audit["state"], "engines": audit["engines"], "history_selected": audit["history"],
               "repositories_selected": audit["total"], "repositories_finished": audit["done"], "checkouts": checkouts}
    if secret:
        signature = hmac.new(secret.encode("utf-8"),
                             json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                             hashlib.sha256).hexdigest()
        receipt["signature"] = signature
    return receipt


def verify_coverage_receipt(receipt, secret):
    """Verify an HMAC-signed coverage receipt. Returns True if the signature is valid."""
    if not secret:
        return False
    provided = receipt.get("signature")
    if not provided or not isinstance(provided, str):
        return False
    unsigned = {k: v for k, v in receipt.items() if k != "signature"}
    expected = hmac.new(secret.encode("utf-8"),
                        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided, expected)


class AuditJobs:
    """One audit at a time, kept in memory for the local web view: progress, then results.

    `checkouts(repo_id)` yields this machine's observed copies of a repository; ids it does not
    know are reported as such, never resolved from anything the client sent."""

    def __init__(self, checkouts, *, settings=lambda: (None, None), runner=audit_in_process):
        self.checkouts = checkouts
        self.settings = settings
        self.runner = runner
        self.lock = threading.Lock()
        self.job = None
        self.serial = 0

    def start(self, payload) -> dict:
        ids, history, engines, runners, fresh = _payload(payload)
        with self.lock:
            if self.job and self.job["state"] == "running":
                raise ValueError("an audit is already running; stop it or wait for it")
            self.serial += 1
            self.job = {"id": self.serial, "state": "running", "history": history, "engines": engines,
                        "total": len(ids), "done": 0, "results": [], "stop": False,
                        "runners": runners, "fresh": fresh, "active": {}, "values": [],
                        "started_at": datetime.now(timezone.utc).isoformat(), "finished_at": None}
            job = self.job
        threading.Thread(target=self._run, args=(job, ids), name="security-audit", daemon=True).start()
        return self.status()

    def _run(self, job, ids):
        try:
            home, expected = self.settings()
            with ThreadPoolExecutor(max_workers=job["runners"], thread_name_prefix="audit-repository") as pool:
                for _ in pool.map(lambda repo_id: self._audit_repo(job, repo_id, home, expected), ids):
                    pass
        except Exception:  # noqa: BLE001 - an unexpected runner failure must finish the job
            with self.lock:
                job["error"] = "The audit could not complete every repository."
        finally:
            with self.lock:
                job["state"] = "stopped" if job["stop"] else "failed" if job.get("error") else "finished"
                job["finished_at"] = datetime.now(timezone.utc).isoformat()

    def _audit_repo(self, job, repo_id, home, expected):
        with self.lock:
            if job["stop"]:
                return
            phase = {"repo_id": repo_id, "copy": None, "step": "starting", "step_at": time.monotonic()}
            job["active"][repo_id] = phase

        def update_step(text):
            with self.lock:
                phase.update(step=text, step_at=time.monotonic())

        def worker_budget():
            with self.lock:
                unfinished = max(1, job["total"] - job["done"])
                return max(1, job["runners"] // unfinished)

        def add_result(number, result, found, checkout_name=None):
            with self.lock:
                index = len(job["results"])
                job["values"].append(found)
                entry = {"repo_id": repo_id, "checkout": number, "index": index, "security": result}
                if checkout_name:
                    entry["checkout_name"] = checkout_name
                job["results"].append(entry)

        def incomplete(reason):
            return {"check_status": "incomplete", "working_tree": None, "history": None,
                    "gaps": [{"where": "audit", "reason": reason}]}

        try:
            try:
                paths = list(self.checkouts(repo_id) or [])
            except (OSError, ValueError, KeyError):
                paths = []
            if not paths:
                add_result(0, incomplete("No checkout of this repository on this machine."), {})
            for number, path in enumerate(paths, 1):
                with self.lock:
                    if job["stop"]:
                        return
                    phase.update(step="starting", step_at=time.monotonic(),
                                 copy=number if len(paths) > 1 else None)
                found = {}
                try:
                    result = self.runner(path, history=job["history"], engines=job["engines"],
                                         history_workers=1, worker_budget=worker_budget,
                                         settings_home=home, expected_settings=expected, values=found,
                                         should_stop=lambda: job["stop"], step=update_step, fresh=job["fresh"])
                except (OSError, ValueError, RuntimeError):
                    result = incomplete("The audit worker could not complete this checkout.")
                    found = {}
                add_result(number, result, found, Path(path).name if len(paths) > 1 else None)
            with self.lock:
                if not job["stop"]:
                    job["done"] += 1
        finally:
            with self.lock:
                job["active"].pop(repo_id, None)

    def status(self, payload=None, *, full=False) -> dict:
        with self.lock:
            if self.job is None:
                return {"audit": None}
            view = {key: value for key, value in self.job.items() if key not in ("stop", "active", "results", "values")}
            now = time.monotonic()
            active = [{"repo_id": phase["repo_id"], "copy": phase["copy"], "step": phase["step"],
                       "step_seconds": int(now - phase["step_at"])} for phase in self.job["active"].values()]
            first = active[0] if active else {}
            view.update(active=active, current=first.get("repo_id"), copy=first.get("copy"),
                        step=first.get("step"), step_seconds=first.get("step_seconds"))
            view["results"] = (
                [{key: value for key, value in entry.items() if key != "checkout_name"} for entry in self.job["results"]]
                if full else [_trimmed(entry) for entry in self.job["results"]]
            )
            return {"audit": view}

    def _check_finding_request(self, payload):
        fields = {"index", "material", "finding_id"}
        if not isinstance(payload, dict) or set(payload) not in (fields, fields | {"audit_started_at"}):
            raise ValueError("send index, material and finding_id")

    def _check_current_audit(self, payload):
        if "audit_started_at" in payload and (not self.job or self.job["started_at"] != payload["audit_started_at"]):
            raise ValueError("this finding belongs to an earlier audit; reload the results")

    def reveal(self, payload) -> dict:
        """One finding's unmasked value, for the person at this machine's own page. Answered from
        memory (the audit just run), only through the local, token-checked actions; never logged,
        never published, gone when the app restarts."""
        self._check_finding_request(payload)
        index, material, finding_id = payload["index"], payload["material"], payload["finding_id"]
        if (type(index) is not int or material not in ("working_tree", "history")
                or not isinstance(finding_id, str) or not finding_id.startswith("finding-")
                or not finding_id[8:].isdigit()):
            raise ValueError("that finding is not in this audit")
        with self.lock:
            self._check_current_audit(payload)
            values = (self.job or {}).get("values", [])
            found = values[index].get(material, []) if 0 <= index < len(values) else []
            number = int(finding_id[8:]) - 1
            if not 0 <= number < len(found):
                raise ValueError("that finding is not in this audit")
            return {"value": found[number]}

    def accept(self, payload) -> dict:
        """Accept one finding as reviewed (the user, 2026-11-17), the way `gitso review` does: the
        audit's full report is saved once to private storage in the security profile, then the
        review is planned and applied. Only what a review may accept is accepted (a binary file,
        an uncertain example); anything else is refused with the reason."""
        self._check_finding_request(payload)
        index, material, finding_id = payload["index"], payload["material"], payload["finding_id"]
        with self.lock:
            self._check_current_audit(payload)
            values = (self.job or {}).get("values", [])
            report = (values[index].get("reports") or {}).get(material) if type(index) is int and 0 <= index < len(values) else None
        if not report or not isinstance(finding_id, str):
            raise ValueError("that finding is not in this audit")
        from Special._security._private_files import write_private_json
        from Special._security._review_operation import review_finding
        from Special._settings import select_home
        home = select_home(self.settings()[0], component="security")[0]
        path = Path(home) / "audit-reports" / f"{report['scan_id']}.json"
        if not path.exists():
            write_private_json(path, report)
        reason = "Accepted on the Security page"
        plan = review_finding(path, finding_id, reason, home=home)
        if plan.status != "planned":
            return {"status": plan.status, "message": plan.message, "review_id": plan.review_id}
        done = review_finding(path, finding_id, reason, home=home, apply=True, approve=plan.plan_id)
        return {"status": done.status, "message": done.message, "review_id": done.review_id}

    def stop(self, payload=None) -> dict:
        with self.lock:
            if self.job and self.job["state"] == "running":
                self.job["stop"] = True
        return self.status()


def _main(argv=None) -> int:
    """The child side of audit_in_process: audit one checkout, answer in JSON on stdout."""
    import argparse
    import json
    parser = argparse.ArgumentParser()
    parser.add_argument("repo")
    parser.add_argument("--history", default="1")
    parser.add_argument("--engine", action="append", default=[])
    parser.add_argument("--settings-home")
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--history-workers", type=int, choices=range(1, MAX_RUNNERS + 1), default=1)
    parser.add_argument("--worker-budget-file", type=Path)
    args = parser.parse_args(argv)
    values: dict = {}

    def step(text):
        sys.stderr.write(f"STEP {text}\n")
        sys.stderr.flush()
    with ExitStack() as resources:
        workers = args.history_workers
        if args.worker_budget_file:
            file = resources.enter_context(args.worker_budget_file.open("rb"))
            capacity = resources.enter_context(mmap.mmap(file.fileno(), 1, access=mmap.ACCESS_READ))
            workers = lambda: max(1, min(MAX_RUNNERS, capacity[0]))
        result = audit_checkout(args.repo, history=args.history == "1", engines=args.engine,
                                settings_home=args.settings_home, values=values, step=step, cache=None,
                                fresh=args.fresh, history_workers=workers)
    sys.stdout.write(json.dumps({"result": result, "values": values}) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
