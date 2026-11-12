"""Attach App's presentation to this machine's fleet peer: the web view, optionally the tailnet.

Why:          the tray, the web-only mode and the packaged desktop entry all start the same
              peer with the same presentation; one place builds it.
Reads:        the fleet configuration (read-only; loading never converts or saves).
May change:   nothing.
Results:      (configuration, serve) where serve is what Elaborate's run_peer accepts.
Layer:        App: presence and presentation.
Status:       working
"""
from __future__ import annotations

from pathlib import Path

from App._web.server import peer_server
from Elaborate._fleet.cli import load_saved
from Special._settings.fleet import fleet_directory, fleet_home


def profile_arguments(config_dir=None, settings_home=None) -> list[str]:
    """The profile selection every handoff keeps: tray, start-at-login and the peer itself."""
    arguments = []
    if config_dir is not None:
        arguments += ["--config-dir", str(Path(config_dir))]
    arguments += ["--settings-home", str(fleet_home(settings_home))]
    return arguments


def presentation(config_dir=None, settings_home=None, *, remote: bool = False,
                 face: str | None = None, web: str | None = None):
    """(config, serve, choice): saved choices, with this run's overrides on top.

    `serve` is None when the web view is off; the tray then shows only its own face."""
    from Special._sync.enrollment import DEFAULT_PRESENTATION

    directory = fleet_directory(config_dir, home=settings_home)
    config = load_saved(directory, home=settings_home)
    choice = {**DEFAULT_PRESENTATION, **(config.get("presentation") or {})}
    if face:
        choice["face"] = face
    if web or remote:
        choice["web"] = "tailnet" if remote else web
    serve = None
    if choice["web"] != "off":
        serve = peer_server(int(config["local_port"]))
        if choice["web"] == "tailnet":
            from App._web.remote import with_remote

            serve = with_remote(serve, config)
    return config, serve, choice
