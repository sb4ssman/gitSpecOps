"""Synthetic pilot fleet checks: authorization, freshness, persistence, and replica budgets."""
import copy
import io
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "git-sync-suggester"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup("sync")

from fleet_app import app_lock, require_gh, setup_arguments
from fleet_config import migrate, validate
from fleet_peer import TransportPublisher
from ui_assets import load_ui_assets
from fleet_display import CONTRACT_NAME, CONTRACT_VERSION, PRODUCT_NAME, build_display
from fleet_net import make_server, peer_identity, validate_server_url
from fleet_store import FleetStore, validate_report
from manifest import build_manifest, fleet_id_for

SECRET = "11" * 32
FLEET = fleet_id_for(SECRET)


def report(machine="ts-one", dirty=0, observed=None):
    return {"manifest": build_manifest(FLEET, machine, machine, [{
        "repo_id": "a" * 32, "branch_id": "b" * 16, "has_upstream": True,
        "upstream_observed_at": None, "ahead": 2, "behind": 0,
        "staged": 0, "unstaged": dirty, "untracked": 0, "stashes": 0, "operation": None,
    }], observed_at=observed), "names": {"a" * 32: {
        "host": "github.com", "owner": "example", "name": "work"}}, "issues": []}


def rejected(call, error=ValueError):
    try:
        call()
    except error:
        return
    raise AssertionError("operation should have been refused")


def main():
    with tempfile.TemporaryDirectory() as temp:
        store = FleetStore(Path(temp) / "fleet.sqlite3", FLEET)
        first = report(dirty=1)
        store.put("ts-one", first)
        heartbeat_at = datetime.now(timezone.utc).isoformat()
        store.touch("ts-one", heartbeat_at)
        assert store.reports()[0]["manifest"]["observed_at"] == heartbeat_at
        rejected(lambda: store.touch("missing", heartbeat_at))
        rejected(lambda: store.put("ts-two", first))
        rejected(lambda: validate_report(first, "ts-one", "another-fleet"))
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        rejected(lambda: store.put("ts-one", report(observed=old)))
        leak = copy.deepcopy(first)
        leak["names"]["a" * 32]["path"] = "/private/path"
        rejected(lambda: store.put("ts-one", leak))
        invalid = copy.deepcopy(first)
        invalid["manifest"]["repositories"][0]["ahead"] = "bad"
        rejected(lambda: store.put("ts-one", invalid))
        dup = copy.deepcopy(first)
        dup["manifest"]["repositories"] *= 2
        rejected(lambda: store.put("ts-one", dup))
        store.put("ts-two", report("ts-two", dirty=2, observed=old))
        view = build_display(FleetStore(Path(temp) / "fleet.sqlite3", FLEET).reports(), FLEET)
        assert view["contract"] == {"name": CONTRACT_NAME, "version": CONTRACT_VERSION}
        assert view["product"]["name"] == PRODUCT_NAME
        assert len(view["machines"]) == 2
        assert view["rows"][0]["cells"]["ts-two"]["freshness"] == "stale"
        assert "uncommitted" in view["rows"][0]["advice"]
        assert "ahead 2" in view["rows"][0]["cells"]["ts-one"]["description"]
        assert view["rows"][0]["needs_attention"] is True
        assert view["rows"][0]["cells"]["ts-one"]["tone"] == "danger"
        assert view["groups"] == [{"id": "github.com/example", "label": "example",
                                   "host": "github.com", "count": 1, "attention": 1}]
        assert view["capabilities"]["repository_actions"]["available"] is False
        assert view["integrations"][0]["id"] == "tailscale"
        assert view["features"][2]["id"] == "recovery_snapshots"
        with app_lock(Path(temp)):
            rejected(lambda: app_lock(Path(temp)).__enter__())

        auth = Mock(return_value={"machine_id": "ts-one", "label": "one"})
        assets = {"/": (b"html", "text/html"), "/assets/app.js": (b"js", "text/javascript")}
        with patch("fleet_net.ThreadingHTTPServer") as server:
            make_server(("100.64.0.1", 8765), store, SECRET, "owner", assets, auth)
            Handler = server.call_args.args[1]

        def request(path, body=None, headers=None):
            handler = object.__new__(Handler)
            raw = json.dumps(body).encode() if body is not None else b""
            handler.headers = {"Host": "100.64.0.1:8765", "X-GitSpecOps": "1",
                               "Content-Type": "application/json", "Content-Length": str(len(raw)),
                               **(headers or {})}
            handler.client_address = ("100.64.0.2", 1234)
            handler.path, handler.rfile = path, io.BytesIO(raw)
            handler.send = Mock()
            handler.dispatch(body is not None)
            return handler.send.call_args.args

        assert request("/v1/session")[0] == 200
        assert request("/")[0:2] == (200, b"html")
        assert request("/download")[0] == 404
        fresh = report(observed=datetime.now(timezone.utc).isoformat())
        assert request("/v1/report", fresh)[0] == 200
        assert request("/v1/heartbeat", {"observed_at": datetime.now(timezone.utc).isoformat()})[0] == 200
        assert request("/v1/heartbeat", {"bad": "shape"})[0] == 400
        assert request("/v1/report", report("ts-two"))[0] == 400
        assert request("/v1/report", first, {"Origin": "https://evil.example"})[0] == 403
        assert request("/v1/session", headers={"Host": "evil.example"})[0] == 403
        auth.side_effect = PermissionError()
        assert request("/v1/session")[0] == 403

    whois = Mock(return_value={"Node": {"StableID": "device1", "Name": "renamed.tailnet"},
                               "UserProfile": {"LoginName": "owner"}})
    assert peer_identity("100.64.0.2", "owner", whois)["machine_id"] == "ts-device1"
    rejected(lambda: peer_identity("100.64.0.2", "stranger", whois), PermissionError)
    whois.return_value["Node"]["Tags"] = ["tag:server"]
    rejected(lambda: peer_identity("100.64.0.2", "owner", whois), PermissionError)
    rejected(lambda: validate_server_url("http://127.0.0.1:8765"))
    rejected(lambda: validate_server_url("http://user:password@100.64.0.1:8765"))
    with patch("fleet_app.run_gh", return_value=Mock(returncode=1)):
        rejected(require_gh)
    # Setup asks for the library, the scan acknowledgement, then each optional transport.
    with patch("builtins.input", side_effect=["/libraries/code", "SCAN", "", "", "", ""]):
        setup = setup_arguments(Path("test-config"))
        assert setup.command == "peer" and setup.root == ["/libraries/code"]
        assert setup.acknowledge_initial_scan is True
        assert setup.repo is None and setup.folder is None
        assert setup.no_tailnet is False  # blank answer keeps the tailnet tier

    with tempfile.TemporaryDirectory() as root:
        # A v1 host configuration migrates all the way to a v3 peer, keeping its identity,
        # its fleet key and its transports. A saved setup is never silently discarded.
        migrated = migrate({
            "version": 1, "mode": "host", "roots": [root], "fleet_secret": SECRET,
            "machine_id": "ts-one", "label": "one", "interval": 30, "heartbeat": 30,
            "scan_notice_acknowledged": True, "replica_folder": root,
            "folder_seconds": 300, "replica_repo": None, "github_seconds": 1800,
            "allowed_login": "owner", "port": 8765,
        })
        assert migrated["version"] == 3 and migrated["mode"] == "peer"
        assert "interval" not in migrated and "port" not in migrated
        assert migrated["observation_mode"] == "filesystem-events"
        assert migrated["inventory_notice_acknowledged"] is True
        assert migrated["transports"]["folder"] == {"path": root, "seconds": 300}
        assert migrated["transports"]["tailnet"]["port"] == 8765
        assert migrated["fleet_secret"] == SECRET and migrated["machine_id"] == "ts-one"
        validate(migrated)

        # A former client migrates too, and loses the server it used to push to.
        client = migrate({
            "version": 2, "mode": "connect", "roots": [root], "fleet_secret": SECRET,
            "machine_id": "ts-two", "label": "two", "heartbeat": 30,
            "observation_mode": "filesystem-events", "debounce_seconds": 0.75,
            "inventory_notice_acknowledged": True, "replica_folder": None,
            "folder_seconds": 300, "replica_repo": None, "github_seconds": 1800,
            "server": "http://100.64.0.1:8765",
        })
        assert client["mode"] == "peer" and "server" not in client
        validate(client)

    # Publishing is paced per transport: a change reaches a synced folder quickly while the
    # GitHub API stays within budget, and one transport failing never stops the other.
    clock = [0]
    folder, github = Mock(), Mock()
    publisher = TransportPublisher({}, clock=lambda: clock[0])
    publisher.entries = [
        {"name": "folder", "transport": folder, "seconds": 10, "next": 0.0},
        {"name": "github", "transport": github, "seconds": 60, "next": 0.0},
    ]
    manifest = report()["manifest"]
    assert set(publisher.publish(manifest, changed=True, log=lambda *_: None)) == {"folder",
                                                                                   "github"}
    clock[0] = 5
    assert publisher.publish(manifest, changed=True, log=lambda *_: None) == []
    clock[0] = 12
    assert publisher.publish(manifest, changed=True, log=lambda *_: None) == ["folder"]
    clock[0] = 30
    # Nothing new to say: the slot is kept rather than spent republishing identical state.
    assert publisher.publish(manifest, changed=False, log=lambda *_: None) == []
    clock[0] = 100
    github.write_own_manifest.side_effect = OSError("offline")
    assert "github" not in publisher.publish(manifest, changed=True, log=lambda *_: None)
    clock[0] = 105
    assert publisher.publish(manifest, changed=True, log=lambda *_: None) == []  # no early retry
    assert set(folder.write_own_manifest.call_args.args[1]) == set(manifest)

    assets = load_ui_assets()
    assert set(assets) == {"/", "/assets/fleet_standard.css", "/assets/fleet_client.js",
                           "/assets/fleet_view.js", "/assets/fleet_standard.js"}
    assert all(isinstance(value[0], bytes) for value in assets.values())
    print("ALL-FLEET-APP-TESTS-PASS")


if __name__ == "__main__":
    main()
