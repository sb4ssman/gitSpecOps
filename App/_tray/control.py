"""Talk to a running tray from a terminal: what it is doing, its recent events, open its map, quit.

Why:          the tray belongs to no window (App/_detach.py), so there is no terminal showing its
              output. `gitso tray` while it runs says what it is doing now and what it did last;
              --follow keeps watching; --open opens the web view at the map; --stop quits it
              (the user, 2026-11-16).
Reads:        the tray's operational log (event names and counts only) and its local web view's
              status (GET /v1/dashboard on 127.0.0.1).
May change:   --stop leaves a quit request in the fleet folder; the tray sees it within a second.
Layer:        App: presence. No Qt here: it works over SSH and without a desktop.
"""
from __future__ import annotations

import json
import time
import urllib.request
import webbrowser
from pathlib import Path

QUIT_REQUEST = "tray-quit.request"
EVENTS = {"tray_starting": "started", "peer_ready": "ready: reading and watching your library",
          "peer_stopped": "the watcher stopped"}


def _settings(settings_home):
    from Special._settings import resolve_document
    from Special._settings.fleet import fleet_home, load_fleet_settings
    home = fleet_home(settings_home)
    snapshot = load_fleet_settings(home)
    document = snapshot.document if snapshot is not None else {"schema_version": 2}
    values = resolve_document(document, "app", home=home, configured=snapshot is not None,
                              home_source="common" if snapshot is not None else "runtime-default").values
    app = snapshot.config("app") if snapshot is not None else None
    return values, app or {}


def log_path(settings_home=None) -> Path:
    values, _app = _settings(settings_home)
    return Path(values["logging"]["directory"]) / "app_tray.log"


def web_address(settings_home=None) -> str | None:
    """The local web view's address, or None when the web view is off."""
    _values, app = _settings(settings_home)
    if (app.get("presentation") or {}).get("web") == "off":
        return None
    return f"http://127.0.0.1:{int(app.get('local_port') or 8760)}/"


def event_line(record: dict) -> str:
    """One log record in words, with its local time."""
    stamp = record.get("timestamp", "")
    try:
        from datetime import datetime
        stamp = datetime.fromisoformat(stamp).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass
    text = EVENTS.get(record.get("event"), str(record.get("event", "")).replace("_", " "))
    if record.get("event") == "peer_stopped":
        code = record.get("exit_code", 0)
        text += " normally" if code == 0 else f" with an error (exit code {code}; gitso tray --foreground shows why)"
    return f"{stamp}  {text}"


def recent_events(settings_home=None, count: int = 8) -> list[str]:
    path = log_path(settings_home)
    if not path.exists():
        return []
    lines = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines()[-count:]:
        try:
            lines.append(event_line(json.loads(raw)))
        except (ValueError, AttributeError):
            continue
    return lines


def status_now(settings_home=None) -> list[str]:
    """What the running tray says about itself right now, from its web view; [] when unreadable."""
    address = web_address(settings_home)
    if address is None:
        return ["Its web view is off, so its status can only be seen on its icon."]
    try:
        with urllib.request.urlopen(address + "v1/dashboard", timeout=5) as response:
            data = json.loads(response.read())
    except (OSError, ValueError):
        return ["Its web view is not answering right now."]
    mark, activity, summary = data.get("mark") or {}, data.get("activity") or {}, data.get("summary") or {}
    lines = [f"Now: {activity.get('text') or 'watching for changes'}",
             f"This machine: {(mark.get('machine') or {}).get('text', 'unknown')}",
             f"Fleet: {(mark.get('fleet') or {}).get('text', 'unknown')}"]
    if summary:
        lines.append(f"Repositories: {summary.get('repositories', 0)}, needing attention: "
                     f"{summary.get('attention', 0)}; machines reporting: {summary.get('machines', 0)}")
    return lines


def follow(settings_home=None, interval: float = 2.0, *, out=print, stop=None) -> int:
    """Print what changes, until Ctrl+C or the tray stops."""
    from App._detach import running
    seen_status, seen_events = None, set(recent_events(settings_home, 50))
    try:
        while stop is None or not stop():
            if not running(settings_home=settings_home):
                out("The app is not running any more.")
                return 0
            status = status_now(settings_home)
            if status != seen_status:
                for text in status:
                    out(f"{time.strftime('%H:%M:%S')}  {text}")
                seen_status = status
            for text in recent_events(settings_home, 50):
                if text not in seen_events:
                    seen_events.add(text)
                    out(text)
            time.sleep(interval)
    except KeyboardInterrupt:
        out("Stopped following; the app keeps running.")
    return 0


def open_map(settings_home=None) -> str:
    address = web_address(settings_home)
    if address is None:
        raise RuntimeError("the web view is off; turn it on in setup (The desktop app) or with --web loopback")
    webbrowser.open(address + "#map")
    return address + "#map"


def request_stop(config_dir=None, settings_home=None, wait: float = 15.0) -> bool:
    """Ask the running tray to quit; True once it has."""
    from App._detach import running
    from Basic._files import atomic_write_bytes
    from Special._settings.fleet import fleet_directory
    atomic_write_bytes(fleet_directory(config_dir, home=settings_home) / QUIT_REQUEST, b"quit\n")
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if not running(config_dir, settings_home):
            return True
        time.sleep(0.25)
    return not running(config_dir, settings_home)
