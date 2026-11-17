"""A made-up, messy fleet on the real page: for screenshots, demos and trying the page out.

Usage:
    python _build/demo_fleet.py              # http://127.0.0.1:8799/ ; Ctrl+C stops it
    python _build/demo_fleet.py --port 8800
    python _build/demo_fleet.py --json       # print the display document and exit

Four invented machines (Desktop, Laptop, a Home server with two libraries, an Old laptop that has
not reported for days) and invented organizations, with every kind of trouble: uncommitted work,
behind, ahead, diverged, stashes, a missing copy, a repository with no remote. The reports go
through the same manifest and display code a real fleet uses, so the page shows exactly what it
would. Nothing on this computer is read; every button that would change something says so.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from App._mark.svg import mark_response  # noqa: E402
from App._web._assets import load_ui_assets  # noqa: E402
from Elaborate._fleet.local_view import display_from_manifests  # noqa: E402
from Special._sync.manifest import (branch_id, build_manifest, fleet_id_for, repository_id,  # noqa: E402
                                    root_repository_id)

SECRET = "d3" * 32
FLEET = fleet_id_for(SECRET)
THIS = "desktop"

#: machine id -> (label, minutes since its last report, {library name: [org folders it holds]})
MACHINES = {
    "desktop": ("Desktop", 0, {"Github (D:\\)": ["acme-tools", "studio", "my-forks", "no-remote"]}),
    "laptop": ("Laptop", 1, {"Github (~)": ["acme-tools", "studio", "no-remote"]}),
    "home-server": ("Home server", 2, {"Github (srv)": ["acme-tools", "studio", "my-forks"],
                                       "Github (backup)": ["acme-tools", "my-forks"]}),
    "old-laptop": ("Old laptop", 3 * 24 * 60, {"Projects (~)": ["acme-tools", "studio"]}),
}

#: org -> (host, [repositories])
ORGS = {
    "acme-tools": ("github.com", ["cli-kit", "data-pipeline", "docs-site", "release-scripts"]),
    "studio": ("github.com", ["game-jam", "shader-lab", "website"]),
    "my-forks": ("gitlab.com", ["awesome-lists", "tiny-db"]),
    "no-remote": ("local", ["notes", "scratch"]),
}

#: (machine, library, repository) -> what that copy is like; anything unlisted matches its provider
TROUBLE = {
    ("desktop", "Github (D:\\)", "cli-kit"): {"unstaged": 3, "untracked": 1},
    ("desktop", "Github (D:\\)", "website"): {"ahead": 2},
    ("desktop", "Github (D:\\)", "notes"): {"unstaged": 1},
    ("laptop", "Github (~)", "data-pipeline"): {"behind": 4},
    ("laptop", "Github (~)", "game-jam"): {"ahead": 1, "behind": 2},
    ("laptop", "Github (~)", "cli-kit"): {"stashes": 1},
    ("home-server", "Github (srv)", "docs-site"): {"behind": 7},
    ("home-server", "Github (backup)", "data-pipeline"): {"behind": 12},
    ("home-server", "Github (backup)", "tiny-db"): {"unstaged": 16},
    ("old-laptop", "Projects (~)", "shader-lab"): {"behind": 3, "unstaged": 2},
}
#: copies a machine does not have, though it holds the organization
MISSING = {("laptop", "Github (~)", "release-scripts"), ("home-server", "Github (backup)", "release-scripts"),
           ("old-laptop", "Projects (~)", "website"), ("laptop", "Github (~)", "scratch")}


def commit(*parts: str) -> str:
    return hashlib.sha1("/".join(parts).encode()).hexdigest()


def record(machine: str, library: str, org: str, name: str, now: datetime) -> dict:
    host = ORGS[org][0]
    facts = {"ahead": 0, "behind": 0, "staged": 0, "unstaged": 0, "untracked": 0, "stashes": 0,
             **TROUBLE.get((machine, library, name), {})}
    upstream = commit(org, name, "main")
    head = upstream if not (facts["ahead"] or facts["behind"]) else commit(org, name, machine, library)
    remote = host != "local"
    repo_id = (repository_id(host, org, name, SECRET) if remote
               else root_repository_id(commit("root", name), SECRET))
    return {"repo_id": repo_id, "branch_id": branch_id("main", SECRET), "has_upstream": remote,
            "upstream_observed_at": (now - timedelta(minutes=20)).replace(microsecond=0).isoformat().replace("+00:00", "Z") if remote else None,
            **(facts if remote else {**facts, "ahead": None, "behind": None}),
            "operation": None, "identity": "remote" if remote else "root", "has_remote": remote,
            "unpushed": facts["ahead"] if remote else 3,
            "name": {"host": host, "owner": org, "name": name}, "branch": "main", "head": head,
            "upstream_head": upstream if remote else None,
            "place": {"library": library, "folder": org}}


def document() -> dict:
    now = datetime.now(timezone.utc)
    manifests = []
    for machine, (label, minutes, libraries) in MACHINES.items():
        records = [record(machine, library, org, name, now)
                   for library, orgs in libraries.items() for org in orgs for name in ORGS[org][1]
                   if (machine, library, name) not in MISSING]
        observed = (now - timedelta(minutes=minutes)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        manifests.append(build_manifest(FLEET, machine, label, records, observed, carries_names=True))
    settings = {"machine_id": THIS, "fleet_name": "Demo-Fleet", "fetch_seconds": 3600,
                "transport_config": {"tailnet": {"seconds": 300, "port": 8765}},
                "local_repo_ids": [r["repo_id"] for r in manifests[0]["repositories"]],
                "security_available": True}
    data = display_from_manifests(manifests, FLEET, settings=settings, now=now, stale_seconds=600)
    return {**data, "local_actions": {"token": "demo"}}


REFUSAL = {"error": "This is a demo fleet: nothing here changes anything."}
READS = {"security-status": {"audit": None}, "security-engines": {"engines": []},
         "security-policy": {"lists": {"never_publish": [], "safe_values": [], "public_handles": []},
                             "machine_only_counts": {"never_publish": 0, "safe_values": 0}}}


class Handler(BaseHTTPRequestHandler):
    assets = load_ui_assets()

    def send(self, code: int, body, kind="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/v1/dashboard":
            self.send(200, document())
        elif url.path == "/v1/mark.svg":
            self.send(*mark_response(parse_qs(url.query)))
        elif url.path in self.assets:
            body, kind = self.assets[url.path]
            self.send(200, body, kind)
        else:
            self.send(404, {"error": "not found"})

    def do_POST(self):
        action = urlparse(self.path).path.removeprefix("/v1/")
        self.send(200, READS[action]) if action in READS else self.send(400, REFUSAL)

    def log_message(self, *args):
        pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument("--json", action="store_true", help="print the display document and exit")
    args = parser.parse_args(argv)
    if args.json:
        print(json.dumps(document(), indent=2))
        return 0
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Demo fleet: http://127.0.0.1:{args.port}/  (Ctrl+C stops it)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
