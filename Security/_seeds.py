"""The identity of the person running a scan, read at run time and held only in memory.

No pattern can know a real name in advance, so a real account once sat in a test fixture
unnoticed. These are the values most likely to leak, each read from where the machine already
keeps it -- nothing is asked for, stored or printed:

- offline: the git identity, the `gh` login (from gh's own config), this machine's host name and
  the home folder's name;
- local daemon: every machine name and address on the tailnet (`tailscale status`), when
  Tailscale is installed;
- online, only when asked: the GitHub organizations the `gh` login belongs to (an org's name is
  often the most identifying thing in a repository).

Values too short or too generic to scan for are dropped (see `_patterns.usable_identity`).
"""
from __future__ import annotations

import json
import socket
from pathlib import Path

from Basic._run import run

_TIMEOUT = 30


def _output(argv: list[str]) -> str:
    result = run(argv, timeout=_TIMEOUT)
    return result.stdout.strip() if result.returncode == 0 else ""


def _tailnet() -> tuple[list[str], list[str]]:
    """(machine names, addresses) for this machine and every peer, or empty lists."""
    text = _output(["tailscale", "status", "--json"])
    try:
        status = json.loads(text) if text else {}
    except ValueError:
        return [], []
    nodes = [status.get("Self") or {}, *(status.get("Peer") or {}).values()]
    names, addresses = set(), set()
    for node in nodes:
        for name in (node.get("HostName"), (node.get("DNSName") or "").split(".")[0]):
            if name:
                names.add(name)
        addresses.update(node.get("TailscaleIPs") or [])
    return sorted(names), sorted(addresses)


def _organizations() -> list[str]:
    text = _output(["gh", "api", "user/memberships/orgs", "--paginate",
                    "--jq", ".[].organization.login"])
    return sorted({line.strip() for line in text.splitlines() if line.strip()})


def identity_seeds(*, tailnet: bool = True, online: bool = False,
                   cwd: Path | None = None) -> dict[str, list[str]]:
    """`{kind: [values]}`. `cwd` reads that repository's own git identity (it may differ)."""
    git = ["git", *(["-C", str(cwd)] if cwd else [])]
    seeds = {
        "your git email": [_output([*git, "config", "user.email"])],
        "your git name": [_output([*git, "config", "user.name"])],
        "your gh login": [_output(["gh", "config", "get", "user", "-h", "github.com"])],
        "this machine's host name": [socket.gethostname()],
        "your home folder's name": [Path.home().name],
    }
    if tailnet:
        names, addresses = _tailnet()
        seeds["a tailnet machine name"] = names
        seeds["a tailnet address"] = addresses
    if online:
        seeds["a GitHub organization you belong to"] = _organizations()
    return {kind: [value for value in values if value] for kind, values in seeds.items()}
