"""Synthetic pilot fleet checks: authorization, freshness, persistence, and replica budgets."""
import copy
import io
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Elaborate._fleet.cli import app_lock, guided_durable_arguments, require_gh
from Elaborate._fleet.config import validate
from Elaborate._fleet.peer import TransportPublisher
from App._web._assets import load_ui_assets
from Elaborate._fleet.display import CONTRACT_NAME, CONTRACT_VERSION, PRODUCT_NAME, build_display
from Elaborate._fleet.net import make_server, peer_identity, validate_server_url
from Elaborate._fleet.store import FleetStore, validate_report
from Special._sync.manifest import build_manifest, fleet_id_for

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
        assert view["capabilities"]["repository_actions"]["available"] is True
        assert view["integrations"][0]["id"] == "tailscale"
        features = {feature["id"]: feature for feature in view["features"]}
        assert features["recovery_snapshots"]["available"] is False
        with app_lock(Path(temp)):
            rejected(lambda: app_lock(Path(temp)).__enter__())

        auth = Mock(return_value={"machine_id": "ts-one", "label": "one"})
        assets = {"/": (b"html", "text/html"), "/assets/app.js": (b"js", "text/javascript")}
        with patch("Elaborate._fleet.net.ThreadingHTTPServer") as server:
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
    with patch("Elaborate._fleet.cli.run_gh", return_value=Mock(returncode=1)):
        rejected(require_gh)
    # Guided fleet setup (key, transports, names) on an enrolled machine: test_enrollment.py.

    # A suggested name is not permission to create or publish. No mutation occurs while
    # collecting setup arguments, even when the user explicitly selects creation.
    from contextlib import redirect_stdout
    for exists, answer, expected in [
        (False, "", []),
        (False, "yes", []),
        (False, "CREATE example/gitspecops-state",
         ["--repo", "example/gitspecops-state", "--create-repo"]),
        (True, "USE example/gitspecops-state",
         ["--repo", "example/gitspecops-state"]),
    ]:
        output = io.StringIO()
        with patch("builtins.input", side_effect=["y", "", answer]), \
                patch("Elaborate._fleet.cli.require_gh"), \
                patch("Elaborate._fleet.cli.run_gh", return_value=Mock(stdout="example\n")), \
                patch("Elaborate._fleet.cli.RepoTransport.doctor", return_value={
                    "exists": exists, "private": True, "permissions": True}), \
                patch("Elaborate._fleet.cli.create_state_repo") as create, redirect_stdout(output):
            assert guided_durable_arguments() == expected
            create.assert_not_called()
        assert "30 minutes" in output.getvalue()
        assert "status only" in output.getvalue()
        assert "machines/" in output.getvalue()
    for private, writable in [(False, True), (True, False)]:
        with patch("builtins.input", side_effect=["y", "example/existing"]), \
                patch("Elaborate._fleet.cli.require_gh"), \
                patch("Elaborate._fleet.cli.run_gh", return_value=Mock(stdout="example\n")), \
                patch("Elaborate._fleet.cli.RepoTransport.doctor", return_value={
                    "exists": True, "private": private, "permissions": writable}), \
                patch("Elaborate._fleet.cli.create_state_repo") as create, redirect_stdout(io.StringIO()):
            rejected(guided_durable_arguments)
            create.assert_not_called()

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
    # Unchanged state is still re-sent once per slot: that re-send is the heartbeat that tells
    # other machines this one is alive. The slower transport is not due yet and stays quiet.
    assert publisher.publish(manifest, changed=False, log=lambda *_: None) == ["folder"]
    clock[0] = 100
    github.write_own_manifest.side_effect = OSError("offline")
    assert "github" not in publisher.publish(manifest, changed=True, log=lambda *_: None)
    clock[0] = 105
    assert publisher.publish(manifest, changed=True, log=lambda *_: None) == []  # no early retry
    assert set(folder.write_own_manifest.call_args.args[1]) == set(manifest)

    assets = load_ui_assets()
    assert set(assets) == {"/", "/assets/fleet_standard.css", "/assets/fleet_client.js",
                           "/assets/fleet_view.js", "/assets/fleet_standard.js",
                           "/assets/fleet_map.js", "/assets/fleet_zoom.js", "/assets/fleet_security.js", "/setup", "/assets/fleet_setup.js"}
    assert all(isinstance(value[0], bytes) for value in assets.values())
    print("ALL-FLEET-APP-TESTS-PASS")


if __name__ == "__main__":
    main()
