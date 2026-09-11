"""The browser dashboard, served locally from published manifests. No Tailscale required.

Bound to the loopback address only. It is not a fleet endpoint and never accepts a report: it
reads whichever transports this machine has configured and renders what every machine last
published, including machines that are currently offline. Nothing here classifies Git state --
the document comes from `fleet_display` through `local_view`.

Loopback-only is the whole security model, and it is why there is no authentication: the page
is reachable exactly by someone already on this machine as this user. It must never be bound to
0.0.0.0, and a request whose peer is not loopback is refused rather than served.
"""
from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fleet_display import CONTRACT_NAME
from local_view import display_from_transport
from ui_assets import load_ui_assets

LOOPBACK = "127.0.0.1"
DEFAULT_PORT = 8760


def make_local_server(address, build_document, assets):
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
                if self.client_address[0] != LOOPBACK:
                    self.send(403, {"error": "local dashboard is loopback-only"})
                    return
                if self.path in assets:
                    data, kind = assets[self.path]
                    self.send(200, data, kind)
                    return
                if self.path == "/v1/dashboard":
                    self.send(200, build_document())
                    return
                self.send(404, {"error": "unknown endpoint"})
            except (OSError, ValueError, KeyError) as exc:
                # A transport that cannot be read is reported in the page, not as a dead server.
                self.send(200, {"contract": {"name": CONTRACT_NAME, "version": 1},
                                "error": str(exc)})

        def do_POST(self):
            # This endpoint never accepts reports; peers publish through transports.
            self.send(405, {"error": "the local dashboard is read-only"})

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
