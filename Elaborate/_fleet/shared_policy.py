"""Protected values shared across the fleet: add one on any machine, every machine has it.

Why:          the user (2026-11-16): "if I add a new value on one machine I want the fleet to
              share that", with removals asked about rather than spread.
Reads:        this machine's three policy lists (never_publish, never_publish_words, safe_values)
              in the common settings profile; other machines' shared records.
May change:   those three lists, only to strengthen protection; anything that would loosen it
              (a never-publish value removed elsewhere, an allowed value added elsewhere) waits as
              a question until the person answers it on the App & setup tab.
Results:      this machine's shared record; what a merge did and what it asks.
Layer:        Elaborate: other machines.
Status:       working

The record travels only where it stays among this person's own machines: Tailscale (peers pull
it from each other, authorized by the Tailscale identity that also hands over the fleet key) and,
encrypted with a key from the fleet key, a synced folder (Elaborate/_fleet/sealed.py). It holds
the values themselves, so it never goes into a report, a log or the state repository.

State, per machine, in the fleet folder's shared-policy.json: the lists as last seen (so a value
that disappeared is known to have been removed here), this machine's removals (shared so other
machines can ask about them), answers declined (never asked again), and open questions.
Matching is case-insensitive, as the scanner's is.
"""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

LISTS = ("never_publish", "never_publish_words", "safe_values")
BLOCKING = ("never_publish", "never_publish_words")  # removing from these weakens protection
STATE_NAME = "shared-policy.json"
SCHEMA = 1
LIST_WORDS = {"never_publish": "never publish", "never_publish_words": "never publish (whole word)",
              "safe_values": "allowed"}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _fold(value: str) -> str:
    return value.casefold()


def strengthens(kind: str, name: str) -> bool:
    """Whether adding (kind "add") or removing ("remove") a value in list `name` tightens protection."""
    return (kind == "add") == (name in BLOCKING)


class SharedPolicy:
    """One machine's side of the shared protected values. Thread-safe: the peer's server serves
    the record while its poller merges others."""

    def __init__(self, home, directory: Path, *, fleet_id: str, machine_id: str, label: str):
        self.home, self.path = home, Path(directory) / STATE_NAME
        self.fleet_id, self.machine_id, self.label = fleet_id, machine_id, label
        self.lock = threading.Lock()

    # ------------------------------------------------------------------ state
    def _read(self) -> dict:
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        state.setdefault("known", {})
        state.setdefault("removed", {})
        state.setdefault("declined", {})
        state.setdefault("pending", [])
        return state

    def _write(self, state: dict) -> None:
        from Basic._files import atomic_write_bytes
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(self.path, json.dumps(state, indent=1, sort_keys=True).encode())

    def _lists(self) -> dict:
        from Special._security._policy_edit import policy_view
        return policy_view(self.home)["lists"]

    def _notice_local(self, state: dict, lists: dict) -> None:
        """A value seen before and gone now was removed on this machine: remember it, so the
        others are asked. One added back here is no longer a removal."""
        now = _now()
        for name in LISTS:
            current = {_fold(v) for v in lists.get(name, [])}
            removed = state["removed"].setdefault(name, {})
            for value in state["known"].get(name, []):
                if _fold(value) not in current and _fold(value) not in removed:
                    removed[_fold(value)] = {"value": value, "at": now}
            for key in list(removed):
                if key in current:
                    del removed[key]
            state["known"][name] = list(lists.get(name, []))

    # ------------------------------------------------------------------ outgoing
    def record(self) -> dict:
        """What this machine shares: its lists and its removals."""
        with self.lock:
            state = self._read()
            lists = self._lists()
            self._notice_local(state, lists)
            self._write(state)
            return {"schema": SCHEMA, "fleet_id": self.fleet_id, "machine_id": self.machine_id,
                    "label": self.label, "at": _now(), "lists": lists,
                    "removed": {name: list(state["removed"].get(name, {}).values()) for name in LISTS}}

    # ------------------------------------------------------------------ incoming
    def receive(self, record: dict) -> dict:
        """Merge another machine's record: strengthening changes are made now, loosening ones
        become questions. Returns {"applied": [...], "asked": [...]} in words."""
        if not isinstance(record, dict) or record.get("schema") != SCHEMA:
            raise ValueError("not a shared-settings record")
        if record.get("fleet_id") != self.fleet_id or record.get("machine_id") == self.machine_id:
            return {"applied": [], "asked": []}
        source = str(record.get("label") or record.get("machine_id") or "another machine")[:80]
        with self.lock:
            state = self._read()
            lists = self._lists()
            self._notice_local(state, lists)
            changes: dict = {}
            asked = []
            for name in LISTS:
                here = {_fold(v) for v in lists.get(name, [])}
                removed_here = state["removed"].get(name, {})
                declined = set(state["declined"].get(name, []))
                for value in _strings(record.get("lists", {}).get(name)):
                    key = _fold(value)
                    if key in here or key in removed_here or f"add:{key}" in declined:
                        continue
                    asked += self._change(state, changes, "add", name, value, source)
                for entry in record.get("removed", {}).get(name) or []:
                    value = entry.get("value") if isinstance(entry, dict) else None
                    if not isinstance(value, str) or _fold(value) not in here or f"remove:{_fold(value)}" in declined:
                        continue
                    asked += self._change(state, changes, "remove", name, value, source)
            applied = self._apply(changes)
            if applied:
                self._notice_local(state, self._lists())
            self._write(state)
            return {"applied": applied, "asked": asked}

    def _change(self, state, changes, kind, name, value, source) -> list[str]:
        if strengthens(kind, name):
            changes.setdefault((kind, name), []).append(value)
            return []
        key = f"{kind}:{name}:{_fold(value)}"
        if any(item["id"] == _question_id(key) for item in state["pending"]):
            return []
        state["pending"].append({"id": _question_id(key), "kind": kind, "list": name, "value": value,
                                 "from": source, "at": _now()})
        return [f"{source} {'added' if kind == 'add' else 'removed'} an {LIST_WORDS[name]} value"]

    def _apply(self, changes: dict) -> list[str]:
        from Special._security._policy_edit import policy_change
        done = []
        for (kind, name), values in changes.items():
            try:
                policy_change(self.home, {"list": name, kind: values[:50]})
            except ValueError:
                continue  # in another list here (a conflict the person resolves by hand)
            done.append(f"{'added' if kind == 'add' else 'removed'} {len(values)} {LIST_WORDS[name]} value(s)")
        return done

    # ------------------------------------------------------------------ questions
    def questions(self) -> list[dict]:
        with self.lock:
            return list(self._read()["pending"])

    def answer(self, question_id: str, accept: bool) -> dict:
        """The person's answer to one question. Yes makes the change here; no is remembered."""
        from Special._security._policy_edit import LOOSEN_WORD, policy_change
        with self.lock:
            state = self._read()
            item = next((q for q in state["pending"] if q["id"] == question_id), None)
            if item is None:
                raise ValueError("that question is no longer open; reload")
            if accept:
                try:
                    policy_change(self.home, {"list": item["list"], item["kind"]: [item["value"]],
                                              "confirm": LOOSEN_WORD})
                except ValueError as exc:
                    if "not in the list" not in str(exc):
                        raise
            else:
                state["declined"].setdefault(item["list"], []).append(f"{item['kind']}:{_fold(item['value'])}")
            state["pending"] = [q for q in state["pending"] if q["id"] != question_id]
            self._notice_local(state, self._lists())
            self._write(state)
            return {"answered": question_id, "accepted": bool(accept)}


def _strings(values) -> list[str]:
    return [v for v in values or [] if isinstance(v, str) and v.strip() and len(v) <= 200][:500]


def _question_id(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:16]
