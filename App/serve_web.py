"""Run this machine's fleet peer with its web view and no tray; or only show published status.

Why:          some setups want the web view always on: a headless machine watched from a phone
              over the tailnet, or a desktop that prefers a browser to a tray.
Reads:        the fleet configuration. With --manifests-only: the status transport's published
              manifests and the local catalog, without running a peer.
May change:   nothing in your repositories; the peer writes its own state and manifests.
Results:      the web view at the printed address; log lines on stdout.
Layer:        App: presence and presentation. Standard library only (no Qt).
Status:       working

    python App/serve_web.py [--config-dir D] [--settings-home H] [--remote]
    python App/serve_web.py --manifests-only [--port N] [--no-browser]
"""
from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

EFFECT = "none"


def manifests_only(args) -> int:
    from App._web.server import DEFAULT_PORT, serve
    from Elaborate._fleet.sync_cli import open_transport
    from Special._settings.fleet import fleet_directory
    from Special._sync.config import load_catalog, load_config

    config_dir = fleet_directory(args.config_dir, home=args.settings_home)
    config = load_config(config_dir, home=args.settings_home)
    transport, label = open_transport(config, None)
    if transport is None:
        raise ValueError("no published status to show; set a transport with "
                         "Elaborate/publish_status.py init")
    return serve(transport, config, load_catalog(config_dir), port=args.port or DEFAULT_PORT,
                 open_browser=not args.no_browser,
                 settings={"transport": label, "root_count": len(config.get("roots") or [])})


def with_peer(args) -> int:
    import signal

    from App._launch import presentation, profile_arguments
    from Elaborate._fleet.cli import main as fleet_main

    _config, serve, _choice = presentation(args.config_dir, args.settings_home, remote=args.remote,
                                           web="loopback")
    stopping = threading.Event()
    for name in ("SIGINT", "SIGTERM"):
        signal.signal(getattr(signal, name), lambda *_: stopping.set())
    return fleet_main([*profile_arguments(args.config_dir, args.settings_home), "run"],
                      stopping=stopping, serve=serve)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="serve_web", description=__doc__.split("\n", 1)[0])
    parser.add_argument("--config-dir", type=Path, help="local fleet state and legacy input directory")
    parser.add_argument("--settings-home", type=Path, help="common profile; defaults to the user-data home")
    parser.add_argument("--remote", action="store_true",
                        help="also serve on the tailnet for your own devices (App/_web/remote.py)")
    parser.add_argument("--manifests-only", action="store_true",
                        help="show published status without running a peer")
    parser.add_argument("--port", type=int, help="with --manifests-only: local port")
    parser.add_argument("--no-browser", action="store_true", help="with --manifests-only: do not open a browser")
    args = parser.parse_args(argv)
    try:
        return manifests_only(args) if args.manifests_only else with_peer(args)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
