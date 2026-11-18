"""What this machine's own page can ask the running peer to do.

Why:          the page and the terminal are two faces on the same operations. This is the page's
              face: each action here calls the headless function its `gitso` command calls,
              with the peer's settings profile and this machine's own checkouts.
Reads:        the peer's configuration, its observer (which checkouts exist) and its request book.
May change:   only what the called operation changes; anything that writes holds one lock, so
              two actions never work on a repository at once.
Results:      a JSON-ready answer for the page.
Layer:        Elaborate: other machines.
Status:       working

Taken out of the peer's run loop (an outside review, 2026-11-17: actions, observation,
networking and lifecycle were accumulating in one function). The peer builds one `PageActions`
and hands `handle` to the local web server; nothing here is reachable from another machine.
"""
from __future__ import annotations

import threading
from pathlib import Path

from Basic._files import atomic_write_bytes

HEADLINE = {"done": "Done", "partial": "Partly done", "failed": "Not done"}
REQUEST_ACTIONS = ("request-send", "request-withdraw", "request-answer", "request-clear", "changes")
#: Repository actions after which this machine's own state is read again.
RESCAN_AFTER = ("pull", "commit-apply", "push-apply", "not-counted", "not-counted-folder", "count-again", "fetch")


def _text(value, limit=200) -> str:
    return str(value or "")[:limit]


class PageActions:
    def __init__(self, config: dict, config_dir: Path, observer, book, security_settings, audits):
        self.config, self.config_dir = config, Path(config_dir)
        self.observer, self.book = observer, book
        self.security_settings = security_settings  # () -> (home, snapshot), read fresh each time
        self.audits = audits
        self.lock = threading.Lock()
        self.network = None  # set by the peer once its network exists

    # ---------------------------------------------------------------- the one entry
    def handle(self, action: str, payload: dict):
        """Local dashboard actions call the same headless operations as terminal routes."""
        if action.startswith("security-"):
            return self.security(action, payload)
        if action in REQUEST_ACTIONS:
            return self.requests(action, payload)
        if action == "repo-action":
            return self.repository(payload)
        if action != "catchup-preview" or payload:
            raise ValueError("unsupported fleet dashboard action")
        from Special._sync.actions import plan_catchup, render_catchup
        with self.lock:
            plan = plan_catchup(self.observer.paths)
        return {"message": render_catchup(plan), "action": "catchup-preview"}

    def rescan(self, why: bytes) -> None:
        atomic_write_bytes(self.config_dir / "fleet-rescan.request", why + b"\n")

    def knock(self) -> None:
        if self.network is not None:
            threading.Thread(target=self.network.knock_others, daemon=True).start()

    # ---------------------------------------------------------------- security
    def security(self, action: str, payload: dict):
        from Special._security._audit import engines_status
        from Special._security._policy_edit import policy_change, policy_view
        if action == "security-engines":
            return {"engines": engines_status()}
        if action == "security-policy":
            return policy_view(self.security_settings()[0])
        if action == "security-policy-change":
            with self.lock:
                return policy_change(self.security_settings()[0], payload)
        if action == "security-start":
            return self.audits.start(payload)
        if action == "security-status":
            return self.audits.status()
        if action == "security-reveal":
            return self.audits.reveal(payload)
        if action == "security-accept":
            with self.lock:
                return self.audits.accept(payload)
        if action == "security-stop":
            return self.audits.stop()
        if action == "security-preview":
            from Special._security._advice import inspect_registered
            with self.lock:
                home, snapshot = self.security_settings()
                return inspect_registered(payload, self.observer.local_checkouts, settings_home=home,
                                          expected_settings=snapshot)
        raise ValueError("unsupported fleet dashboard action")

    # ---------------------------------------------------------------- one repository, here
    def repository(self, payload: dict):
        """Resolve on this machine: open, look at changes, fetch, fast-forward, commit and push
        (plan, then apply), safe to delete, not counted (Special/_sync/resolve.py)."""
        from Special._sync.resolve import READ_ONLY, repo_action
        op = str(payload.get("op") or "")
        home = self.security_settings()[0]
        if op in READ_ONLY:
            answer = repo_action(op, payload, self.observer.local_checkouts, home=home)
        else:
            with self.lock:
                answer = repo_action(op, payload, self.observer.local_checkouts, home=home)
        if "not_counted" in answer:
            self.config["not_counted"] = answer["not_counted"]  # the running observer reads this
        if op in RESCAN_AFTER:
            self.rescan(b"repository action")
        return answer

    # ---------------------------------------------------------------- uncommitted work
    def own_changes(self, repo_id: str) -> dict:
        from Special._sync.changes import working_changes
        copies = []
        for path in self.observer.local_checkouts(repo_id):
            try:
                copies.append(working_changes(path))
            except ValueError as exc:
                copies.append({"files": [], "count": 0, "summary": str(exc)})
        return {"machine": self.config["label"], "copies": copies}

    # ---------------------------------------------------------------- requests between machines
    def requests(self, action: str, payload: dict):
        config, book = self.config, self.book
        if action == "request-send":
            items = [{key: _text(item.get(key)) for key in ("repo_id", "host", "owner", "name", "folder", "library")}
                     for item in payload.get("items") or [] if isinstance(item, dict)]
            if _text(payload.get("to")) == config["machine_id"]:
                # Asked of this machine, from its own page: the person is here, so it runs now,
                # with the same safe operations (the user, 2026-11-16).
                request = {"kind": _text(payload.get("kind")), "items": items, "from_label": config["label"],
                           "to_label": config["label"]}
                if request["kind"] not in ("pull", "clone") or not items:
                    raise ValueError("choose pull or clone, and at least one repository")
                status, result = self.run_and_log("ran here", request)
                return {"status": status, "message": f"{HEADLINE[status]} here.\n{result}"}
            sent = book.send(_text(payload.get("to")), _text(payload.get("to_label")), _text(payload.get("kind")), items)
            book.log("asked", sent)
            self.knock()  # so it is picked up now
            return {"sent": sent, "message": f"Asked {sent['to_label']}. It runs there when that machine next checks in "
                                             "(about a minute when it is on); the result appears under Requests."}
        if action == "request-withdraw":
            book.withdraw(_text(payload.get("id")))
            return {"message": "Withdrawn."}
        if action == "request-clear":
            dropped = book.clear(everything_sent=bool(payload.get("everything_sent")))
            return {"message": f"Cleared {dropped}. The task log keeps the record."}
        if action == "changes":
            repo_id, machine_id = _text(payload.get("repo_id")), _text(payload.get("machine_id"))
            if machine_id == config["machine_id"]:
                return self.own_changes(repo_id)
            if self.network is None:
                raise ValueError("this machine is not connected to its fleet right now")
            return self.network.ask(machine_id, f"/v1/changes/{repo_id}")
        request = next((item for item in book.incoming() if item["id"] == payload.get("id")), None)
        if request is None or request["status"] != "waiting":
            raise ValueError("that request is no longer waiting; reload")
        if payload.get("accept") is None:
            raise ValueError("answer with accept true or false")
        if not payload.get("accept"):
            book.log("dismissed", request)
            return book.settle(request["id"], "dismissed", "Dismissed here.")
        return self.answer(request)

    def run_and_log(self, event: str, request: dict) -> tuple[str, str]:
        """Run a request with the safe operations; Git's own words stay in this machine's log."""
        from Elaborate._fleet.requests import perform
        details = []
        with self.lock:
            status, result = perform(request, self.observer.local_checkouts, self.config["roots"],
                                     private=lambda name, detail: details.append(f"{name}: {detail}"))
        self.book.log(event, request, "\n".join([result, *details]))
        self.rescan(b"request ran")  # see the result
        return status, result

    def answer(self, request: dict) -> dict:
        self.book.settle(request["id"], "running", "")
        try:
            status, result = self.run_and_log("applied", request)
        except Exception:  # noqa: BLE001 - a request must end in a state, never stay "running"
            status, result = "failed", "It could not be run on that machine; its log has the reason."
        settled = self.book.settle(request["id"], status, result)
        self.knock()  # the asker learns now
        return settled

    def run_waiting(self) -> None:
        """Requests from this fleet's machines run on arrival (requests.py): they can only ask
        for a fast-forward or a clone, neither of which can lose work."""
        if self.config.get("auto_requests") is not True:
            return
        for request in self.book.incoming():
            if request.get("status") == "waiting":
                try:
                    self.answer(request)
                except ValueError:
                    continue
