"""Requests between machines: "please fast-forward these", "please clone this". Asked on one
machine's page, answered on the other's.

Why:          Each machine pulls requests from its authenticated peers and keeps those addressed
              to it. Its local policy decides whether to run a clone or safe fast-forward on
              arrival, wait for its own operator, or accept one confirmation from the sender.
Reads:        this machine's requests-out.json and requests-in.json in the fleet folder.
May change:   those two files only. Applying a request runs the existing safe operations
              (Special/_sync/actions.py): a fast-forward after a fresh fetch, a clone that never
              replaces anything.
Results:      the lists the page shows.
Layer:        Elaborate: other machines.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

KINDS = {"pull": "fast-forward", "clone": "clone", "resolve": "resolve repository"}
RESOLVE_OPERATIONS = {
    "changes": set(), "untracked": {"file"}, "commit-plan": {"files", "message"},
    "commit-apply": {"files", "message", "plan_id"}, "push-plan": set(), "push-apply": {"plan_id"},
    "branches": set(), "stashes": set(), "fetch": set(),
    "stash-plan": {"message"}, "stash-apply": {"message", "plan_id"},
}


def valid_resolve(value) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get("op"), str):
        return False
    op = value["op"]
    if op not in RESOLVE_OPERATIONS:
        return False
    base = {"op", "checkout"}
    fields = RESOLVE_OPERATIONS[op]
    if not fields <= value.keys() or set(value) - base - fields:
        return False
    checkout = value.get("checkout", "")
    if not isinstance(checkout, str) or (checkout and not re.fullmatch(r"[a-f0-9]{32}", checkout)):
        return False
    if op not in ("changes", "branches", "stashes", "fetch") and not checkout:
        return False
    if "files" in fields and (not isinstance(value["files"], list) or not 0 < len(value["files"]) <= 100):
        return False
    paths = value["files"] if "files" in fields else [value["file"]] if "file" in fields else []
    if any(not isinstance(path, str) or not 0 < len(path) <= 500 or not path.isprintable() for path in paths):
        return False
    if "message" in fields:
        msg = value["message"]
        if not isinstance(msg, str) or not msg.strip() or len(msg) > 5000 or "\0" in msg:
            return False
    return "plan_id" not in fields or (
        isinstance(value["plan_id"], str) and re.fullmatch(r"[a-f0-9]{64}", value["plan_id"]) is not None
    )
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
    "remote_policy": (False, "requires local review before Git can run"),
}
KEEP_DAYS = 7
MAX_ITEMS = 500
CONFIRMATION_MINUTES = 15
CONFIRMATION_MODES = ("confirm", "typed")
ITEM_KEYS = ("repo_id", "host", "owner", "name", "folder", "library")


def valid_items(items) -> bool:
    """A bounded peer payload of fields, never arguments or paths on the receiver."""
    return (isinstance(items, list) and 0 < len(items) <= MAX_ITEMS
            and all(isinstance(item, dict) and item and set(item) <= set(ITEM_KEYS)
                    and all(isinstance(value, str) and len(value) <= 200
                            and (not value or value.isprintable()) for value in item.values())
                    for item in items))


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _fresh(stamp: str) -> bool:
    try:
        age = _now() - datetime.fromisoformat(stamp)
        return -timedelta(minutes=1) <= age < timedelta(days=KEEP_DAYS)
    except (TypeError, ValueError):
        return False


def _digest(request: dict) -> str:
    fields = {key: request[key] for key in ("id", "from", "to", "kind", "items", "at")}
    return hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _phrase(request: dict) -> str:
    if len(request["items"]) == 1:
        item = request["items"][0]
        if item.get("owner") and item.get("name"):
            return f"{item['owner']}/{item['name']}"
    return f"{KINDS[request['kind']].upper()} {len(request['items'])}"


def _valid_receipt(value, request) -> bool:
    if (not isinstance(value, dict) or set(value) != {"mode", "nonce", "digest", "expires"}
            or value.get("mode") not in CONFIRMATION_MODES
            or not re.fullmatch(r"[0-9a-f]{32}", str(value.get("nonce", "")))
            or value.get("digest") != _digest(request)):
        return False
    try:
        return _now() < datetime.fromisoformat(value["expires"])
    except (KeyError, TypeError, ValueError):
        return False


def approval_valid(request: dict, mode: str) -> bool:
    return (_fresh(request["at"]) and request.get("approval_mode") == mode
            and (mode == "automatic" or (mode in CONFIRMATION_MODES and request.get("confirmed") is True
                                         and _valid_receipt(request.get("challenge"), request))))


class RequestBook:
    def __init__(self, directory: Path, machine_id: str, label: str):
        self.out_path = Path(directory) / "requests-out.json"
        self.in_path = Path(directory) / "requests-in.json"
        self.peers_path = Path(directory) / "request-peers.json"
        self.machine_id, self.label = machine_id, label
        self.lock = threading.Lock()

    def _read(self, path: Path):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return [] if path == self.out_path else {}
        if not isinstance(record, list if path == self.out_path else dict):
            raise ValueError("invalid request record; review the request state on this machine")
        return record

    def _write(self, path: Path, value) -> None:
        from Basic._files import atomic_write_bytes
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(path, json.dumps(value, indent=1).encode())

    def bind_peer(self, machine_id: str, device_id: str) -> bool:
        """Pin a legacy report id to the authenticated tailnet device that first used it."""
        if machine_id.startswith("ts-"):
            return machine_id == device_id
        if not device_id.startswith("ts-") or machine_id == self.machine_id:
            return False
        with self.lock:
            try:
                peers = json.loads(self.peers_path.read_bytes())
            except FileNotFoundError:
                peers = {}
            if not isinstance(peers, dict):
                raise ValueError("invalid request peer bindings")
            if machine_id in peers:
                return peers[machine_id] == device_id
            peers[machine_id] = device_id
            self._write(self.peers_path, peers)
            return True

    # ---------------------------------------------------------------- asking
    def device_matches(self, machine_id, device_id) -> bool:
        if not isinstance(device_id, str) or not device_id.startswith("ts-"):
            return False
        if machine_id.startswith("ts-"):
            return device_id == machine_id
        with self.lock:
            try:
                peers = json.loads(self.peers_path.read_bytes())
            except (FileNotFoundError, ValueError):
                return False
            return isinstance(peers, dict) and peers.get(machine_id) == device_id

    def send(self, to: str, to_label: str, kind: str, items: list[dict], *, resolve=None) -> dict:
        if kind not in KINDS:
            raise ValueError("a request is pull or clone")
        if not valid_items(items):
            raise ValueError("choose a bounded list of valid repository targets")
        request = {"id": uuid.uuid4().hex[:16], "from": self.machine_id, "from_label": self.label,
                   "to": to, "to_label": to_label, "kind": kind, "items": items, "at": _now().isoformat(),
                   "supports_confirmation": True}
        if kind == "resolve":
            if len(items) != 1 or not valid_resolve(resolve):
                raise ValueError("invalid remote repository operation")
            request["resolve"] = resolve
        with self.lock:
            sent = [item for item in self._read(self.out_path) if _fresh(item.get("at", ""))]
            sent.append(request)
            self._write(self.out_path, sent)
        return request

    def outgoing(self) -> list[dict]:
        with self.lock:
            return [item for item in self._read(self.out_path) if _fresh(item.get("at", ""))]

    def published(self, mode: str | None = None, *, device_id=None) -> list[dict]:
        """What GET /v1/requests serves: this machine's requests, and its answers to the requests
        others sent it, so the asking machine learns what happened (the user, 2026-11-16)."""
        answers = []
        for item in self.incoming(include_hidden=True):
            if item["kind"] == "resolve" and not self.device_matches(item["from"], device_id):
                continue
            selected = item.get("approval_mode", "local")
            effective = "paused" if mode == "paused" else selected if mode is None or mode == selected else "local"
            answer = {"answer_for": item["id"], "from": self.machine_id, "to": item["from"],
                      "status": item["status"], "result": item.get("result", "")[:2000], "at": item["at"],
                      "approval_mode": effective}
            if (item["status"] == "waiting" and effective in CONFIRMATION_MODES
                    and _valid_receipt(item.get("challenge"), item)):
                answer["challenge"] = item["challenge"]
            answers.append(answer)
        return [item for item in self.outgoing()
                if item["kind"] != "resolve" or (
                    item.get("status") not in ENDED and self.device_matches(item["to"], device_id)
                )] + answers

    def confirm(self, request_id: str, text: str) -> dict:
        with self.lock:
            sent = self._read(self.out_path)
            request = next((item for item in sent if item["id"] == request_id), None)
            if not request or request.get("status") != "waiting" or request.get("confirmation"):
                raise ValueError("this request is no longer waiting for confirmation")
            challenge = request.get("challenge")
            if not _valid_receipt(challenge, request):
                raise ValueError("the receiving machine's confirmation has expired; send a new request")
            if challenge["mode"] == "typed" and text != _phrase(request):
                raise ValueError("the acknowledgment did not match")
            request["confirmation"] = {"nonce": challenge["nonce"], "digest": challenge["digest"],
                                       "text": text if challenge["mode"] == "typed" else ""}
            self._write(self.out_path, sent)
            return request

    def recover_interrupted(self) -> None:
        """A previous process may have applied Git changes before it lost its receipt."""
        with self.lock:
            book = self._read(self.in_path)
            running = [item for item in book.values() if item.get("status") == "running"]
            for item in running:
                item.update(status="partial", result="Interrupted. Check the checkout before sending another request.")
            if running:
                self._write(self.in_path, book)

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
            cleared_in = 0
            for value in book.values():
                if value.get("status") in ENDED and not value.get("hidden"):
                    value["hidden"] = True  # Keep the receipt until expiry so it cannot run again.
                    cleared_in += 1
            self._write(self.out_path, kept_sent)
            self._write(self.in_path, book)
            return len(sent) - len(kept_sent) + cleared_in

    # ---------------------------------------------------------------- answering
    def receive(self, requests, from_machine: str, mode: str = "local", *, peer_label=None) -> int:
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
                        if (request.get("id") == item["answer_for"] and request.get("to") == from_machine
                                and request.get("status") not in ENDED
                                and not (request.get("status") == "running" and item.get("status") == "waiting")
                                and item.get("status") in (*ENDED, "waiting", "running")):
                            challenge = item.get("challenge")
                            updates = {"status": item["status"], "result": str(item.get("result", ""))[:2000],
                                       "approval_mode": item.get("approval_mode", "local"),
                                       "challenge": challenge if _valid_receipt(challenge, request) else None}
                            if any(request.get(key) != value for key, value in updates.items()):
                                request.update(updates)
                                if request["kind"] == "resolve" and request["status"] in ENDED:
                                    request["resolve"] = {"op": request["resolve"]["op"]}
                                answered = True
            if answered:
                self._write(self.out_path, sent)
            book = self._read(self.in_path)
            for item in requests:
                if (not isinstance(item, dict) or item.get("to") != self.machine_id
                        or item.get("from") != from_machine or item.get("kind") not in KINDS
                        or not re.fullmatch(r"[0-9a-f]{16}", str(item.get("id", "")))
                        or not valid_items(item.get("items"))
                        or not _fresh(item.get("at", ""))):
                    continue
                resolve = item.get("kind") == "resolve"
                if resolve and (len(item["items"]) != 1 or not valid_resolve(item.get("resolve"))):
                    continue
                request = book.get(item["id"])
                if request is None:
                    request = {key: item[key] for key in ("id", "from", "to", "kind", "items", "at")}
                    request.update(from_label=str(peer_label or item.get("from_label", from_machine))[:200], status="waiting", result="",
                                   approval_mode=mode if item.get("supports_confirmation") is True or mode == "automatic" else "local")
                    if resolve:
                        request.update(resolve=item["resolve"], approval_mode="local")
                    if mode == "paused":
                        request.update(status="dismissed", result="Incoming fleet operations are paused on this machine.")
                    if request["approval_mode"] in CONFIRMATION_MODES:
                        request["challenge"] = {"mode": mode, "digest": _digest(request), "nonce": secrets.token_hex(16),
                                                "expires": (_now() + timedelta(minutes=CONFIRMATION_MINUTES)).isoformat()}
                    book[item["id"]] = request
                    added += 1
                elif mode == "paused" and request["status"] == "waiting" and request["from"] == from_machine:
                    request.update(status="dismissed", result="Incoming fleet operations are paused on this machine.")
                    added += 1
                proof, challenge = item.get("confirmation"), request.get("challenge")
                if (request["status"] == "waiting" and not request.get("confirmed")
                        and mode in CONFIRMATION_MODES and request.get("approval_mode") == mode
                        and request["from"] == from_machine and _valid_receipt(challenge, request)
                        and isinstance(proof, dict) and proof.get("nonce") == challenge["nonce"]
                        and proof.get("digest") == challenge["digest"] == _digest(item)
                        and (mode != "typed" or proof.get("text") == _phrase(request))):
                    request["confirmed"] = True
                    added += 1
            book = {key: value for key, value in book.items() if _fresh(value.get("at", ""))}
            self._write(self.in_path, book)
        return added

    def incoming(self, *, include_hidden=False) -> list[dict]:
        with self.lock:
            book = self._read(self.in_path)
            return sorted((item for item in book.values() if include_hidden or not item.get("hidden")),
                          key=lambda item: item.get("at", ""), reverse=True)

    def claim(self, request_id: str, mode: str | None, *, dismiss=False) -> dict:
        """Atomically take a waiting request; mode None is the receiver's local decision."""
        with self.lock:
            book = self._read(self.in_path)
            request = book.get(request_id)
            if not request or request["status"] != "waiting" or not _fresh(request["at"]):
                raise ValueError("that request is no longer waiting; reload")
            if mode is not None and not approval_valid(request, mode):
                raise ValueError("this request is waiting for approval")
            request.update(status="dismissed" if dismiss else "running", result="Dismissed here." if dismiss else "")
            self._write(self.in_path, book)
            return request

    def settle(self, request_id: str, status: str, result: str) -> dict:
        with self.lock:
            book = self._read(self.in_path)
            if request_id not in book:
                raise ValueError("that request is no longer here; reload")
            book[request_id].update(status=status, result=result[:2000])
            if book[request_id]["kind"] == "resolve" and status in ENDED:
                book[request_id]["resolve"] = {"op": book[request_id]["resolve"]["op"]}
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


def perform(request: dict, local_checkouts, libraries: list[str], private=None, *, fleet=False) -> tuple[str, str]:
    """Do what a request asks, with the safe operations. Returns (status, public text):
    "done" when every repository ended well, "partial" when some did, "failed" when none did.
    The text is fixed sentences per repository; `private(name, detail)` receives Git's own words
    for this machine's log."""
    from Special._sync.actions import apply_catchup, apply_materialize, fleet_clone_origin, plan_catchup
    from Special._runtime.files import traverses_link
    if request.get("kind") not in ("pull", "clone") or not valid_items(request.get("items")):
        return "failed", "Invalid operation or repository targets."
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
            if wanted or fleet:
                # Only the copy in the library the asking page's column named.
                paths = [path for path in paths if (library := _library_of(path, libraries))
                         and (not wanted or library == wanted) and (not fleet or not traverses_link(Path(path)))]
            if not paths:
                bad += 1
                lines.append(f"{name}: no copy here" + (f" in {wanted}" if wanted else ""))
                continue
            for result in apply_catchup(plan_catchup(paths, fleet=fleet), fleet=fleet):
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
        origin = fleet_clone_origin(host, owner, name, folder)
        if origin is None:
            say("Repository", "remote_policy")
            continue
        # The library the asking page's column named (one machine may keep several); the first
        # library when it names none.
        from Special._sync.manifest import library_name
        chosen = [root for root in libraries if library_name(root, libraries) == wanted] if wanted else libraries[:1]
        if not chosen:
            bad += 1
            lines.append(f"{name}: no library called {wanted} here, so nothing was cloned")
            continue
        from Special._sync.observer import library_available
        if not library_available(chosen[0]):
            bad += 1
            lines.append(f"{name}: the selected library is unavailable; nothing was cloned")
            continue
        library = Path(chosen[0]).resolve()
        target = library / (folder or owner) / name
        if target.exists():
            say(name, "exists")
            continue
        plan = [{"source": target, "name": name, "target": target, "library": library,
                 "origin": origin, "action": "clone", "detail": ""}]
        result = apply_materialize(plan, fleet=True)[0]
        say(name, result["action"], result.get("detail", ""))
    return _status(good, bad), "\n".join(lines)


def _status(good: int, bad: int) -> str:
    return "done" if not bad else "partial" if good else "failed"
