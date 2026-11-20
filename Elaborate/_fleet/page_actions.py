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

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from Basic._files import atomic_write_bytes

HEADLINE = {"done": "Done", "partial": "Partly done", "failed": "Not done"}
REQUEST_ACTIONS = ("request-send", "request-confirm", "request-withdraw", "request-answer", "request-clear", "changes")
#: Repository actions after which this machine's own state is read again.
RESCAN_AFTER = ("pull", "commit-apply", "push-apply", "stash-apply", "not-counted", "not-counted-folder", "count-again", "fetch")


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
        from Elaborate._fleet.remote_resolve import RemoteResolve
        self.remote_resolve = RemoteResolve(self)

    # ---------------------------------------------------------------- the one entry
    def handle(self, action: str, payload: dict):
        """Local dashboard actions call the same headless operations as terminal routes."""
        if action == "repo-visibility":
            if payload:
                raise ValueError("repository visibility takes no arguments")
            return self.repository_visibility()
        if action.startswith("security-"):
            return self.security(action, payload)
        if action in REQUEST_ACTIONS:
            return self.requests(action, payload)
        if action in ("remote-resolve", "remote-result"):
            return self.remote_resolve.handle(action, payload)
        if action == "repo-action":
            return self.repository(payload)
        if action != "catchup-preview" or payload:
            raise ValueError("unsupported fleet dashboard action")
        from Special._sync.actions import plan_catchup, render_catchup
        with self.lock:
            plan = plan_catchup(self.observer.paths)
        return {"message": render_catchup(plan), "action": "catchup-preview"}

    def repository_visibility(self):
        """Look up visibility in the GitHub namespaces already observed on this machine."""
        from Basic._providers.github import GitHubProvider
        from Elaborate._fleet.convergence import namespaces_from_catalog
        from Special._sync.config import load_catalog
        from Special._sync.manifest import repository_id

        catalog = load_catalog(self.config_dir)
        owners = [owner for host, owner in namespaces_from_catalog(catalog)
                  if host == "github.com" and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", owner)]
        provider = GitHubProvider()
        visibility, failed = {}, 0
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="repo-visibility") as pool:
            for refs, error in pool.map(provider.list_repos, owners):
                if error or refs is None:
                    failed += 1
                    continue
                for ref in refs:
                    repo_id = repository_id(ref.host, ref.owner, ref.name, self.config.get("fleet_secret"))
                    if repo_id in catalog and ref.visibility in ("public", "private", "internal"):
                        visibility[repo_id] = ref.visibility
        return {"visibility": visibility, "namespaces_checked": len(owners) - failed, "namespaces_unavailable": failed}

    def rescan(self, why: bytes) -> None:
        atomic_write_bytes(self.config_dir / "fleet-rescan.request", why + b"\n")

    def knock(self) -> None:
        if self.network is not None:
            threading.Thread(target=self.network.knock_others, daemon=True).start()

    # ---------------------------------------------------------------- security
    def security(self, action: str, payload: dict):
        from Special._security._audit import MAX_RUNNERS, coverage_receipt, engines_status
        from Special._security._policy_edit import audit_cache_change, audit_cache_view, policy_change, policy_view
        if action == "security-engines":
            return {"engines": engines_status(), "audit_checkpoints": True, "bound_audit_actions": True, "max_runners": MAX_RUNNERS,
                    "audit_storage": audit_cache_view(self.security_settings()[0])}
        if action == "security-policy":
            return policy_view(self.security_settings()[0])
        if action == "security-policy-change":
            with self.lock:
                home = self.security_settings()[0]
                if "audit_history_cache" in payload:
                    return {"audit_storage": audit_cache_change(home, payload)}
                return policy_change(home, payload)
        if action == "security-start":
            return self._coverage_destinations(self.audits.start(payload))
        if action == "security-export":
            destination = payload.get("destination")
            if set(payload) - {"id", "destination"} or destination not in (None, "download", "folder", "repo"):
                raise ValueError("choose a supported audit export destination")
            audit = self.audits.status(full=destination is None)["audit"]
            if audit is None or audit["id"] != payload.get("id"):
                raise ValueError("that audit is no longer available")
            if destination is None:
                return {"disclosure": "masked", "audit": audit}
            coverage = coverage_receipt(audit, self.config["machine_id"],
                                        secret=self.config.get("fleet_secret"))
            if destination == "download":
                return coverage
            return self._share_audit_coverage(destination, coverage)
        if action == "security-status":
            return self._coverage_destinations(self.audits.status())
        if action == "security-reveal":
            return self.audits.reveal(payload)
        if action == "security-accept":
            with self.lock:
                return self.audits.accept(payload)
        if action == "security-stop":
            return self._coverage_destinations(self.audits.stop())
        if action == "security-preview":
            from Special._security._advice import inspect_registered
            with self.lock:
                home, snapshot = self.security_settings()
                return inspect_registered(payload, self.observer.local_checkouts, settings_home=home,
                                          expected_settings=snapshot)
        raise ValueError("unsupported fleet dashboard action")

    def _coverage_destinations(self, result):
        if result["audit"] is not None:
            transports = self.config.get("transports") or {}
            result["audit"]["coverage_destinations"] = [name for name in ("folder", "repo") if transports.get(name)]
        return result

    def _share_audit_coverage(self, destination, coverage):
        from Basic._providers.github import GhError
        from Elaborate._transport.folder import FolderTransport
        from Elaborate._transport.repo import RepoTransport

        config = (self.config.get("transports") or {}).get(destination)
        if not config:
            raise ValueError("this audit coverage destination is not configured")
        payload = (json.dumps(coverage, indent=2, sort_keys=True) + "\n").encode("utf-8")
        transport = FolderTransport(config["path"]) if destination == "folder" else RepoTransport(config["name"])
        try:
            with self.lock:
                transport.write_audit_coverage(self.config["machine_id"], payload)
        except (GhError, OSError, ValueError) as exc:
            raise ValueError("Could not share coverage. Check access to the configured private destination.") from exc
        return {"message": "Shared coverage for this machine."}

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
    def own_changes(self, repo_id: str, *, offset=None) -> dict:
        from Elaborate._fleet.requests import _library_of
        from Special._sync.changes import working_changes
        copies = []
        for path in self.observer.local_checkouts(repo_id):
            library = _library_of(path, self.config.get("roots") or [])
            try:
                copies.append({**working_changes(path, expanded=offset is not None, offset=offset or 0), "library": library})
            except ValueError as exc:
                copies.append({"files": [], "count": 0, "summary": str(exc), "library": library})
        return {"machine": self.config["label"], "copies": copies}

    # ---------------------------------------------------------------- requests between machines
    def requests(self, action: str, payload: dict):
        config, book = self.config, self.book
        if action == "request-send":
            from Elaborate._fleet.requests import valid_items
            items = payload.get("items")
            if not valid_items(items):
                raise ValueError("choose a bounded list of valid repository targets")
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
            return {"sent": sent, "message": f"Queued for {sent['to_label']}. Requests shows when the receiving machine responds."}
        if action == "request-withdraw":
            book.withdraw(_text(payload.get("id")))
            return {"message": "Withdrawn."}
        if action == "request-confirm":
            request = book.confirm(_text(payload.get("id")), _text(payload.get("text"), limit=401))
            book.log("confirmed remotely", request)
            self.knock()
            return {"message": f"Approval sent to {request['to_label']} for this request."}
        if action == "request-clear":
            dropped = book.clear(everything_sent=bool(payload.get("everything_sent")))
            return {"message": f"Cleared {dropped}. The task log keeps the record."}
        if action == "changes":
            repo_id, machine_id = _text(payload.get("repo_id")), _text(payload.get("machine_id"))
            offset = payload.get("offset")
            if offset is not None and (type(offset) is not int or not 0 <= offset <= 999_999):
                raise ValueError("invalid file detail page")
            if machine_id == config["machine_id"]:
                return self.own_changes(repo_id) if offset is None else self.own_changes(repo_id, offset=offset)
            if self.network is None:
                raise ValueError("this machine is not connected to its fleet right now")
            if offset is not None:
                return self.network.ask(machine_id, f"/v1/change-files/{repo_id}/{offset}")
            return self.network.ask(machine_id, f"/v1/changes/{repo_id}")
        if type(payload.get("accept")) is not bool:
            raise ValueError("answer with accept true or false")
        request_id = _text(payload.get("id"))
        if not payload.get("accept"):
            request = book.claim(request_id, None, dismiss=True)
            book.log("dismissed", request)
            self.knock()
            return request
        if self.request_mode() == "paused":
            raise ValueError("Incoming fleet operations are paused on this machine.")
        return self.answer(request_id)

    def run_and_log(self, event: str, request: dict, mode: str | None = None) -> tuple[str, str]:
        """Run a request with the safe operations; Git's own words stay in this machine's log."""
        from Elaborate._fleet.requests import approval_valid, perform
        details = []
        with self.lock:
            if "from" in request and self.request_mode() == "paused":
                return "dismissed", "Incoming fleet operations are paused on this machine."
            if mode is not None and mode != self.request_mode():
                return "failed", "The receiving machine's approval policy changed before execution."
            if mode is not None and not approval_valid(request, mode):
                return "failed", "The approval expired before execution."
            status, result = perform(request, self.observer.local_checkouts, self.config["roots"],
                                     private=lambda name, detail: details.append(f"{name}: {detail}"),
                                     fleet="from" in request)
        self.book.log(event, request, "\n".join([result, *details]))
        self.rescan(b"request ran")  # see the result
        return status, result

    def answer(self, request_id: str, mode: str | None = None) -> dict:
        request = self.book.claim(request_id, mode)
        try:
            event = {"automatic": "ran automatically", "confirm": "applied remote approval",
                     "typed": "applied typed remote approval"}.get(mode, "applied locally")
            if request["kind"] == "resolve":
                status, result = self.remote_resolve.execute(request)
                self.book.log(event, request, result)
            else:
                status, result = self.run_and_log(event, request, mode)
        except Exception:  # noqa: BLE001 - a request must end in a state, never stay "running"
            status, result = "failed", "It could not be run on that machine; its log has the reason."
        settled = self.book.settle(request["id"], status, result)
        self.knock()  # the asker learns now
        return settled

    def request_mode(self) -> str:
        from Special._sync.enrollment import request_approval_mode
        try:
            _home, snapshot = self.security_settings()
            if snapshot is None and hasattr(self.config, "snapshot"):
                return "local"
            config = snapshot.config("app") if snapshot is not None else self.config
            return request_approval_mode((config or {}).get("auto_requests"))
        except (OSError, ValueError):
            return "local"

    def run_waiting(self) -> None:
        """Apply eligible requests under the receiver's current policy."""
        self.knock()
        for request in self.book.incoming():
            mode = self.request_mode()
            if mode not in ("local", "paused") and request.get("status") == "waiting":
                try:
                    self.answer(request["id"], mode)
                except ValueError:
                    continue
