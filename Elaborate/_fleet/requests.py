"""Requests between machines: "please fast-forward these", "please clone this". Asked on one
machine's page, answered on the other's.

Why:          syncing a fleet from one screen (the user, 2026-11-16) without breaking the rule that
              machines only read from each other. A request is published like a report: the asking
              machine serves its outgoing requests (GET /v1/requests); each machine pulls them on
              its round and keeps the ones addressed to it. A request can only ask for the two
              operations that cannot lose work (a fast-forward after a fresh fetch; a clone that
              replaces nothing), and only a machine of the same fleet can send one, so the
              receiving machine runs it on arrival (the user, 2026-11-17: remote management
              without walking to the other machine). `auto_requests: false` in the app's
              settings makes it wait for Apply on that machine's page instead.
Reads:        this machine's requests-out.json and requests-in.json in the fleet folder.
May change:   those two files only. Applying a request runs the existing safe operations
              (Special/_sync/actions.py): a fast-forward after a fresh fetch, a clone that never
              replaces anything.
Results:      the lists the page shows.
Layer:        Elaborate: other machines.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

KINDS = {"pull": "fast-forward", "clone": "clone"}
#: What a request can end as. "partial": some repositories done, some not; never shown as done.
ENDED = ("done", "partial", "failed", "dismissed")
#: What other machines are told about one repository: fixed sentences by outcome, never Git's
#: own words (they can hold paths and addresses; an outside review, 2026-11-17). The detail stays
#: in this machine's tasks.log.
OUTCOMES = {
    "pulled": (True, "fast-forwarded"), "current": (True, "already current"),
    "cloned": (True, "cloned"), "exists": (True, "already there, left as it is"),
    "dirty": (False, "has uncommitted work, so it was not moved"),
    "diverged": (False, "has commits on both sides; it needs a person"),
    "ahead": (False, "is ahead of its provider; nothing to pull"),
    "detached": (False, "is not on a branch"), "no_upstream": (False, "tracks no branch on a remote"),
    "fetch_failed": (False, "could not be fetched"), "pull_failed": (False, "could not be fast-forwarded"),
    "pull_needs_review": (False, "was pulled, but its state needs a look on that machine"),
    "clone_failed": (False, "could not be cloned"),
}
KEEP_DAYS = 7
MAX_ITEMS = 500


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _fresh(stamp: str) -> bool:
    try:
        return _now() - datetime.fromisoformat(stamp) < timedelta(days=KEEP_DAYS)
    except (TypeError, ValueError):
        return False


class RequestBook:
    def __init__(self, directory: Path, machine_id: str, label: str):
        self.out_path = Path(directory) / "requests-out.json"
        self.in_path = Path(directory) / "requests-in.json"
        self.machine_id, self.label = machine_id, label
        self.lock = threading.Lock()

    def _read(self, path: Path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return [] if path == self.out_path else {}

    def _write(self, path: Path, value) -> None:
        from Basic._files import atomic_write_bytes
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(path, json.dumps(value, indent=1).encode())

    # ---------------------------------------------------------------- asking
    def send(self, to: str, to_label: str, kind: str, items: list[dict]) -> dict:
        if kind not in KINDS:
            raise ValueError("a request is pull or clone")
        if not items or len(items) > MAX_ITEMS:
            raise ValueError("choose at least one repository")
        request = {"id": uuid.uuid4().hex[:16], "from": self.machine_id, "from_label": self.label,
                   "to": to, "to_label": to_label, "kind": kind, "items": items, "at": _now().isoformat()}
        with self.lock:
            sent = [item for item in self._read(self.out_path) if _fresh(item.get("at", ""))]
            sent.append(request)
            self._write(self.out_path, sent)
        return request

    def outgoing(self) -> list[dict]:
        with self.lock:
            return [item for item in self._read(self.out_path) if _fresh(item.get("at", ""))]

    def published(self) -> list[dict]:
        """What GET /v1/requests serves: this machine's requests, and its answers to the requests
        others sent it, so the asking machine learns what happened (the user, 2026-11-16)."""
        answers = [{"answer_for": item["id"], "from": self.machine_id, "to": item["from"],
                    "status": item["status"], "result": item.get("result", "")[:2000], "at": item["at"]}
                   for item in self.incoming() if item["status"] != "waiting"]
        return self.outgoing() + answers

    def log(self, event: str, request: dict, result: str = "") -> None:
        """The task log: every request sent, applied or dismissed, and every local run, one JSON
        line each, kept in the fleet folder (tasks.log). Names and counts; never a path."""
        line = {"at": _now().isoformat(), "event": event, "id": request.get("id"), "kind": request.get("kind"),
                "from": request.get("from_label") or request.get("from"), "to": request.get("to_label") or request.get("to"),
                "repositories": [item.get("name") or item.get("repo_id", "")[:8] for item in request.get("items", [])][:50],
                "result": result.splitlines()[:20]}
        try:
            with open(self.out_path.with_name("tasks.log"), "a", encoding="utf-8") as handle:
                handle.write(json.dumps(line) + "\n")
        except OSError:
            pass

    def withdraw(self, request_id: str) -> None:
        with self.lock:
            self._write(self.out_path, [item for item in self._read(self.out_path) if item.get("id") != request_id])

    def clear(self, everything_sent: bool = False) -> int:
        """Drop finished requests here: this machine's answered ones and the answers it gave; with
        `everything_sent`, also what it is still waiting on (stale requests, the user, 2026-11-16).
        The task log keeps the record. Returns how many were dropped."""
        with self.lock:
            sent = self._read(self.out_path)
            kept_sent = [] if everything_sent else [item for item in sent if item.get("status") not in ENDED]
            book = self._read(self.in_path)
            kept_in = {key: value for key, value in book.items() if value.get("status") in ("waiting", "running")}
            self._write(self.out_path, kept_sent)
            self._write(self.in_path, kept_in)
            return len(sent) - len(kept_sent) + len(book) - len(kept_in)

    # ---------------------------------------------------------------- answering
    def receive(self, requests, from_machine: str) -> int:
        """Keep the requests a machine publishes that are addressed here. Returns how many are new."""
        if not isinstance(requests, list):
            return 0
        added = 0
        with self.lock:
            # Answers to what this machine asked: kept on its own request, so its page says what
            # happened over there.
            sent = self._read(self.out_path)
            answered = False
            for item in requests:
                if (isinstance(item, dict) and item.get("answer_for") and item.get("to") == self.machine_id
                        and item.get("from") == from_machine):
                    for request in sent:
                        if request.get("id") == item["answer_for"] and request.get("status") != item.get("status"):
                            request.update(status=str(item.get("status"))[:20], result=str(item.get("result"))[:2000])
                            answered = True
            if answered:
                self._write(self.out_path, sent)
            book = self._read(self.in_path)
            for item in requests:
                if (not isinstance(item, dict) or item.get("to") != self.machine_id
                        or item.get("from") != from_machine or item.get("kind") not in KINDS
                        or not isinstance(item.get("items"), list) or not _fresh(item.get("at", ""))):
                    continue
                if item["id"] not in book:
                    book[item["id"]] = {**item, "status": "waiting", "result": ""}
                    added += 1
            book = {key: value for key, value in book.items() if _fresh(value.get("at", ""))}
            self._write(self.in_path, book)
        return added

    def incoming(self) -> list[dict]:
        with self.lock:
            return sorted(self._read(self.in_path).values(), key=lambda item: item.get("at", ""), reverse=True)

    def settle(self, request_id: str, status: str, result: str) -> dict:
        with self.lock:
            book = self._read(self.in_path)
            if request_id not in book:
                raise ValueError("that request is no longer here; reload")
            book[request_id].update(status=status, result=result[:2000])
            self._write(self.in_path, book)
            return book[request_id]


def _library_of(path, libraries: list[str]) -> str:
    from Special._sync.manifest import library_name
    resolved = Path(path).resolve()
    for root in libraries:
        base = Path(root).resolve()
        if resolved == base or base in resolved.parents:
            return library_name(root)
    return ""


def run_request(request: dict, local_checkouts, libraries: list[str]) -> str:
    """Do what a request asks; returns what happened, in words (see `perform`)."""
    return perform(request, local_checkouts, libraries)[1]


def perform(request: dict, local_checkouts, libraries: list[str], private=None) -> tuple[str, str]:
    """Do what a request asks, with the safe operations. Returns (status, public text):
    "done" when every repository ended well, "partial" when some did, "failed" when none did.
    The text is fixed sentences per repository; `private(name, detail)` receives Git's own words
    for this machine's log."""
    from Special._sync.actions import apply_catchup, apply_materialize, plan_catchup
    private = private or (lambda _name, _detail: None)
    good = bad = 0
    lines = []

    def say(name, action, detail=""):
        nonlocal good, bad
        ok, words = OUTCOMES.get(action, (False, action.replace("_", " ")))
        good, bad = good + ok, bad + (not ok)
        lines.append(f"{name}: {words}")
        if detail and not ok:
            private(name, detail)

    if request["kind"] == "pull":
        for item in request["items"]:
            name, wanted = str(item.get("name") or "a repository"), str(item.get("library") or "")
            paths = list(local_checkouts(item.get("repo_id", "")) or [])
            if wanted:
                # Only the copy in the library the asking page's column named.
                paths = [path for path in paths if _library_of(path, libraries) == wanted]
            if not paths:
                bad += 1
                lines.append(f"{name}: no copy here" + (f" in {wanted}" if wanted else ""))
                continue
            for result in apply_catchup(plan_catchup(paths)):
                say(name, result["action"], result.get("detail", ""))
        return _status(good, bad), "\n".join(lines)
    for item in request["items"]:
        host, owner, name, folder, wanted = (str(item.get(key) or "") for key in (
            "host", "owner", "name", "folder", "library"))
        if not all(part and "/" not in part and "\\" not in part and ".." not in part for part in (host, owner, name)):
            bad += 1
            lines.append(f"{name or 'a repository'}: its name is not known here (the asking machine withholds names)")
            continue
        if folder and any(mark in folder for mark in ("/", "\\", "..", ":")):
            bad += 1
            lines.append(f"{name}: the folder it names is not a plain folder name, so nothing was cloned")
            continue
        # The library the asking page's column named (one machine may keep several); the first
        # library when it names none.
        from Special._sync.manifest import library_name
        chosen = [root for root in libraries if library_name(root, libraries) == wanted] if wanted else libraries[:1]
        if not chosen:
            bad += 1
            lines.append(f"{name}: no library called {wanted} here, so nothing was cloned")
            continue
        library = Path(chosen[0]).resolve()
        target = library / (folder or owner) / name
        if target.exists():
            say(name, "exists")
            continue
        plan = [{"source": target, "name": name, "target": target, "library": library,
                 "origin": f"https://{host}/{owner}/{name}.git", "action": "clone", "detail": ""}]
        result = apply_materialize(plan)[0]
        say(name, result["action"], result.get("detail", ""))
    return _status(good, bad), "\n".join(lines)


def _status(good: int, bad: int) -> str:
    return "done" if not bad else "partial" if good else "failed"
