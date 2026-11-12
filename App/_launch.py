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
                 face: str | None = None, web: str | None = None, on_change=None):
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
        from App._web.setup import SetupRoutes

        serve = peer_server(int(config["local_port"]),
                            setup=SetupRoutes(settings_home, config_dir, on_change=on_change))
        if choice["web"] == "tailnet":
            from App._web.remote import with_remote

            serve = with_remote(serve, config)
    return config, serve, choice


def serve_setup(config_dir=None, settings_home=None, *, stopping, on_setup=None, port=None) -> bool:
    """An un-enrolled machine: serve only the setup page until it is enrolled (True) or the app
    is told to stop (False)."""
    import threading

    from App._web.server import DEFAULT_PORT, setup_server
    from App._web.setup import SetupRoutes

    enrolled = threading.Event()
    routes = SetupRoutes(settings_home, config_dir,
                         on_change=lambda state: enrolled.set() if state.get("machine") else None)
    server, url = setup_server(routes, DEFAULT_PORT if port is None else port)
    try:
        if on_setup is not None:
            on_setup(url)
        while not (enrolled.is_set() or stopping.is_set()):
            stopping.wait(0.5)
    finally:
        server.shutdown()
        server.server_close()
    return enrolled.is_set()


def is_not_enrolled(exc) -> bool:
    return "not enrolled" in str(exc)


def run_app(config_dir=None, settings_home=None, *, stopping, on_ready=None, on_setup=None,
            face=None, web=None, remote=False, choice_out=None) -> int:
    """The app's life: setup until this machine is enrolled, then the peer with its web view.

    A setup change made from the web view (a library, the fleet, the presentation) restarts the
    peer so it takes effect; quitting stops everything."""
    import threading

    from Elaborate._fleet.cli import main as fleet_main

    profile = profile_arguments(config_dir, settings_home)
    while not stopping.is_set():
        changed, run_stop = threading.Event(), threading.Event()
        try:
            _config, serve, choice = presentation(config_dir, settings_home, remote=remote, face=face,
                                                  web=web, on_change=lambda state: changed.set())
        except ValueError as exc:
            if not is_not_enrolled(exc):
                raise
            if not serve_setup(config_dir, settings_home, stopping=stopping, on_setup=on_setup):
                return 0
            continue
        if choice_out is not None:
            choice_out.update(choice)

        def relay():
            while not (stopping.is_set() or changed.is_set()):
                stopping.wait(0.5)
            run_stop.set()
        threading.Thread(target=relay, name="app-relay", daemon=True).start()
        code = fleet_main([*profile, "run"], stopping=run_stop, on_ready=on_ready, serve=serve)
        if stopping.is_set() or not changed.is_set():
            return code
    return 0

