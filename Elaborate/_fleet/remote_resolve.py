"""Attended Resolve for another enrolled device. Plans and private results expire in memory."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from Elaborate._fleet.requests import valid_resolve
from Special._runtime.files import traverses_link
from Special._sync.resolve import inspect_remote_changes, inspect_untracked, repo_action

TTL = 30 * 60
MAX_RESULTS = 32


class RemoteResolve:
    def __init__(self, actions):
        self.actions = actions
        self.key = secrets.token_bytes(32)
        self.lock = threading.Lock()
        self.results = {}
        self.plans = {}

    def handle(self, action, payload):
        book, network = self.actions.book, self.actions.network
        if network is None or not network.enabled:
            raise ValueError("Live Resolve requires the Tailscale fleet connection.")
        if action == "remote-result":
            if set(payload) != {"id"}:
                raise ValueError("choose a Resolve receipt")
            request = next((item for item in book.outgoing() if item["id"] == payload["id"]
                            and item["kind"] == "resolve"), None)
            if request is None or request.get("status") not in ("done", "failed", "partial"):
                raise ValueError("the remote result is not ready")
            try:
                return network.ask(request["to"], f"/v1/resolve-result/{request['id']}")
            except ValueError as exc:
                raise ValueError("Result unavailable. It may have expired or the host may have restarted.") from exc
        if set(payload) != {"machine_id", "machine_label", "repo_id", "resolve"}:
            raise ValueError("choose a fleet machine, repository and Resolve operation")
        to, label, repo_id = (payload[key] for key in ("machine_id", "machine_label", "repo_id"))
        if (any(not isinstance(value, str) or not 0 < len(value) <= 200 for value in (to, label, repo_id))
                or to == book.machine_id or to not in network.addresses
                or re.fullmatch(r"[a-f0-9]{32}", repo_id) is None or not valid_resolve(payload["resolve"])):
            raise ValueError("select a valid live remote checkout and operation")
        request = book.send(to, label, "resolve", [{"repo_id": repo_id}], resolve=payload["resolve"])
        book.log("asked for remote resolve", request)
        self.actions.knock()
        return {"sent": request, "message": "Queued for approval on the receiving machine."}

    def _copies(self, repo_id):
        roots = [Path(root).resolve() for root in self.actions.config.get("roots", [])]
        copies = {}
        for found in self.actions.observer.local_checkouts(repo_id):
            found = Path(found)
            if traverses_link(found):
                continue
            path = found.resolve()
            root = next((root for root in roots if path.is_relative_to(root)), None)
            if root is None:
                continue
            token = hmac.new(self.key, f"{repo_id}\0{path}".encode(), hashlib.sha256).hexdigest()[:32]
            copies[token] = (path, f"{root.name} / {path.relative_to(root).as_posix()}")
        return copies

    def _prune(self, cache):
        now = time.monotonic()
        for key in list(cache):
            if cache[key][0] <= now:
                del cache[key]
        while len(cache) >= MAX_RESULTS:
            del cache[next(iter(cache))]

    def result(self, request_id, device_id):
        with self.lock:
            record = self.results.get(request_id)
        if record and record[0] > time.monotonic() and self.actions.book.device_matches(record[1], device_id):
            return record[2]
        return None

    def execute(self, request):
        data = request["resolve"]
        sender, repo_id = request["from"], request["items"][0]["repo_id"]
        if datetime.now(timezone.utc) - datetime.fromisoformat(request["at"]) >= timedelta(seconds=TTL):
            return "failed", "Resolve request expired. Send it again."
        if not valid_resolve(data) or re.fullmatch(r"[a-f0-9]{32}", repo_id) is None:
            return "failed", "Invalid Resolve request."
        try:
            with self.actions.lock:
                if self.actions.request_mode() == "paused":
                    return "dismissed", "Incoming fleet operations are paused."
                result = self._execute(sender, repo_id, data)
        except (FileNotFoundError, ValueError, RuntimeError, OSError):
            result = {"ok": False, "message": "Resolve could not verify the checkout, plan or requested file on this machine."}
        with self.lock:
            self._prune(self.results)
            self.results[request["id"]] = (time.monotonic() + TTL, sender, result)
        status = "done" if result.get("ok") else "failed"
        if result.get("applied"):
            try:
                self.actions.rescan(b"remote resolve applied")
            except OSError:
                pass  # Preserve the result if a refresh could not be requested.
        if result.get("applied"):
            message = {"commit-apply": "Checked commit applied.", "push-apply": "Checked push finished.",
                       "stash-apply": "Checked stash created."}.get(data["op"], "Resolve completed.")
        else:
            message = "Resolve response is available to the requesting device."
        return status, message

    def pending_details(self, request):
        """A local consent summary for the exact checkout and the reviewed push target."""
        if request.get("kind") != "resolve":
            return request
        data = request["resolve"]
        checkout = data.get("checkout", "")
        repo_id = request["items"][0].get("repo_id")
        try:
            choice = self._copies(repo_id).get(checkout) if checkout else None
        except (OSError, ValueError):
            choice = None
        details = [choice[1]] if choice else []
        if data["op"] == "push-apply":
            with self.lock:
                plan = self.plans.get((request["from"], repo_id, checkout, "push", data["plan_id"]))
            if plan and plan[0] > time.monotonic():
                details.append(plan[3])
            else:
                details.append("The checked plan is no longer available. Request a fresh push preview.")
        return {**request, "resolve_details": details}

    def _execute(self, sender, repo_id, data):
        op, checkout = data["op"], data.get("checkout") or ""
        copies = self._copies(repo_id)
        if op in ("changes", "branches", "stashes", "fetch") and not checkout:
            if not copies:
                raise ValueError("no checkout")
            if len(copies) != 1:
                return {"ok": True, "copies": [{"checkout": token, "label": label}
                                               for token, (_, label) in copies.items()]}
            checkout = next(iter(copies))
        if checkout not in copies:
            raise ValueError("checkout changed")
        path, label = copies[checkout]
        if op == "changes":
            return {"ok": True, "checkout": checkout, "label": label, **inspect_remote_changes(path)}
        if op == "untracked":
            return {"ok": True, **inspect_untracked(path, data["file"])}

        home = self.actions.security_settings()[0]
        args = {**data, "repo_id": repo_id, "checkout": 0}
        if op in ("branches", "stashes", "fetch"):
            response = repo_action(op, args, lambda _: (path,), home=home)
            if op == "fetch":
                return {"ok": response["ok"], "status": "fetched" if response["ok"] else "failed",
                        "checkout": checkout, "applied": response["ok"]}
            return {**response, "checkout": checkout}
        draft = (data.get("files"), data.get("message"))
        scope = (sender, repo_id, checkout, op.split("-")[0])

        if op.endswith("-apply"):
            with self.lock:
                previous = self.plans.pop((*scope, data["plan_id"]), None)
            if previous is None or previous[0] <= time.monotonic() or previous[1] != draft:
                return {"ok": False, "message": "Check this exact proposal on this checkout again before applying."}
            if op == "push-apply":
                from Special._security._push import push_checked
                response = push_checked(path, settings_home=home, apply=True, approve=data["plan_id"],
                                        expected_base=previous[2]).record()
                response.update(ok=response["status"] in ("pushed", "already-current"),
                                applied=response["status"] == "pushed")
            else:
                response = repo_action(op, args, lambda _: (path,), home=home)
        else:
            base = None
            if op == "push-plan":
                from Special._security._push import preview_remote_push
                response, base = preview_remote_push(path, settings_home=home)
            else:
                response = repo_action(op, args, lambda _: (path,), home=home)
            if response.get("ok") and response.get("plan_id"):
                with self.lock:
                    self._prune(self.plans)
                    target = f"{response.get('remote', '')} / {response.get('destination', '')}"
                    self.plans[(*scope, response["plan_id"])] = (time.monotonic() + TTL, draft, base, target)
        answer = _masked_outcome(response)
        answer["checkout"] = checkout
        if op in ("commit-plan", "stash-plan") and response.get("ok") and response.get("plan_id"):
            answer["draft"] = {"message": data["message"]}
            if op == "commit-plan":
                answer["draft"]["files"] = data["files"]
        return answer


def _masked_outcome(result):
    safe = {key: result[key] for key in ("ok", "applied", "status", "plan_id", "branch", "remote", "destination", "files", "untracked", "count")
            if key in result}
    scan = result.get("security")
    if scan:
        safe["security"] = {"status": scan["check_status"], "coverage": scan["coverage"],
                            "findings": [{"check": item["check"], "where": item["where"]}
                                         for item in scan["findings"][:30]],
                            "gaps": len(scan["gaps"]), "commits": scan["commits"]}
    if not safe.get("ok"):
        safe.pop("plan_id", None)
    return safe
