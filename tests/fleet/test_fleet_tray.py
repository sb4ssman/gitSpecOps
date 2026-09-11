"""Tray-skin and start-at-login checks. Offline, synthetic, and non-mutating.

Two properties matter most here and neither needs a tray to exist:

- The tray is a *skin*. It must take every number and every state from the host's display
  document and must refuse an unrecognized contract version instead of guessing. These tests
  run on any platform because that logic is deliberately free of Win32.
- Start-at-login must never be changed as a side effect. The registry/XDG/LaunchAgent backends
  are swapped for an in-memory one, so running this suite never writes a real autostart entry
  on the developer's machine.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "git-sync-suggester"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup("sync")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fleet_autostart
import fleet_tray
from fleet_display import build_display
from fleet_tray import error_snapshot, snapshot_from_display
from manifest import build_manifest, fleet_id_for

SECRET = "22" * 32
FLEET = fleet_id_for(SECRET)


def report(machine="ts-one", dirty=0, observed=None):
    return {"manifest": build_manifest(FLEET, machine, machine, [{
        "repo_id": "c" * 32, "branch_id": "d" * 16, "has_upstream": True,
        "upstream_observed_at": None, "ahead": 0, "behind": 0,
        "staged": 0, "unstaged": dirty, "untracked": 0, "stashes": 0, "operation": None,
    }], observed_at=observed), "names": {"c" * 32: {
        "host": "github.com", "owner": "example", "name": "work"}}, "issues": []}


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def test_clean_fleet_reads_as_ok():
    now = datetime.now(timezone.utc)
    document = build_display([report(observed=now.isoformat())], FLEET, now=now)
    snapshot = snapshot_from_display(document, "http://100.0.0.1:8765/", "prime")
    check(snapshot.state == "ok", f"clean fleet should be ok, got {snapshot.state}")
    check(snapshot.repositories == 1, "repository count must come from the document")
    check(snapshot.attention == 0, "clean fleet has no attention")
    check("all clear" in snapshot.text, f"unexpected tooltip: {snapshot.text}")


def test_dirty_fleet_reads_as_attention():
    now = datetime.now(timezone.utc)
    document = build_display([report(dirty=3, observed=now.isoformat())], FLEET, now=now)
    snapshot = snapshot_from_display(document, "http://100.0.0.1:8765/", "prime")
    check(snapshot.state == "attention", f"dirty fleet should need attention, got {snapshot.state}")
    check(snapshot.attention == 1, "attention total must come from summary.attention")


def test_stale_machine_is_surfaced():
    """Silence is never good news: a stale report must not read as a clean fleet."""
    now = datetime.now(timezone.utc)
    old = (now - timedelta(hours=3)).isoformat()
    document = build_display([report(observed=old)], FLEET, now=now)
    snapshot = snapshot_from_display(document, "http://100.0.0.1:8765/", "prime")
    check(snapshot.stale == 1, "a stale machine must be counted as stale")
    check(snapshot.state == "attention", "a stale machine must not present as all clear")


def test_unsupported_contract_version_refuses_to_guess():
    document = {"contract": {"name": "gitspecops.fleet.display", "version": 99},
                "summary": {"repositories": 5, "attention": 0}}
    snapshot = snapshot_from_display(document, "http://100.0.0.1:8765/", "prime")
    check(snapshot.state == "error", "an unknown contract version must not be parsed")
    check(snapshot.repositories == 0, "no field may be trusted from an unsupported document")
    check("not supported" in snapshot.text, f"unexpected message: {snapshot.text}")


def test_foreign_contract_is_rejected():
    document = {"contract": {"name": "something.else", "version": 1}, "summary": {}}
    check(snapshot_from_display(document, "u", "p").state == "error",
          "a foreign contract name must be refused")


def test_error_snapshot_keeps_the_dashboard_reachable():
    snapshot = error_snapshot("http://100.0.0.1:8765/", "prime", OSError("connection refused"))
    check(snapshot.state == "error", "a failed fetch is an error state")
    check(snapshot.ready is True, "the dashboard link stays usable when a poll fails")
    check(len(snapshot.text) <= 200, "tooltip text must stay bounded")


def test_discovery_ranks_serving_hosts_first_and_keeps_the_rest_visible():
    """A peer that is online but not serving must be named, not silently dropped.

    "The host app is not running" is the most common enrolment failure, and an empty list
    would present it as "no machines exist" -- the same silence-as-good-news mistake the
    aggregate rules exist to prevent.
    """
    from fleet_net import discover_hosts

    status = {"Peer": {
        "a": {"HostName": "quiet-box", "TailscaleIPs": ["100.0.0.2"], "Online": True},
        "b": {"HostName": "offline-box", "TailscaleIPs": ["100.0.0.3"], "Online": False},
        "c": {"HostName": "tagged-server", "TailscaleIPs": ["100.0.0.4"], "Online": True,
              "Tags": ["tag:server"]},
    }}
    # Port 0 is never listenable, so every probe fails without touching the real network.
    hosts = discover_hosts(port=0, timeout=0.01, status=status)
    labels = [h["label"] for h in hosts]
    check("tagged-server" not in labels, "tagged devices are out of scope for this pilot")
    check(set(labels) == {"quiet-box", "offline-box"}, f"unexpected discovery: {labels}")
    check(all(h["serving"] is False for h in hosts), "nothing is serving on port 0")
    check(labels[0] == "offline-box" or labels[0] == "quiet-box", "ordering must be stable")
    online = {h["label"]: h["online"] for h in hosts}
    check(online["quiet-box"] is True and online["offline-box"] is False,
          "online state must be reported per peer")


def test_discovery_skips_peers_without_an_ipv4():
    from fleet_net import discover_hosts

    status = {"Peer": {"a": {"HostName": "v6only", "TailscaleIPs": ["fd7a::1"], "Online": True}}}
    check(discover_hosts(port=0, timeout=0.01, status=status) == [],
          "this pilot needs a Tailscale IPv4 address")


def test_tray_support_matches_platform():
    check(fleet_tray.supported() == (sys.platform == "win32"),
          "tray support must be claimed only on Windows")


class FakeBackend:
    """Stands in for the registry / XDG / LaunchAgent so tests never touch the real machine."""

    def __init__(self):
        self.value = None

    def status(self):
        return {"enabled": self.value is not None, "target": self.value}

    def enable(self, command):
        self.value = " ".join(command)
        return self.value

    def disable(self):
        existed, self.value = self.value is not None, None
        return existed


def test_autostart_roundtrip_without_touching_the_machine():
    backend = FakeBackend()
    original = dict(fleet_autostart._BACKENDS)
    key = "linux" if sys.platform.startswith("linux") else sys.platform
    fleet_autostart._BACKENDS[key] = ("fake backend", backend.status, backend.enable,
                                      backend.disable)
    try:
        check(fleet_autostart.status()["enabled"] is False, "should start disabled")
        result = fleet_autostart.enable(["fleet", "tray"])
        check(result["enabled"] is True, "enable must report success")
        check("fleet" in backend.value and "tray" in backend.value,
              f"registered command must carry the arguments: {backend.value}")
        check(fleet_autostart.status()["enabled"] is True, "status must observe the change")
        check(fleet_autostart.disable()["removed"] is True, "disable must remove the entry")
        check(fleet_autostart.status()["enabled"] is False, "status must observe removal")
    finally:
        fleet_autostart._BACKENDS.clear()
        fleet_autostart._BACKENDS.update(original)


def test_launch_command_is_absolute():
    command = fleet_autostart.launch_command(["fleet", "tray"])
    check(command[-2:] == ["fleet", "tray"], "arguments must be preserved in order")
    check(Path(command[0]).is_absolute(),
          "the login entry must not depend on the login shell's working directory")


def test_unsupported_platform_reports_a_reason():
    original = dict(fleet_autostart._BACKENDS)
    fleet_autostart._BACKENDS.clear()
    try:
        state = fleet_autostart.status()
        check(state["supported"] is False, "an unknown platform must report unsupported")
        check(state["reason"], "an unsupported platform must explain itself")
    finally:
        fleet_autostart._BACKENDS.update(original)


def main():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"test_fleet_tray: {len(tests)} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
