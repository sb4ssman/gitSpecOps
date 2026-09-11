"""The peer runtime. One kind of machine; no host, no client, no authority.

A peer does four things, and each is independent of the others failing:

1. **Observes itself** — one acknowledged inventory, then native filesystem events.
2. **Publishes its own manifest** to every transport it has (a synced folder, a private repo).
3. **Serves its own dashboard** on loopback, always, from everything it can currently read.
4. **Talks to other peers when it can** — answers `GET /v1/manifest`, and pulls theirs.

The ordering matters. Tailscale is step 4, so nothing above it may depend on Tailscale being
installed, running, or logged in. A peer with no network at all still observes, still publishes
to a synced folder, and still shows you a dashboard. That is the property the old host/client
split destroyed, and the reason this module exists.

Peers **pull**; they never push to each other. An unreachable peer is therefore not an error
condition — it is simply not polled this cycle, and its last manifest is still readable through
the folder and repo transports.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from fleet_config import describe
from fleet_events import NativeEvents
from fleet_net import fetch_peer_report, local_identity, make_peer_server
from fleet_observer import IncrementalObserver
from fleet_store import FleetStore, MAX_REPORT_BYTES
from folder_transport import FolderTransport, atomic_write_bytes
from local_view import display_from_manifests
from manifest import fleet_id_for
from repo_transport import RepoTransport
from watcher import semantic_fingerprint

PEER_POLL_SECONDS = 20.0


def _log(message: str) -> None:
    """Flush every line: a peer normally runs under the tray or at login with stdout redirected
    to a file, where block buffering would leave the log empty exactly when it is needed."""
    print(message, flush=True)


class TransportPublisher:
    """Publishes this peer's manifest to each transport, paced per transport.

    A semantic change publishes as soon as that transport's minimum interval allows, so a synced
    folder sees new state in seconds while the GitHub Contents API stays within a sane budget.
    A failure costs that transport its next slot and nothing else -- one unreachable transport
    must never stop the others, or stop observation.
    """

    def __init__(self, transports: dict, clock=time.monotonic):
        self.clock = clock
        self.entries = []
        folder = transports.get("folder")
        if folder:
            self.entries.append({"name": "folder", "transport": FolderTransport(folder["path"]),
                                 "seconds": int(folder["seconds"]), "next": 0.0})
        repo = transports.get("repo")
        if repo:
            self.entries.append({"name": "repo", "transport": RepoTransport(repo["name"]),
                                 "seconds": int(repo["seconds"]), "next": 0.0})

    def publish(self, manifest: dict, changed: bool, log=_log) -> list[str]:
        published = []
        now = self.clock()
        for entry in self.entries:
            due = now >= entry["next"]
            if not due:
                continue
            if not changed and entry["next"] != 0.0:
                # Nothing new to say; keep the slot for when there is.
                continue
            entry["next"] = now + entry["seconds"]
            try:
                if isinstance(entry["transport"], RepoTransport):
                    health = entry["transport"].doctor()
                    if not health.get("private") or not health.get("permissions"):
                        raise ValueError("state repository is no longer private and writable")
                entry["transport"].write_own_manifest(manifest["machine_id"], manifest,
                                                      compress=True)
                published.append(entry["name"])
            except Exception as exc:  # noqa: BLE001 - a transport may never break the peer
                log(f"{entry['name']} transport failed (will retry at its next slot): {exc}")
        return published

    def read_all(self) -> tuple[list[dict], list[str]]:
        """Every manifest every transport can currently see, plus what could not be read."""
        from aggregate import load_manifests

        manifests, issues = [], []
        for entry in self.entries:
            try:
                found, problems = load_manifests(entry["transport"])
                manifests.extend(found)
                issues.extend(problems)
            except Exception as exc:  # noqa: BLE001
                issues.append(f"{entry['name']} transport unreadable: {exc}")
        return manifests, issues


class PeerNetwork:
    """The optional tailnet tier: answer peers, and pull from them. Degrades to nothing."""

    def __init__(self, config: dict, own_report, store: FleetStore, log=_log):
        self.log = log
        self.config = config
        self.store = store
        self.own_report = own_report
        self.server = None
        self.identity = None
        self.port = int((config.get("transports") or {}).get("tailnet", {}).get("port") or 0)

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
                                           self.config["fleet_secret"], allowed)
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
        from fleet_net import discover_hosts

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
        return learned

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None


def run_peer(config: dict, config_dir: Path, stopping: threading.Event, *,
             on_ready=None, event_source=None, once: bool = False, log=_log) -> int:
    """Run this peer until `stopping` is set."""
    fleet_id = fleet_id_for(config["fleet_secret"])
    store = FleetStore(config_dir / "fleet.sqlite3", fleet_id)
    publisher = TransportPublisher(config.get("transports") or {})
    observer = IncrementalObserver(config)
    latest = {"report": None}

    network = PeerNetwork(config, lambda: latest["report"], store, log=log)

    def sources() -> tuple[list[dict], list[str], dict]:
        """Everything this machine can currently see, newest-per-machine resolved downstream."""
        manifests, issues = publisher.read_all()
        names = {}
        for cached in store.reports():
            manifests.append(cached["manifest"])
            names.update(cached.get("names") or {})
        if latest["report"] is not None:
            manifests.append(latest["report"]["manifest"])
            names.update(latest["report"].get("names") or {})
        return manifests, issues, names

    def document():
        manifests, issues, names = sources()
        return display_from_manifests(manifests, fleet_id=fleet_id, names=names, issues=issues,
                                      settings={"transports": describe(config),
                                                "root_count": len(config["roots"])})

    from local_dashboard import make_local_server
    from ui_assets import load_ui_assets

    local_port = int(config["local_port"])
    dashboard = make_local_server(("127.0.0.1", local_port), document, load_ui_assets())
    threading.Thread(target=dashboard.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{local_port}/"
    log(f"Dashboard: {url}")
    log("This dashboard is local. It needs no other machine and no Tailscale.")
    log(f"Transports:\n{describe(config)}")

    network.start()
    if on_ready is not None:
        on_ready({"url": url, "mode": "peer", "label": config["label"],
                  "config_dir": config_dir, "dashboard": document,
                  "rescan": lambda: atomic_write_bytes(
                      config_dir / "fleet-rescan.request", b"inventory requested\n")})

    started = time.monotonic()
    count = observer.inventory()
    log(f"Initial inventory found {count} repositories in {time.monotonic() - started:.1f}s. "
        "Filesystem events now drive targeted checks; there is no periodic scan. Ctrl-C stops.")
    source = event_source or NativeEvents([Path(root) for root in config["roots"]])
    request_path = config_dir / "fleet-rescan.request"
    fingerprint = None
    next_poll = 0.0

    def observe(reason: str):
        nonlocal fingerprint
        report = observer.report()
        raw = json.dumps(report).encode()
        if len(raw) > MAX_REPORT_BYTES:
            raise ValueError("report exceeds the size limit")
        atomic_write_bytes(config_dir / "fleet-latest.json", raw)
        latest["report"] = report
        current = semantic_fingerprint(report["manifest"]) + json.dumps(
            [report["names"], report["issues"]], sort_keys=True)
        changed = current != fingerprint
        fingerprint = current
        published = publisher.publish(report["manifest"], changed, log=log)
        if changed:
            log(f"Observed {len(report['manifest']['repositories'])} repos ({reason})"
                + (f"; published to {', '.join(published)}" if published else ""))
        return changed

    try:
        observe("initial inventory")
        if once:
            return 0
        while not stopping.is_set():
            try:
                changed = source.wait(timeout=1.0, debounce=config["debounce_seconds"])
                reason = None
                if request_path.exists():
                    request_path.unlink(missing_ok=True)
                    started = time.monotonic()
                    count = observer.inventory()
                    reason = f"manual inventory: {count} repos in {time.monotonic() - started:.1f}s"
                elif changed:
                    touched = observer.refresh(changed)
                    if touched:
                        reason = f"filesystem change: checked {touched} repo(s)"
                if reason:
                    observe(reason)
                now = time.monotonic()
                if now >= next_poll:
                    next_poll = now + PEER_POLL_SECONDS
                    network.poll()
            except (OSError, ValueError) as exc:
                log(f"Observation cycle failed; last state retained: {exc}")
    finally:
        source.close()
        network.stop()
        dashboard.shutdown()
        dashboard.server_close()
    return 0
