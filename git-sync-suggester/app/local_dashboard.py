"""The browser dashboard, served locally from published manifests. No Tailscale required.

Bound to the loopback address only. It is not a fleet endpoint and never accepts a report: it
reads whichever transports this machine has configured and renders what every machine last
published, including machines that are currently offline. Nothing here classifies Git state --
the document comes from `fleet_display` through `local_view`.

The optional desktop-client actions are local only: strict Host/Origin checks plus a per-run
request token prevent another website from launching applications. Loopback is not isolation
between OS users sharing this machine. Tailnet peer endpoints remain GET-only.
"""
from __future__ import annotations

import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fleet_display import CONTRACT_NAME
from local_view import display_from_transport
from ui_assets import load_ui_assets

LOOPBACK = "127.0.0.1"
DEFAULT_PORT = 8760


def make_local_server(address, build_document, assets, desktop_action=None):
    if address[0] != LOOPBACK:
        raise ValueError("the local dashboard must bind to loopback")
    action_token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(20)

        def log_message(self, *args):
            pass

        def send(self, status, value, kind="application/json"):
            data = json.dumps(value).encode() if kind == "application/json" else value
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; script-src 'self'; style-src 'self'; "
                             "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
                             "form-action 'none'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            try:
                if not self.local_request():
                    self.send(403, {"error": "invalid local dashboard address"})
                    return
                if self.path in assets:
                    data, kind = assets[self.path]
                    self.send(200, data, kind)
                    return
                if self.path == "/v1/dashboard":
                    document = build_document()
                    if desktop_action is not None:
                        document = {**document, "local_actions": {"token": action_token}}
                    self.send(200, document)
                    return
                self.send(404, {"error": "unknown endpoint"})
            except (OSError, ValueError, KeyError) as exc:
                # A transport that cannot be read is reported in the page, not as a dead server.
                self.send(200, {"contract": {"name": CONTRACT_NAME, "version": 1},
                                "error": str(exc)})

        def local_request(self):
            expected = f"{LOOPBACK}:{self.server.server_address[1]}"
            return self.client_address[0] == LOOPBACK and self.headers.get("Host") == expected

        def do_POST(self):
            if desktop_action is None or self.path not in ("/v1/git-client", "/v1/open-git-client"):
                self.send(405, {"error": "this endpoint accepts no actions"})
                return
            origin = f"http://{LOOPBACK}:{self.server.server_address[1]}"
            if not self.local_request() or self.headers.get("Origin") != origin \
                    or not secrets.compare_digest(self.headers.get("X-GitSpecOps-Token", "").encode(),
                                                  action_token.encode()):
                self.send(403, {"error": "open this action from the local dashboard"})
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
                self.send(200, desktop_action(self.path.removeprefix("/v1/"), payload))
            except (OSError, ValueError, KeyError):
                # Never echo paths from a launch error into the browser document.
                self.send(400, {"error": "Could not complete the desktop action. Check the client "
                                         "selection and that this checkout still exists locally."})

    server = ThreadingHTTPServer(address, Handler)
    server.daemon_threads = True
    return server


def serve(transport, config: dict, catalog: dict, port: int = DEFAULT_PORT,
          open_browser: bool = True, settings: dict | None = None) -> int:
    """Serve until interrupted. Returns 0 on a clean stop."""
    def build_document():
        # Re-read on every request: a peer's manifest may land in the synced folder at any
        # moment, and a dashboard that cached would quietly show yesterday's fleet.
        return display_from_transport(transport, config, catalog, settings=settings)

    server = make_local_server((LOOPBACK, port), build_document, load_ui_assets())
    url = f"http://{LOOPBACK}:{port}/"
    print(f"Local dashboard: {url}", flush=True)
    print("Reading published manifests only — no Tailscale connection is required, and "
          "machines that are offline still appear with their last known state.", flush=True)
    print("Ctrl-C stops it.", flush=True)
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
    finally:
        server.shutdown()
        server.server_close()
    return 0
