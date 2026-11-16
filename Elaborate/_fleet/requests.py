"""Requests between machines: "please fast-forward these", "please clone this". Asked on one
machine's page, answered on the other's.

Why:          syncing a fleet from one screen (the user, 2026-11-16) without breaking the rule that
              machines only read from each other. A request is published like a report: the asking
              machine serves its outgoing requests (GET /v1/requests); each machine pulls them on
              its round and keeps the ones addressed to it. Nothing runs until a person presses
              Apply on the machine that does the work.
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
            kept_sent = [] if everything_sent else [item for item in sent if item.get("status") not in ("done", "dismissed")]
            book = self._read(self.in_path)
            kept_in = {key: value for key, value in book.items() if value.get("status") == "waiting"}
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


def run_request(request: dict, local_checkouts, libraries: list[str]) -> str:
    """Do what a request asks, with the safe operations; returns what happened, in words."""
    from Special._sync.actions import apply_catchup, apply_materialize, plan_catchup, render_catchup
    if request["kind"] == "pull":
        paths = [path for item in request["items"] for path in local_checkouts(item.get("repo_id", ""))]
        if not paths:
            return "None of those repositories has a copy here."
        return render_catchup(apply_catchup(plan_catchup(paths)), applied=True)
    lines = []
    for item in request["items"]:
        host, owner, name, folder = (str(item.get(key) or "") for key in ("host", "owner", "name", "folder"))
        if not all(part and "/" not in part and "\\" not in part and ".." not in part for part in (host, owner, name)):
            lines.append(f"{name or 'a repository'}: its name is not known here (the asking machine withholds names)")
            continue
        library = Path(libraries[0])
        target = library / (folder or owner) / name
        if target.exists():
            lines.append(f"{name}: already here, left as it is")
            continue
        plan = [{"source": target, "name": name, "target": target, "library": library,
                 "origin": f"https://{host}/{owner}/{name}.git", "action": "clone", "detail": ""}]
        result = apply_materialize(plan)[0]
        lines.append(f"{name}: {'cloned into ' + str(target.parent.name) if result['action'] == 'cloned' else result['detail']}")
    return "\n".join(lines)
