"""The tailnet web view's safeguards, always on: who may connect, which host name, which actions.

Runs a real listener on loopback with an injected identity check, so no Tailscale is needed and
nothing leaves this machine.
"""
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from App._web._assets import load_ui_assets  # noqa: E402
from App._web.remote import ACTIONS, make_remote_server, with_remote  # noqa: E402

HOST = "127.0.0.1"


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def request(port, path, *, method="GET", body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://{HOST}:{port}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, None


def serve(allowed: bool):
    calls = []

    def authenticate(_ip):
        if not allowed:
            raise PermissionError("not this user's device")
        return {"machine_id": "ts-phone"}

    def fleet_action(action, payload):
        calls.append(action)
        return {"message": "preview only", "action": action}

    server = make_remote_server((HOST, 0), lambda: {"contract": {"name": "x", "version": 1}},
                                load_ui_assets(), fleet_action, authenticate)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1], calls


def test_a_device_of_another_user_sees_nothing():
    server, port, _calls = serve(allowed=False)
    try:
        check(request(port, "/v1/dashboard")[0] == 403, "an unauthorized device must be refused")
        check(request(port, "/")[0] == 403, "even the page itself is refused")
    finally:
        server.shutdown(); server.server_close()


def test_actions_need_the_token_and_origin_and_exist_only_if_listed():
    server, port, calls = serve(allowed=True)
    try:
        status, document = request(port, "/v1/dashboard")
        check(status == 200 and document["local_actions"]["token"], "the document carries the per-run token")
        token = document["local_actions"]["token"]
        origin = f"http://{HOST}:{port}"
        check(request(port, "/v1/catchup-preview", method="POST", body={},
                      headers={"Origin": origin})[0] == 403, "no token, no action")
        check(request(port, "/v1/catchup-preview", method="POST", body={},
                      headers={"X-GitSpecOps-Token": token, "Origin": "http://elsewhere"})[0] == 403,
              "a foreign origin cannot act")
        check(request(port, "/v1/open-git-client", method="POST", body={},
                      headers={"X-GitSpecOps-Token": token, "Origin": origin})[0] == 405,
              "opening a desktop client stays local-only")
        status, result = request(port, "/v1/catchup-preview", method="POST", body={},
                                 headers={"X-GitSpecOps-Token": token, "Origin": origin})
        check(status == 200 and calls == ["catchup-preview"], (status, calls))
        check(not any(word in " ".join(ACTIONS) for word in ("force", "reset", "rebase", "merge", "delete")),
              "destructive verbs are not actions at all")
    finally:
        server.shutdown(); server.server_close()


def test_without_tailscale_the_view_stays_local_and_the_peer_runs_on():
    local = object()
    attach = with_remote(lambda *_: (local, "http://127.0.0.1:1/"), {"local_port": 8760},
                         identity=None, authenticate=None)
    import App._web.remote as remote

    original = remote.local_identity
    remote.local_identity = lambda: (_ for _ in ()).throw(ValueError("Tailscale must be connected"))
    try:
        server, url = attach(lambda: {}, None, None)
    finally:
        remote.local_identity = original
    check(server is local and url == "http://127.0.0.1:1/", "the loopback view is returned untouched")


def main():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"ALL-REMOTE-WEB-TESTS-PASS ({len(tests)} checks)")


if __name__ == "__main__":
    main()
