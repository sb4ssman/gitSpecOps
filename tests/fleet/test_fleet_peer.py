"""The peer model: no host, no client, and no dependence on Tailscale.

These pin the properties whose absence was the original design mistake:

- a peer needs **no other machine** to observe, publish and show a dashboard;
- Tailscale being absent or down degrades the tailnet tier only;
- peers **pull**, so a peer endpoint has no write path at all;
- reading the same machine from several transports is normal and must not double-count it.

Offline and synthetic throughout: temporary folders stand in for transports, and the tailnet
tier is exercised without a tailnet by stubbing identity resolution.
"""
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup("sync")

import fleet_peer  # noqa: E402
from fleet_config import migrate, new_config, validate  # noqa: E402
from folder_transport import FolderTransport  # noqa: E402
from local_view import display_from_manifests  # noqa: E402
from manifest import build_manifest, fleet_id_for  # noqa: E402

SECRET = "55" * 32
FLEET = fleet_id_for(SECRET)


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def manifest_for(machine, observed, dirty=0):
    return build_manifest(FLEET, machine, machine, [{
        "repo_id": "a" * 32, "branch_id": "b" * 16, "has_upstream": True,
        "upstream_observed_at": None, "ahead": 0, "behind": 0,
        "staged": 0, "unstaged": dirty, "untracked": 0, "stashes": 0, "operation": None,
    }], observed_at=observed)


def test_a_peer_with_no_transports_is_valid():
    """The fleet features must not be a precondition for the single-machine tool."""
    with tempfile.TemporaryDirectory() as root:
        config = new_config("machine-a", "A", [root], SECRET, transports={})
        validate(config)
    check(config["mode"] == "peer", "there is only one kind of machine")


def test_same_machine_from_several_transports_counts_once():
    """More transports may only improve freshness; they must never double-count a machine."""
    now = datetime.now(timezone.utc)
    older = manifest_for("machine-a", (now - timedelta(hours=2)).isoformat(), dirty=3)
    newer = manifest_for("machine-a", now.isoformat(), dirty=0)
    document = display_from_manifests([older, newer], fleet_id=FLEET, now=now)
    check(document["summary"]["machines"] == 1,
          f"one machine seen twice is one machine: {document['summary']}")
    check(document["machines"][0]["freshness"] == "current",
          "the newest observation must win")
    text = " ".join(i for issue in document["issues"] for i in issue["items"])
    check("duplicate" not in text,
          f"reading one machine from several sources is normal, not an issue: {text}")


def test_tailnet_tier_degrades_without_tailscale():
    """Tailscale missing must cost the tailnet tier and nothing else."""
    messages = []
    config = {"fleet_secret": SECRET, "transports": {"tailnet": {"port": 8765,
                                                                 "allowed_login": None}}}
    original = fleet_peer.local_identity
    fleet_peer.local_identity = lambda: (_ for _ in ()).throw(ValueError("Tailscale not running"))
    try:
        network = fleet_peer.PeerNetwork(config, lambda: None, store=None, log=messages.append)
        check(network.enabled is True, "the tier is configured")
        check(network.start() is False, "it must not come up without Tailscale")
        check(network.poll() == 0, "polling without a server is a no-op, not a crash")
    finally:
        fleet_peer.local_identity = original
    joined = " ".join(messages)
    check("unaffected" in joined,
          f"the message must say what still works, not just what failed: {joined}")


def test_peer_without_the_tailnet_tier_never_touches_tailscale():
    config = {"fleet_secret": SECRET, "transports": {}}
    original = fleet_peer.local_identity

    def explode():
        raise AssertionError("a peer without the tailnet tier must not call Tailscale")

    fleet_peer.local_identity = explode
    try:
        network = fleet_peer.PeerNetwork(config, lambda: None, store=None)
        check(network.enabled is False, "no tailnet transport means the tier is off")
        check(network.start() is False, "starting it is a no-op")
    finally:
        fleet_peer.local_identity = original


def test_publisher_survives_a_broken_transport():
    """One unreachable transport may not stop the others, or stop observation."""
    class Broken:
        def write_own_manifest(self, *_args, **_kwargs):
            raise OSError("volume not mounted")

    class Working:
        def __init__(self):
            self.written = 0

        def write_own_manifest(self, *_args, **_kwargs):
            self.written += 1

    working, messages = Working(), []
    publisher = fleet_peer.TransportPublisher({}, clock=lambda: 0)
    publisher.entries = [
        {"name": "broken", "transport": Broken(), "seconds": 10, "next": 0.0},
        {"name": "working", "transport": working, "seconds": 10, "next": 0.0},
    ]
    published = publisher.publish(manifest_for("machine-a", "2026-01-01T00:00:00+00:00"),
                                  changed=True, log=messages.append)
    check(published == ["working"], f"the healthy transport must still publish: {published}")
    check(working.written == 1, "and must actually have been written to")
    check(any("broken" in m for m in messages), "the failure must be reported, not swallowed")


def test_transports_read_independently():
    """A peer reads every transport it has; one failing contributes an issue, not an outage."""
    now = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory() as temp:
        good = FolderTransport(temp)
        good.write_own_manifest("machine-b", manifest_for("machine-b", now.isoformat()))

        class Broken:
            def list_manifests(self):
                raise OSError("share unavailable")

        publisher = fleet_peer.TransportPublisher({}, clock=lambda: 0)
        publisher.entries = [
            {"name": "folder", "transport": good, "seconds": 10, "next": 0.0},
            {"name": "repo", "transport": Broken(), "seconds": 10, "next": 0.0},
        ]
        manifests, issues = publisher.read_all()
    check(len(manifests) == 1, f"the readable transport must still yield data: {manifests}")
    check(any("repo" in issue for issue in issues), f"the failure must surface: {issues}")


def test_v2_host_and_client_both_become_peers():
    with tempfile.TemporaryDirectory() as root:
        base = {"version": 2, "roots": [root], "fleet_secret": SECRET, "heartbeat": 30,
                "observation_mode": "filesystem-events", "debounce_seconds": 0.75,
                "inventory_notice_acknowledged": True, "replica_folder": None,
                "folder_seconds": 300, "replica_repo": None, "github_seconds": 1800}
        host = migrate({**base, "mode": "host", "machine_id": "ts-a", "label": "a",
                        "allowed_login": "owner", "port": 8765})
        client = migrate({**base, "mode": "connect", "machine_id": "ts-b", "label": "b",
                          "server": "http://100.64.0.1:8765"})
        validate(host)
        validate(client)
    check(host["mode"] == client["mode"] == "peer", "both old roles become the same thing")
    check("server" not in client and "allowed_login" not in client,
          "a peer pushes to nobody, so it remembers no server")


def test_cooldown_retains_latest_status_and_retries_without_new_events():
    clock = [0]
    transport = Mock()
    publisher = fleet_peer.TransportPublisher({}, clock=lambda: clock[0])
    publisher.entries = [{"name": "folder", "transport": transport,
                          "seconds": 10, "next": 0.0}]
    initial = manifest_for("machine-a", "2026-01-01T00:00:00+00:00")
    publisher.publish(initial, True)
    clock[0] = 2
    dirty = manifest_for("machine-a", "2026-01-01T00:00:02+00:00", dirty=1)
    publisher.publish(dirty, True)
    clock[0] = 4
    latest = manifest_for("machine-a", "2026-01-01T00:00:04+00:00", dirty=2)
    publisher.publish(latest, True)
    latest["observed_at"] = "must not affect the queued snapshot"
    clock[0] = 10
    transport.write_own_manifest.side_effect = OSError("offline")
    check(publisher.flush(log=lambda *_: None) == [], "failed write stays queued")
    clock[0] = 19
    publisher.flush()
    check(transport.write_own_manifest.call_count == 2, "no retry before its slot")
    clock[0] = 20
    transport.write_own_manifest.side_effect = None
    check(publisher.flush() == ["folder"], "retry needs no new filesystem event")
    written = transport.write_own_manifest.call_args.args[1]
    check(written["repositories"][0]["unstaged"] == 2, "latest queued status wins")
    check(written["observed_at"] == "2026-01-01T00:00:04+00:00",
          "delivery must not pretend observation was more recent")
    clock[0] = 100
    check(publisher.flush() == [], "successful delivery clears pending status")


def test_idle_runtime_drains_pending_status_without_scanning():
    """A publisher unit test alone cannot catch forgetting to drain it in the event loop."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        config = new_config("machine-a", "A", [root], SECRET)
        stopping = threading.Event()
        events = Mock()
        events.wait.side_effect = lambda **_: (stopping.set() or set())
        observer = Mock()
        observer.inventory.return_value = 1
        report = {"manifest": manifest_for("machine-a", "2026-01-01T00:00:00+00:00"),
                  "names": {}, "issues": []}
        observer.report.return_value = report
        observer.shared_report.return_value = (report, set())
        observer.excluded_from_observation = 0
        with patch("fleet_peer.IncrementalObserver", return_value=observer), \
                patch("fleet_peer.TransportPublisher") as Publisher, \
                patch("fleet_peer.PeerNetwork"), \
                patch("local_dashboard.make_local_server"), \
                patch("fleet_peer.threading.Thread"):
            Publisher.return_value.publish.return_value = []
            Publisher.return_value.flush.return_value = ["folder"]
            fleet_peer.run_peer(config, root, stopping, event_source=events, log=lambda *_: None)
            Publisher.return_value.flush.assert_called_once()
        observer.inventory.assert_called_once()
        observer.report.assert_called_once()
        observer.refresh.assert_not_called()
        events.close.assert_called_once()


def main():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    failures = []
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failures.append(f"{test.__name__}: {exc}")
    if failures:
        print("FLEET-PEER-TESTS FAILED:")
        for failure in failures:
            print("  -", failure)
        return 1
    print(f"ALL-FLEET-PEER-TESTS-PASS ({len(tests)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
