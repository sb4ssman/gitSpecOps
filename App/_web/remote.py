"""Serve this machine's web view on the tailnet, so a phone or tablet can watch and act.

Why:          a headless machine, or one across the house, should be watchable without a
              desktop session; and the same previews the local web view offers should work there.
Reads:        this machine's Tailscale identity; each caller's identity (`tailscale whois`).
May change:   nothing itself. Actions are the local web view's own (today: catch-up and
              security previews), run through the same peer handlers.
Results:      a second listener at http://<this machine's Tailscale IPv4>:<port>/.
Layer:        App: presence and presentation.
Status:       working

Safeguards, always on:
- Off unless asked for (`--remote` on App/tray.py or App/serve_web.py).
- Bound to this machine's Tailscale address only; never all interfaces, never the internet.
- Every request: the caller must be a device of this machine's own Tailscale user, untagged
  (the fleet's existing check, Elaborate/_fleet/net.py), and the Host header must be the
  numeric tailnet address (blocks DNS rebinding).
- Every action: the per-run token from the document, the exact Origin, JSON, at most 1 KiB.
- Only the actions listed in ACTIONS exist. Opening a desktop Git client stays local-only.
  Forced, reset, rebase, merge and delete are not verbs here at all.
"""
from __future__ import annotations

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from urllib.parse import parse_qs, urlsplit

from App._mark.svg import mark_response
from App._web._assets import load_ui_assets
from Elaborate._fleet.display import CONTRACT_NAME
from Elaborate._fleet.net import local_identity, peer_identity

DEFAULT_REMOTE_PORT = 8770
ACTIONS = ("catchup-preview", "security-preview")


class _Pair:
    """Stop both listeners as one, the way run_peer stops its dashboard."""

    def __init__(self, *servers):
        self.servers = [server for server in servers if server is not None]

    def shutdown(self):
        for server in self.servers:
            server.shutdown()

    def server_close(self):
        for server in self.servers:
            server.server_close()


def make_remote_server(address, build_document, assets, fleet_action, authenticate):
    host = address[0]
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(20)

        def log_message(self, *args):
            pass  # never log identities, tokens or request bodies

        def send(self, status, value, kind="application/json"):
            data = json.dumps(value).encode() if kind == "application/json" else value
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; script-src 'self'; style-src 'self'; "
                             "img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
                             "form-action 'none'")
            self.end_headers()
            self.wfile.write(data)

        def allowed(self) -> bool:
            if self.headers.get("Host") != f"{host}:{self.server.server_address[1]}":
                return False
            try:
                authenticate(self.client_address[0])
            except (PermissionError, ValueError, KeyError, OSError):
                return False
            return True

        def do_GET(self):
            if not self.allowed():
                self.send(403, {"error": "device not authorized"})
                return
            if self.path in assets:
                data, kind = assets[self.path]
                self.send(200, data, kind)
                return
            if urlsplit(self.path).path == "/v1/mark.svg":
                self.send(*mark_response(parse_qs(urlsplit(self.path).query)))
                return
            if self.path == "/v1/dashboard":
                try:
                    document = {**build_document(), "local_actions": {"token": token}}
                except (OSError, ValueError, KeyError):
                    document = {"contract": {"name": CONTRACT_NAME, "version": 1},
                                "error": "the fleet document is unavailable right now"}
                self.send(200, document)
                return
            self.send(404, {"error": "unknown endpoint"})

        def do_POST(self):
            action = self.path.removeprefix("/v1/")
            if action not in ACTIONS or fleet_action is None:
                self.send(405, {"error": "this action is not available remotely"})
                return
            if (not self.allowed() or self.headers.get("Origin") != f"http://{host}:{self.server.server_address[1]}"
                    or not secrets.compare_digest(self.headers.get("X-GitSpecOps-Token", "").encode(),
                                                  token.encode())):
                self.send(403, {"error": "open this action from the web view"})
                return
            if self.headers.get_content_type() != "application/json":
                self.send(415, {"error": "JSON required"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1024 or self.headers.get("Transfer-Encoding"):
                    raise ValueError("invalid action size")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("expected a JSON object")
                self.send(200, fleet_action(action, payload))
            except (OSError, ValueError, KeyError):
                self.send(400, {"error": "could not complete the action"})

    server = ThreadingHTTPServer(address, Handler)
    server.daemon_threads = True
    return server


def with_remote(serve, config: dict, *, identity=None, authenticate=None):
    """Wrap a loopback `serve` so the peer also gets the tailnet listener.

    If Tailscale is not connected the web view stays loopback-only and the reason is printed;
    the peer itself is never stopped by the optional remote tier."""
    port = int(config.get("remote_port") or DEFAULT_REMOTE_PORT)

    def attach(build_document, desktop_action, fleet_action):
        local, url = serve(build_document, desktop_action, fleet_action)
        try:
            me = identity or local_identity()
        except (OSError, ValueError) as exc:
            print(f"note: remote web view off: {exc}", flush=True)
            return local, url
        check = authenticate or (lambda ip: peer_identity(ip, me["login"]))
        remote = make_remote_server((me["ip"], port), build_document, load_ui_assets(),
                                    fleet_action, check)
        threading.Thread(target=remote.serve_forever, name="fleet-remote", daemon=True).start()
        print(f"Remote web view: http://{me['ip']}:{port}/ (your Tailscale devices only)", flush=True)
        return _Pair(local, remote), url
    return attach
