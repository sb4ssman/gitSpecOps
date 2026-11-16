"""The peer runtime. One kind of machine; no host, no client, no authority.

A peer does five things, and each is independent of the others failing:

1. **Observes itself** — one acknowledged inventory, then native filesystem events.
2. **Fetches its remotes** on a timer, read-only, so "behind" means behind the remote *now*.
3. **Publishes its own manifest** to every transport it has (a synced folder, a private repo),
   including an unchanged one once per slot, as a heartbeat.
4. **Serves its own dashboard** on loopback, always, from everything it can currently read.
5. **Talks to other peers when it can** — answers `GET /v1/manifest`, and pulls theirs.

Nothing above the tailnet tier may depend on Tailscale being installed, running, or logged in.
A peer with no network at all still observes, still publishes to a synced folder, and still
shows you a dashboard.

Peers **pull**; they never push to each other. An unreachable peer is therefore not an error
condition — it is simply not polled this cycle, and its last manifest is still readable through
the folder and repo transports.
"""
from __future__ import annotations

import json
from copy import deepcopy
import queue
import sys
import threading
import time
from pathlib import Path

from Elaborate._fleet.config import DEFAULT_FETCH_MINUTES, describe
from Elaborate._fleet.events import NativeEvents
from Elaborate._fleet.net import fetch_peer_report, local_identity, make_peer_server
from Special._sync.inventory import IncrementalObserver
from Elaborate._fleet.store import FleetStore, MAX_REPORT_BYTES
from Special._sync.git_client import DesktopIntegration
from Basic._files import atomic_write_bytes
from Elaborate._transport.folder import FolderTransport
from Elaborate._fleet.local_view import display_from_manifests
from Special._sync.manifest import fleet_id_for, names_over, without_names
from Special._sync.observer import fetch_repositories
from Elaborate._transport.repo import RepoTransport
from Elaborate._fleet.watcher import semantic_fingerprint

# How often Tailscale peers are asked for their reports, unless the machine's tailnet
# connection says otherwise (`seconds`). Every 30 seconds was far more often than anyone looks
# (the user, 2026-11-15); setup offers 1, 5 or 30 minutes.
PEER_POLL_SECONDS = 300.0


def poll_seconds(config: dict) -> float:
    tailnet = (config.get("transports") or {}).get("tailnet") or {}
    return float(tailnet.get("seconds") or PEER_POLL_SECONDS)
# How often each transport is re-read for other machines' manifests. The tray and the browser
# ask for the dashboard every few seconds, and every GitHub read is an API call: reading on
# every request spent most of the account's hourly API budget on one idle machine.
READ_SECONDS = {"folder": 15.0, "repo": 300.0}
# When Linux cannot watch every repository folder, the library is reread this often instead.
SWEEP_SECONDS = 600
READ_RETRY_SECONDS = 30.0
WATCH_RESTART_SECONDS = 5.0


def _log(message: str) -> None:
    """Flush every line: a peer normally runs under the tray or at login with stdout redirected
    to a file, where block buffering would leave the log empty exactly when it is needed."""
    print(message, flush=True)


def stale_after(config: dict) -> float:
    """Seconds after which a machine's report counts as stale, for this machine's settings.

    A report can only be as fresh as the slowest way it arrives. A peer publishing to a GitHub
    state repo every 30 minutes is not stale at minute 3; missing two deliveries is. The old
    fixed two minutes marked every quiet machine stale -- and every repository on it as needing
    attention -- shortly after its last edit.
    """
    transports = config.get("transports") or {}
    slowest = float(config.get("heartbeat") or 30)
    if transports.get("tailnet"):
        slowest = max(slowest, poll_seconds(config))
    for name in ("folder", "repo"):
        entry = transports.get(name)
        if entry:
            slowest = max(slowest, float(entry["seconds"]) + READ_SECONDS[name])
    return 2 * slowest + 60


def _overflowed(source) -> bool:
    """Whether the event source dropped changes it could not report one by one."""
    check = getattr(type(source), "overflowed", None)
    return callable(check) and source.overflowed() is True


class TransportPublisher:
    """Publishes this peer's manifest to each transport, paced per transport.

    A semantic change publishes as soon as that transport's minimum interval allows, so a synced
    folder sees new state in seconds while the GitHub Contents API stays within a sane budget.
    A failure costs that transport its next slot and nothing else -- one unreachable transport
    must never stop the others, or stop observation.
    """

    def __init__(self, transports: dict, clock=time.monotonic, names: dict | None = None):
        """`names`: per connection, whether its copy keeps readable names (missing: kept as given)."""
        self.clock = clock
        self.lock = threading.Lock()
        self.entries = []
        names = names or {}
        folder = transports.get("folder")
        if folder:
            self.entries.append({"name": "folder", "transport": FolderTransport(folder["path"]),
                                 "seconds": int(folder["seconds"]), "next": 0.0,
                                 "names": names.get("folder", True)})
        repo = transports.get("repo")
        if repo:
            self.entries.append({"name": "repo", "transport": RepoTransport(repo["name"]),
                                 "seconds": int(repo["seconds"]), "next": 0.0,
                                 "names": names.get("repo", True)})

    def publish(self, manifest: dict, changed: bool, log=_log) -> list[str]:
        """Queue this manifest for each transport, then deliver whatever is due.

        A change is always queued, and delivered at most once per transport slot. A synced
        folder also gets unchanged state once per slot: that re-send is the heartbeat that lets
        other machines tell a quiet machine from one that is switched off, and it costs nothing.

        The GitHub state repository never gets a heartbeat (the user, 2026-11-12): every write
        there is a commit kept forever, so it writes only when something changed, at most once
        per slot (30 minutes by default), and only when GitHub can be reached (a failed write
        waits for the next slot). How a machine heard only through the repository proves it is
        alive is part of the state repository's open review.
        """
        now = self.clock()
        for entry in self.entries:
            heartbeat = entry["name"] != "repo" and now >= entry["next"]
            if changed or entry.get("pending") is not None or heartbeat:
                # Each connection carries names only if its own setting says so.
                entry["pending"] = deepcopy(manifest if entry.get("names", True) else without_names(manifest))
        return self.flush(log=log)

    def flush(self, log=_log) -> list[str]:
        """Deliver due cached status; never inspect a repository or advance its timestamp."""
        published = []
        now = self.clock()
        for entry in self.entries:
            due = now >= entry["next"]
            if not due:
                continue
            manifest = entry.get("pending")
            if manifest is None:
                continue
            entry["next"] = now + entry["seconds"]
            try:
                if isinstance(entry["transport"], RepoTransport):
                    health = entry["transport"].doctor()
                    if not health.get("private") or not health.get("permissions"):
                        raise ValueError("state repository is no longer private and writable")
                entry["transport"].write_own_manifest(manifest["machine_id"], manifest,
                                                      compress=True)
                entry["pending"] = None
                published.append(entry["name"])
            except Exception as exc:  # noqa: BLE001 - a transport may never break the peer
                log(f"{entry['name']} transport failed (will retry at its next slot): {exc}")
        return published

    def read_all(self) -> tuple[list[dict], list[str]]:
        """Every manifest every transport can see, re-read at most once per transport interval.

        Shared by every dashboard request, so the tray, a browser tab and a second browser tab
        together cost one read per interval rather than one each per refresh.
        """
        from Elaborate._fleet.aggregate import load_manifests

        manifests, issues = [], []
        with self.lock:
            now = self.clock()
            for entry in self.entries:
                if now >= entry.get("read_due", 0.0):
                    try:
                        entry["read"] = load_manifests(entry["transport"])
                        entry["read_due"] = now + READ_SECONDS.get(entry["name"], 15.0)
                    except Exception as exc:  # noqa: BLE001
                        entry["read"] = ([], [f"{entry['name']} transport unreadable: {exc}"])
                        entry["read_due"] = now + READ_RETRY_SECONDS
                found, problems = entry["read"]
                manifests.extend(found)
                issues.extend(problems)
        return manifests, issues


class PeerNetwork:
    """The optional tailnet tier: answer peers, and pull from them. Degrades to nothing."""

    def __init__(self, config: dict, own_report, store: FleetStore, log=_log, shared=None, adopt_name=None,
                 requests=None, own_changes=None):
        self.log = log
        self.config = config
        self.store = store
        self.own_report = own_report
        self.shared = shared  # shared_policy.SharedPolicy: protected values pulled and served
        self.adopt_name = adopt_name  # saves a newer fleet name heard from a machine of this fleet
        self.requests = requests  # requests.RequestBook: asked of others, asked of this machine
        self.own_changes = own_changes  # repo_id -> this machine's uncommitted-work summary
        self.addresses: dict[str, str] = {}  # machine_id -> its Tailscale address, from the last round
        self.server = None
        self.identity = None
        self.port = int((config.get("transports") or {}).get("tailnet", {}).get("port") or 0)
        self.knocked = threading.Event()  # another machine asked to be pulled now (/v1/knock)

    @property
    def enabled(self) -> bool:
        return bool((self.config.get("transports") or {}).get("tailnet"))

    def start(self) -> bool:
        """Returns whether the tailnet tier actually came up. Never raises."""
        if not self.enabled:
            return False
        try:
            self.identity = local_identity()
        except (OSError, ValueError) as exc:
            # Tailscale missing, stopped, or logged out. Everything else still works.
            self.log(f"Tailnet tier unavailable ({exc}). Observation, transports and the local "
                     "dashboard are unaffected.")
            return False
        allowed = (self.config["transports"]["tailnet"].get("allowed_login")
                   or self.identity["login"])
        self.config["transports"]["tailnet"]["allowed_login"] = allowed
        if self.identity["login"] != allowed:
            self.log("Tailscale user changed; tailnet tier disabled pending review.")
            return False
        try:
            self.server = make_peer_server((self.identity["ip"], self.port), self.own_report,
                                           self.config["fleet_secret"], allowed,
                                           own_settings=self.shared.record if self.shared else None,
                                           own_name=lambda: self.config.get("fleet_name"),
                                           on_knock=self.knocked.set,
                                           own_requests=self.requests.published if self.requests else None,
                                           own_changes=self.own_changes)
            threading.Thread(target=self.server.serve_forever, daemon=True).start()
        except OSError as exc:
            self.log(f"Could not listen for peers on port {self.port}: {exc}")
            self.server = None
            return False
        self.log(f"Answering peers at http://{self.identity['ip']}:{self.port}/ "
                 "(read-only; peers pull, nothing is pushed)")
        return True

    def poll(self) -> int:
        """Pull every reachable peer's current report into the local cache."""
        if self.server is None:
            return 0
        from Elaborate._fleet.net import discover_hosts

        try:
            candidates = discover_hosts(port=self.port, timeout=0.5)
        except (OSError, ValueError):
            return 0
        learned = 0
        for host in candidates:
            if not host.get("serving"):
                continue  # off, asleep, or not running the app: normal, not an error
            report = fetch_peer_report(host["ip"], self.port)
            if not report:
                continue
            try:
                self.store.put(report["manifest"]["machine_id"], report)
                learned += 1
            except (ValueError, KeyError, OSError):
                continue  # a peer on a different fleet, or a malformed report
            machine_id = report["manifest"]["machine_id"]
            self.addresses[machine_id] = host["ip"]
            self.merge_settings(host)
            self.merge_name(host)
            self.merge_requests(host, machine_id)
        return learned

    def merge_requests(self, host, machine_id) -> None:
        """Take the requests this peer has addressed to this machine (requests.py)."""
        if self.requests is None:
            return
        from Elaborate._fleet.net import FleetClient
        try:
            new = self.requests.receive(FleetClient(f"http://{host['ip']}:{self.port}").request("/v1/requests"),
                                        machine_id)
        except (OSError, ValueError, KeyError, TypeError):
            return  # an older peer without requests
        if new:
            self.log(f"{new} request(s) from {host.get('label', 'another machine')} wait on this machine's page.")

    def ask(self, machine_id: str, path: str):
        """A read from one fleet machine by its id, through its Tailscale address."""
        from Elaborate._fleet.net import FleetClient
        address = self.addresses.get(machine_id)
        if not address:
            raise ValueError("that machine is not answering on Tailscale right now")
        return FleetClient(f"http://{address}:{self.port}").request(path)

    def merge_name(self, host) -> None:
        """The fleet's name as the newest machine to name it says (a rename spreads)."""
        if self.adopt_name is None:
            return
        from Elaborate._fleet.net import FleetClient
        from Special._sync.manifest import fleet_id_for
        try:
            about = FleetClient(f"http://{host['ip']}:{self.port}").request("/v1/fleet")
        except (OSError, ValueError):
            return
        named = about.get("fleet_name") if isinstance(about, dict) else None
        if (not isinstance(named, dict) or about.get("fleet_id") != fleet_id_for(self.config["fleet_secret"])
                or not isinstance(named.get("name"), str) or not isinstance(named.get("at"), str)):
            return
        mine = self.config.get("fleet_name") or {}
        if named["at"] > str(mine.get("at", "")) and named["name"] != mine.get("name"):
            try:
                self.adopt_name(named)
            except (OSError, ValueError):
                return
            self.config["fleet_name"] = {"name": named["name"], "at": named["at"]}
            self.log(f"The fleet is called {named['name']} (named on {host.get('label', 'another machine')}).")

    def knock_others(self) -> int:
        """Ask every running machine on the tailnet to pull this one now (after a start or a join)."""
        if self.server is None:
            return 0
        from Elaborate._fleet.net import FleetClient, discover_hosts
        try:
            hosts = [host for host in discover_hosts(port=self.port, timeout=0.5) if host.get("serving")]
        except (OSError, ValueError):
            return 0
        knocked = 0
        for host in hosts:
            try:
                FleetClient(host["url"]).request("/v1/knock")
                knocked += 1
            except (OSError, ValueError):
                continue  # an older machine without /v1/knock: it pulls at its next round
        return knocked

    def merge_settings(self, host) -> None:
        """Pull a peer's shared protected values and merge them (shared_policy.py). Counts only
        in the log: the values themselves never are."""
        if self.shared is None:
            return
        from Elaborate._fleet.net import FleetClient
        try:
            result = self.shared.receive(FleetClient(f"http://{host['ip']}:{self.port}").request("/v1/settings"))
        except (OSError, ValueError, KeyError, TypeError):
            return  # an older peer without shared settings, or one in another fleet
        if result["applied"] or result["asked"]:
            self.log(f"Shared protected values from {host.get('label', 'a peer')}: "
                     + "; ".join(result["applied"] + [f"{len(result['asked'])} change(s) to answer "
                                                       "on the App & setup tab"] * bool(result["asked"])))

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None


def run_peer(config: dict, config_dir: Path, stopping: threading.Event, *,
             on_ready=None, event_source=None, once: bool = False, log=_log, settings_home=None,
             serve=None) -> int:
    """Run this peer until `stopping` is set.

    `serve(document, desktop_action, fleet_action) -> (server, url)` is how a presentation
    (App) attaches. Without it the peer runs headless: it observes, publishes and talks to
    other peers, and shows nothing itself."""
    fleet_id = fleet_id_for(config["fleet_secret"])
    store = FleetStore(config_dir / "fleet.sqlite3", fleet_id)
    publisher = TransportPublisher(config.get("transports") or {},
                                   names={name: names_over(config, name) for name in ("folder", "repo")})
    observer = IncrementalObserver(config)
    # What this peer is doing right now, in words, for the tray's status line and the web view:
    # people should see the work happen. Counts only; never a path or a repository name.
    activity = {"phase": "starting", "text": "starting up", "done": 0, "total": 0}

    def doing(phase: str, text: str, done: int = 0, total: int = 0) -> None:
        activity.update(phase=phase, text=text, done=done, total=total)

    def watching_text() -> str:
        """Folders and repositories are different counts: a repository with a second copy here
        (a backup library, a duplicate clone) is two folders and one repository."""
        try:
            folders, repositories = len(observer.paths), len(observer.local_repositories())
        except TypeError:  # a stand-in observer in tests
            return "watching for changes"
        extra = folders - repositories
        return (f"watching {folders} repository folders for changes"
                + (f" ({repositories} repositories; {extra} folders are second copies)" if extra > 0 else ""))
    from Elaborate._recovery.runtime import RecoveryRuntime
    recovery = RecoveryRuntime(config, observer, log=log)
    stale_seconds = stale_after(config)
    fetch_minutes = int(config.get("fetch_minutes", DEFAULT_FETCH_MINUTES))
    heartbeat_seconds = float(config.get("heartbeat") or 30)
    # `local` is everything this machine observes and is only ever rendered here; `report` is
    # the filtered view peers and transports receive. Keeping them apart is the whole point of
    # a publish basket: withheld work must still be visible to the person sitting at the machine.
    latest = {"report": None, "local": None, "withheld": set(), "paths": ()}
    watching = {"incomplete": False}  # Linux's watch limit reached: the library is reread on a timer

    def save_client(choice):
        # Only local UI choices reach here; executable paths never cross a transport.
        from Elaborate._fleet.config import save_client_choice

        save_client_choice(config_dir, config, choice)

    desktop = DesktopIntegration(config.get("git_client"), observer.local_repositories, save_client)
    action_lock = threading.Lock()

    def security_settings():
        """The profile as it is now, not as it was when the peer started: a policy change made
        from the web view (or by hand) applies to the next check without a restart. Each check
        still verifies that the profile does not change while it runs."""
        from Special._settings.fleet import load_fleet_settings

        home = getattr(getattr(config, "snapshot", None), "home", settings_home)
        return home, load_fleet_settings(home)

    from Special._security._audit import AuditJobs, engines_status
    from Special._security._policy_edit import policy_change, policy_view
    audits = AuditJobs(observer.local_checkouts, settings=security_settings)

    def dashboard_action(action, payload):
        """Local dashboard actions call the same headless operations as terminal routes."""
        if action == "security-engines":
            return {"engines": engines_status()}
        if action == "security-policy":
            return policy_view(security_settings()[0])
        if action == "security-policy-change":
            with action_lock:
                return policy_change(security_settings()[0], payload)
        if action == "security-start":
            return audits.start(payload)
        if action == "security-status":
            return audits.status()
        if action == "security-stop":
            return audits.stop()
        if action == "security-preview":
            from Special._security._advice import inspect_registered
            with action_lock:
                home, snapshot = security_settings()
                return inspect_registered(payload, observer.local_checkouts, settings_home=home, expected_settings=snapshot)
        if action in ("request-send", "request-withdraw", "request-answer", "request-clear", "changes"):
            return request_action(action, payload)
        if action != "catchup-preview" or payload:
            raise ValueError("unsupported fleet dashboard action")
        from Special._sync.actions import plan_catchup, render_catchup

        with action_lock:
            plan = plan_catchup(observer.paths)
        return {"message": render_catchup(plan), "action": "catchup-preview"}

    # Protected values shared with the fleet (shared_policy.py): over Tailscale whenever this
    # machine is in a fleet; sealed through the synced folder when that is turned on.
    from Elaborate._fleet.shared_policy import SharedPolicy
    shared = (SharedPolicy(security_settings()[0], config_dir, fleet_id=fleet_id,
                           machine_id=config["machine_id"], label=config["label"])
              if config.get("transports") else None)
    def adopt_name(named):
        from Elaborate._fleet.setup_state import name_fleet
        name_fleet(security_settings()[0], config_dir, name=named["name"], at=named["at"])
    # Requests between machines, and what a copy's uncommitted work is (requests.py, changes.py).
    from Elaborate._fleet.requests import RequestBook, run_request
    book = RequestBook(config_dir, config["machine_id"], config["label"])

    def own_changes(repo_id):
        from Special._sync.changes import working_changes
        copies = []
        for path in observer.local_checkouts(repo_id):
            try:
                copies.append(working_changes(path))
            except ValueError as exc:
                copies.append({"files": [], "count": 0, "summary": str(exc)})
        return {"machine": config["label"], "copies": copies}

    def text(value, limit=200):
        return str(value or "")[:limit]

    def request_action(action, payload):
        if action == "request-send":
            items = [{key: text(item.get(key)) for key in ("repo_id", "host", "owner", "name", "folder")}
                     for item in payload.get("items") or [] if isinstance(item, dict)]
            if text(payload.get("to")) == config["machine_id"]:
                # Asked of this machine, from its own page: the person is here, so it runs now,
                # with the same safe operations (the user, 2026-11-16).
                request = {"kind": text(payload.get("kind")), "items": items, "from_label": config["label"],
                           "to_label": config["label"]}
                if request["kind"] not in ("pull", "clone") or not items:
                    raise ValueError("choose pull or clone, and at least one repository")
                with action_lock:
                    result = run_request(request, observer.local_checkouts, config["roots"])
                book.log("ran here", request, result)
                atomic_write_bytes(config_dir / "fleet-rescan.request", b"ran here\n")
                return {"message": f"Done here.\n{result}"}
            sent = book.send(text(payload.get("to")), text(payload.get("to_label")), text(payload.get("kind")), items)
            book.log("asked", sent)
            threading.Thread(target=network.knock_others, daemon=True).start()  # so it is picked up now
            return {"sent": sent, "message": f"Asked {sent['to_label']}; it shows on that machine's page."}
        if action == "request-withdraw":
            book.withdraw(text(payload.get("id")))
            return {"message": "Withdrawn."}
        if action == "request-clear":
            dropped = book.clear(everything_sent=bool(payload.get("everything_sent")))
            return {"message": f"Cleared {dropped}. The task log keeps the record."}
        if action == "changes":
            repo_id, machine_id = text(payload.get("repo_id")), text(payload.get("machine_id"))
            if machine_id == config["machine_id"]:
                return own_changes(repo_id)
            return network.ask(machine_id, f"/v1/changes/{repo_id}")
        request = next((item for item in book.incoming() if item["id"] == payload.get("id")), None)
        if request is None or request["status"] != "waiting":
            raise ValueError("that request is no longer waiting; reload")
        if not payload.get("accept"):
            book.log("dismissed", request)
            return book.settle(request["id"], "dismissed", "Dismissed here.")
        with action_lock:
            result = run_request(request, observer.local_checkouts, config["roots"])
        book.log("applied", request, result)
        atomic_write_bytes(config_dir / "fleet-rescan.request", b"request applied\n")  # see the result
        threading.Thread(target=network.knock_others, daemon=True).start()  # the asker learns now
        return book.settle(request["id"], "done", result)

    network = PeerNetwork(config, lambda: latest["report"], store, log=log, shared=shared, adopt_name=adopt_name,
                          requests=book, own_changes=own_changes)

    def sealed_folder_loop():
        """The shared protected values through the synced folder, sealed (sealed.py)."""
        from Elaborate._fleet import sealed
        root = (config.get("transports") or {}).get("folder", {}).get("path")
        while True:
            try:
                sealed.write_own(root, shared.record(), config["fleet_secret"], config["machine_id"])
                for record in sealed.read_others(root, config["fleet_secret"], config["machine_id"]):
                    result = shared.receive(record)
                    if result["applied"] or result["asked"]:
                        log("Shared protected values through the synced folder: "
                            f"{len(result['applied'])} change(s) made, {len(result['asked'])} to answer")
            except (OSError, ValueError) as exc:
                log(f"Sealed settings through the synced folder failed: {exc}")
            if stopping.wait(poll_seconds(config)):
                return

    def sources() -> tuple[list[dict], list[str], dict]:
        """Everything this machine can currently see, newest-per-machine resolved downstream."""
        manifests, issues = publisher.read_all()
        # Drop this machine's own manifest as read back from a transport. It is at best a stale
        # echo of what `latest["local"]` already holds, and with a publish basket it is also a
        # *narrower* one -- letting it win would hide withheld repositories from their owner.
        if latest["local"] is not None:
            manifests = [item for item in manifests
                         if item.get("machine_id") != config["machine_id"]]
        names = {}
        for cached in store.reports():
            manifests.append(cached["manifest"])
            names.update(cached.get("names") or {})
        if latest["local"] is not None:
            manifests.append(latest["local"]["manifest"])
            names.update(latest["local"].get("names") or {})
        return manifests, issues, names

    def document():
        manifests, issues, names = sources()
        if latest["local"] is not None:
            issues = list(issues) + list(latest["local"].get("issues") or [])
        if pending_new:
            listed = ", ".join(sorted(p.name for p in sorted(pending_new))[:5])
            more = "" if len(pending_new) <= 5 else f" (+{len(pending_new) - 5} more)"
            issues = list(issues) + [
                f"{len(pending_new)} new repository(ies) appeared in your library and are not "
                f"observed yet: {listed}{more}. Run 'fleet rescan' to include them."]
        if watching["incomplete"]:
            issues = list(issues) + [
                f"Linux's file-watch limit was reached, so some repositories are not watched for "
                f"changes; the library is reread every {SWEEP_SECONDS // 60} minutes instead. To "
                "watch everything, raise the limit: sudo sysctl fs.inotify.max_user_watches=524288 "
                "(add fs.inotify.max_user_watches=524288 to /etc/sysctl.conf to keep it)."]
        if shared is not None:
            try:
                waiting = len(shared.questions())
            except (OSError, ValueError):
                waiting = 0
            if waiting:
                issues = list(issues) + [
                    f"{waiting} change(s) to protected values made on other machines wait for your "
                    "answer: App & setup tab, Shared protected values."]
        document = display_from_manifests(
            manifests, fleet_id=fleet_id, names=names, issues=issues,
            stale_seconds=stale_seconds,
            settings={"machine_id": config["machine_id"],
                      "transports": describe(config),
                      "fleet_name": (config.get("fleet_name") or {}).get("name"),
                      "transport_config": config.get("transports") or {},
                      "debounce_seconds": config["debounce_seconds"],
                      "fetch_seconds": fetch_minutes * 60,
                      "root_count": len(config["roots"]),
                      "git_client": desktop.settings(),
                      "local_repo_ids": list(observer.local_repositories()),
                      "security_available": True,
                      "new_repositories": len(pending_new),
                      "baskets": config["baskets"],
                      "recovery": config.get("recovery") or {"location": None, "confirmed": False,
                                                                   "policies": {}},
                      "withheld_repo_ids": sorted(latest["withheld"]),
                      "unobserved_count": observer.excluded_from_observation})
        document["activity"] = dict(activity)
        incoming = book.incoming()
        document["requests"] = {"waiting": [item for item in incoming if item["status"] == "waiting"],
                                "answered": [item for item in incoming if item["status"] != "waiting"][:10],
                                "sent": book.outgoing()}
        return document

    dashboard, url = (serve(document, desktop.handle, dashboard_action) if serve is not None
                      else (None, None))
    if url:
        log(f"Dashboard: {url}")
    else:
        log("Running headless: no dashboard is served by this process.")
    log(f"Transports:\n{describe(config)}")

    if shared is not None and config.get("seal_settings") and (config.get("transports") or {}).get("folder"):
        from Elaborate._fleet import sealed
        if sealed.available():
            threading.Thread(target=sealed_folder_loop, name="fleet-sealed-settings", daemon=True).start()
        else:
            log("Sealing shared settings for the synced folder needs the cryptography package "
                "(setup, or the App & setup tab, installs it); Tailscale still carries them.")

    if network.start():
        def poll_loop():
            # Off the observation loop: an unreachable peer can take seconds to time out, and
            # that must never delay noticing a local edit.
            while True:
                network.knocked.clear()
                try:
                    network.poll()
                except Exception as exc:  # noqa: BLE001 - the tailnet tier may never stop the peer
                    log(f"Tailnet poll failed: {exc}")
                # The next round, or sooner when a machine that just started or joined knocks.
                deadline = time.monotonic() + poll_seconds(config)
                while time.monotonic() < deadline and not network.knocked.is_set():
                    if stopping.wait(1.0):
                        return

        threading.Thread(target=poll_loop, name="fleet-poll", daemon=True).start()
    if on_ready is not None:
        on_ready({"url": url, "mode": "peer", "label": config["label"],
                  "config_dir": config_dir, "dashboard": document,
                  "rescan": lambda: atomic_write_bytes(
                      config_dir / "fleet-rescan.request", b"inventory requested\n"),
                  "catchup_preview": lambda: dashboard_action("catchup-preview", {})})

    pending_new: set = set()

    def stop_serving():
        network.stop()
        if dashboard is not None:
            dashboard.shutdown()
            dashboard.server_close()

    def open_events():
        # Linux watches only the repositories and the folders leading to them (events.py).
        return event_source or NativeEvents([Path(root) for root in config["roots"]],
                                            repositories=list(observer.paths))

    def watch_note(events) -> None:
        if getattr(events, "incomplete", False):
            log("Linux's file-watch limit was reached, so some folders are not watched; the "
                f"library is reread every {SWEEP_SECONDS // 60} minutes instead.")
        watching["incomplete"] = bool(getattr(events, "incomplete", False))

    # Until the observation loop's own try/finally takes over, a failure here must still stop the
    # web view: on one machine (2026-11-16) the watcher failed after a 20-minute walk and the page
    # showed "putting this machine's state together" for good, served by a peer that had stopped.
    try:
        started = time.monotonic()
        doing("finding", "finding the repositories in your library")
        count = observer.inventory(progress=lambda done, total, _path: doing(
            "reading", f"reading Git status: {done} of {total} repositories", done, total))
        doing("publishing", f"found {count} repositories; putting this machine's state together", count, count)
        log(f"Initial inventory found {count} repositories in {time.monotonic() - started:.1f}s. "
            "Filesystem events now drive targeted checks. Ctrl-C stops.")
        doing("publishing", f"found {count} repositories; setting up change watching", count, count)
        source = open_events()
        watch_note(source)
    except Exception as exc:
        doing("stopped", f"stopped: {exc}")
        print(f"error: {exc}", file=sys.stderr, flush=True)  # the tray's icon says why
        stop_serving()
        raise
    next_sweep = time.monotonic() + SWEEP_SECONDS
    request_path = config_dir / "fleet-rescan.request"
    fingerprint = None
    next_heartbeat = 0.0
    fetch_results: queue.Queue = queue.Queue()

    def fetch_loop():
        """Fetch every observed repository on a timer so "behind" means behind the remote now.

        Read-only toward everything the user owns: `git fetch` moves only remote-tracking refs,
        never a branch, the index, or a file. It never prompts for credentials. A repository that
        cannot be fetched keeps its last-known counts, and the dashboard lists the failure.
        """
        # The first fetch comes one full interval after start, not at start: starting the app
        # is not a reason to fetch every repository (the user, 2026-11-15). "Fetch now" is on
        # the tray's menu for when it is wanted.
        delay = fetch_minutes * 60
        while not stopping.wait(delay):
            delay = fetch_minutes * 60
            paths = list(latest["paths"])
            if paths:
                doing("fetching", f"fetching remotes (read-only): {len(paths)} repositories", 0, len(paths))
                fetched, problems = fetch_repositories(paths)
                fetch_results.put((paths, fetched, problems))
                doing("idle", watching_text())

    if fetch_minutes > 0 and not once:
        threading.Thread(target=fetch_loop, name="fleet-fetch", daemon=True).start()

    def observe(reason: str):
        nonlocal fingerprint, next_heartbeat
        local = observer.report()
        shared, withheld = observer.shared_report(local)
        # What Tailscale peers may fetch: without names unless that connection carries them.
        live = shared if names_over(config, "tailnet") else {
            **shared, "names": {}, "manifest": without_names(shared["manifest"])}
        raw = json.dumps(live).encode()
        if len(raw) > MAX_REPORT_BYTES or len(json.dumps(shared).encode()) > MAX_REPORT_BYTES:
            raise ValueError("report exceeds the size limit")
        atomic_write_bytes(config_dir / "fleet-latest.json", raw)
        latest["local"], latest["report"], latest["withheld"] = local, live, withheld
        latest["paths"] = observer.paths
        next_heartbeat = time.monotonic() + heartbeat_seconds
        # Fingerprinted on the shared view, so a change confined to a withheld namespace
        # correctly publishes nothing new -- only the per-slot heartbeat.
        current = semantic_fingerprint(shared["manifest"]) + json.dumps(
            [shared["names"], shared["issues"]], sort_keys=True)
        changed = current != fingerprint
        fingerprint = current
        published = publisher.publish(shared["manifest"], changed, log=log)
        if changed:
            held = f", {len(withheld)} withheld by baskets" if withheld else ""
            log(f"Observed {len(local['manifest']['repositories'])} repos ({reason}){held}"
                + (f"; published to {', '.join(published)}" if published else ""))
        return changed

    try:
        # Initial inventory is a deliberate quiet boundary too.  Capture validates that the
        # checkout stayed unchanged while read, so an editor mid-write is deferred to its next
        # event rather than yielding a mixed snapshot.
        recovery.capture_paths(observer.paths)
        recovery.acknowledge_available()
        observe("initial inventory")
        # Now there is a report to pull: ask the other machines to pull it at once, so a machine
        # that just started or joined appears on their maps now, not at their next round.
        threading.Thread(target=network.knock_others, name="fleet-knock", daemon=True).start()
        doing("idle", watching_text())
        if once:
            return 0
        while not stopping.is_set():
            try:
                force_inventory = False
                try:
                    changed = source.wait(timeout=1.0, debounce=config["debounce_seconds"])
                except OSError as exc:
                    log(f"Filesystem watching stopped ({exc}). Restarting it and taking a fresh "
                        "inventory, because changes made meanwhile were not seen.")
                    source.close()
                    if stopping.wait(WATCH_RESTART_SECONDS):
                        break
                    source = open_events()
                    changed, force_inventory = set(), True
                else:
                    if _overflowed(source):
                        log("More filesystem changes arrived at once than could be tracked "
                            "individually; taking a fresh inventory.")
                        force_inventory = True
                reason = None
                if getattr(source, "incomplete", False) and time.monotonic() >= next_sweep:
                    force_inventory, next_sweep = True, time.monotonic() + SWEEP_SECONDS
                if force_inventory or request_path.exists():
                    request_path.unlink(missing_ok=True)
                    started = time.monotonic()
                    doing("finding", "rescanning: finding the repositories in your library")
                    count = observer.inventory(progress=lambda done, total, _path: doing(
                        "reading", f"rescanning: reading Git status: {done} of {total}", done, total))
                    if event_source is None:  # watch what this inventory found, new clones included
                        source.close()
                        source = open_events()
                        watch_note(source)
                    doing("idle", watching_text())
                    pending_new.clear()
                    reason = f"inventory: {count} repos in {time.monotonic() - started:.1f}s"
                elif changed:
                    affected = observer.affected_repositories(changed)
                    touched = observer.refresh(changed)
                    if touched:
                        reason = f"filesystem change: checked {touched} repo(s)"
                        recovery.capture_paths(affected)
                    # Events that mapped to no known checkout used to be dropped entirely, so a
                    # freshly cloned repository stayed invisible until someone ran rescan.
                    appeared = observer.detect_new_checkouts(changed) - pending_new
                    if appeared:
                        pending_new.update(appeared)
                        log(f"Noticed {len(appeared)} new repository(ies) in your library: "
                            + ", ".join(sorted(path.name for path in appeared)[:5])
                            + ". Run 'fleet rescan' to start observing them.")
                while True:
                    try:
                        paths, fetched, problems = fetch_results.get_nowait()
                    except queue.Empty:
                        break
                    observer.apply_fetch(fetched, problems, paths)
                    note = f"fetched remotes for {len(fetched)} of {len(paths)} repo(s)"
                    reason = f"{reason}; {note}" if reason else note
                if reason:
                    recovery.acknowledge_available()
                    observe(reason)
                elif time.monotonic() >= next_heartbeat:
                    recovery.acknowledge_available()
                    observe("heartbeat")
                published = publisher.flush(log=log)
                if published:
                    log(f"Published pending status to {', '.join(published)}")
            except (OSError, ValueError) as exc:
                log(f"Observation cycle failed; last state retained: {exc}")
    except Exception as exc:
        doing("stopped", f"stopped: {exc}")
        print(f"error: {exc}", file=sys.stderr, flush=True)
        raise
    finally:
        source.close()
        stop_serving()
    return 0
