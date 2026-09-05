"""Private-tailnet pilot protocol. No public listener, proxy identity headers or shell jobs.

Tailscale authenticates each TCP peer. The host allows its configured Tailscale user only,
and derives the report writer from the peer's stable node id, never from a supplied label.
This is a trusted personal fleet, not multi-user enterprise authorization.
"""
from __future__ import annotations

import ipaddress
import json
import shutil
import socket
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from fleet_store import MAX_REPORT_BYTES
from fleet_display import build_display


def tailscale_json(*args):
    executable = shutil.which("tailscale")
    if not executable:
        candidate = Path("C:/Program Files/Tailscale/tailscale.exe")
        executable = str(candidate) if candidate.is_file() else "tailscale"
    try:
        proc = subprocess.run([executable, *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Tailscale CLI unavailable; start Tailscale and retry") from exc
    if proc.returncode:
        raise ValueError("Tailscale is unavailable or not connected")
    return json.loads(proc.stdout)


def local_identity(status=None):
    status = tailscale_json("status", "--json") if status is None else status
    if status.get("BackendState") != "Running":
        raise ValueError("Tailscale must be connected")
    node = status["Self"]
    if node.get("Tags"):
        raise ValueError("tagged devices need an explicit future enrollment policy")
    login = status.get("User", {}).get(str(node["UserID"]), {}).get("LoginName")
    if not login:
        raise ValueError("cannot resolve the current Tailscale user")
    ip = next((v for v in node["TailscaleIPs"] if ":" not in v), None)
    if not ip:
        raise ValueError("this pilot needs a Tailscale IPv4 address")
    return {"machine_id": "ts-" + node["ID"], "label": node["HostName"],
            "login": login, "ip": ip}


def peer_identity(ip: str, allowed_login: str, whois=tailscale_json):
    value = whois("whois", "--json", ip)
    node = value.get("Node") or {}
    user = value.get("UserProfile") or {}
    if user.get("LoginName") != allowed_login or node.get("Tags"):
        raise PermissionError("device is not owned by the allowed Tailscale user")
    stable = node.get("StableID")
    if not isinstance(stable, str) or not stable.isalnum():
        raise PermissionError("unrecognized Tailscale device identity")
    return {"machine_id": "ts-" + stable,
            "label": str(node.get("Name") or stable).split(".")[0]}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("fleet endpoints must not redirect")


def validate_server_url(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("server must be http://TAILSCALE-IP:PORT")
    # Resolve once, then pin the numeric destination. Never send reports through an HTTP proxy.
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 80, socket.AF_INET,
                                   socket.SOCK_STREAM)
    ip = addresses[0][4][0]
    if ipaddress.ip_address(ip) not in ipaddress.ip_network("100.64.0.0/10"):
        raise ValueError("server must resolve to a Tailscale IPv4 address")
    return f"http://{ip}:{parsed.port or 80}"


class FleetClient:
    def __init__(self, url: str):
        self.url = validate_server_url(url)
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, path: str, value=None):
        raw = json.dumps(value).encode() if value is not None else None
        request = Request(self.url + path, data=raw,
                          headers={"Content-Type": "application/json",
                                   "X-GitSpecOps": "1"})
        try:
            with self.opener.open(request, timeout=20) as response:
                data = response.read(MAX_REPORT_BYTES + 1)
                if len(data) > MAX_REPORT_BYTES:
                    raise ValueError("fleet response is too large")
                return json.loads(data)
        except HTTPError as exc:
            raise ValueError(f"fleet request refused ({exc.code})") from None


def make_server(address, store, secret: str, allowed_login: str, assets: dict,
                authenticate=None, display_settings=None):
    authenticate = authenticate or (lambda ip: peer_identity(ip, allowed_login))

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(20)

        def log_message(self, *args):
            pass  # never log authentication material or request bodies

        def send(self, status, value, kind="application/json"):
            data = json.dumps(value).encode() if kind == "application/json" else value
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; "
                             "style-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
                             "base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(data)

        def dispatch(self, write=False):
            try:
                # Host check also blocks browser DNS rebinding. No CORS or forwarded identities.
                if self.headers.get("Host") != f"{address[0]}:{address[1]}":
                    self.send(403, {"error": "use the numeric Tailscale dashboard URL"})
                    return
                peer = authenticate(self.client_address[0])
                if write:
                    if (self.headers.get("X-GitSpecOps") != "1"
                            or self.headers.get("Content-Type") != "application/json"
                            or self.headers.get("Origin") is not None
                            or self.headers.get("Transfer-Encoding") is not None):
                        raise PermissionError("only fleet clients may publish")
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= MAX_REPORT_BYTES:
                        self.send(413, {"error": "invalid report size"})
                        return
                    raw = self.rfile.read(size)
                    if len(raw) != size:
                        raise ValueError("incomplete request")
                    if self.path == "/v1/report":
                        store.put(peer["machine_id"], json.loads(raw))
                        self.send(200, {"stored": True})
                        return
                    if self.path == "/v1/heartbeat":
                        value = json.loads(raw)
                        if not isinstance(value, dict) or set(value) != {"observed_at"}:
                            raise ValueError("invalid heartbeat")
                        store.touch(peer["machine_id"], value["observed_at"])
                        self.send(200, {"stored": True})
                        return
                elif self.path in assets:
                    data, kind = assets[self.path]
                    self.send(200, data, kind)
                    return
                elif self.path == "/v1/session":
                    # A local fleet key, never a GitHub token. Only authenticated allowed peers.
                    self.send(200, {**peer, "fleet_secret": secret, "fleet_id": store.fleet_id})
                    return
                elif self.path == "/v1/dashboard":
                    self.send(200, build_display(store.reports(), store.fleet_id,
                                                 settings=display_settings))
                    return
                self.send(404, {"error": "unknown endpoint"})
            except PermissionError:
                self.send(403, {"error": "device not authorized"})
            except (ValueError, KeyError, TypeError):
                self.send(400, {"error": "invalid report or unavailable Tailscale identity"})
            except (OSError, TimeoutError):
                self.close_connection = True

        def do_GET(self):
            self.dispatch()

        def do_POST(self):
            self.dispatch(True)

    server = ThreadingHTTPServer(address, Handler)
    server.daemon_threads = True
    return server
