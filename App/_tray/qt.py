"""The Qt tray behind App/tray.py: icon, menu, notifications, and the peer's worker threads.

Why:          the command file stays a header and a `main`; the tray's machinery lives here.
Reads:        the running peer's display document, in memory.
May change:   nothing itself; see App/tray.py.
Results:      the tray icon and its menu.
Layer:        App: presence and presentation. Needs PySide6 (Qt).
Status:       working
"""
from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

#: What start-at-login registers: the tray command itself.
TRAY_SCRIPT = Path(__file__).resolve().parents[1] / "tray.py"

from App._mark.geometry import FRAME_MS, FRAMES  # noqa: E402
from App._mark.qt import icon as mark_icon  # noqa: E402
from App._tray.model import (GENERIC_FAILURE, POLL_SECONDS, setup_snapshot, Snapshot, error_snapshot,  # noqa: E402
                             failure_reason, snapshot_from_display, stopped_snapshot)

class TrayUnavailable(RuntimeError):
    """No Qt, or no system tray on this desktop."""


class ErrorChannel:
    """Forward console output unchanged. Of an `error:` line, keep only its fixed meaning: the
    raw text can carry paths or values, so it is never stored, logged or shown by the tray."""

    def __init__(self, original):
        self.original = original
        self.reason = None
        self._pending = ""

    def write(self, text):
        if self.original is not None:  # pythonw has no console streams
            self.original.write(text)
        self._pending += text
        *lines, self._pending = self._pending.split("\n")
        for line in lines:
            if line.startswith("error:"):
                self.reason = failure_reason(line)
        return len(text)

    def flush(self):
        if self.original is not None:
            self.original.flush()


def _logging(settings_home):
    """Counts-only operational events, as the common app settings choose (legacy: defaults)."""
    from Special._runtime.files import RuntimeIOError, excluded
    from Special._runtime.logger import configure_logging
    from Special._settings import resolve_document
    from Special._settings.fleet import fleet_home, load_fleet_settings

    home = fleet_home(settings_home)
    snapshot = load_fleet_settings(home)
    document = snapshot.document if snapshot is not None else {"schema_version": 2}
    settings = resolve_document(document, "app", home=home, configured=snapshot is not None,
                                home_source="common" if snapshot is not None else "legacy-runtime-default")
    values = settings.values
    if values["logging"]["enabled"] and excluded(values["logging"]["directory"],
                                                 values["scope"]["exclude_paths"]):
        raise RuntimeIOError("excluded_destination")
    return configure_logging(settings, "app_tray")


class Icons:
    """The mark for each pair of states and each working frame, painted once and reused."""

    def __init__(self):
        self._cache = {}

    def get(self, machine: str, fleet: str, frame: int | None = None):
        key = (machine, fleet, frame)
        if key not in self._cache:
            self._cache[key] = mark_icon(machine, fleet, frame)
        return self._cache[key]


def missing_qt_message() -> str:
    """Name the interpreter that has Qt, rather than calling it "not installed"."""
    project = TRAY_SCRIPT.parents[1]
    venv = project / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if venv.is_file() and venv.resolve() != Path(sys.executable).resolve():
        return (f"this Python ({sys.executable}) has no PySide6, but the project's own environment "
                f"does. Run:\n  {venv} {TRAY_SCRIPT}")
    return "PySide6 is not installed; install the app extra (uv sync --extra app)"


def run_tray(config_dir=None, settings_home=None, *, view=None, web=None, open_on_start=False,
             remote=False, poll_seconds=POLL_SECONDS) -> int:
    try:
        from PySide6 import QtCore, QtGui, QtWidgets
    except ImportError as exc:
        raise TrayUnavailable(missing_qt_message()) from exc
    from App._launch import profile_arguments, run_app
    from Basic._version import check_for_update, version_line
    from Elaborate._fleet import autostart
    from Elaborate._fleet.cli import main as fleet_main

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)
    if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
        raise TrayUnavailable("this desktop has no system tray")

    profile = profile_arguments(config_dir, settings_home)
    # What start-at-login registers: this tray, with the same choices it was started with.
    login_arguments = [*profile, *(["--view", view] if view else []), *(["--web", web] if web else []),
                       *(["--remote"] if remote else [])]

    class Bridge(QtCore.QObject):
        snapshot = QtCore.Signal(object)
        notify = QtCore.Signal(str, str)
        work = QtCore.Signal(int)

    bridge = Bridge()
    icons = Icons()
    tray = QtWidgets.QSystemTrayIcon(icons.get("starting", "none"))
    tray.setToolTip("gitSpecOps: starting")
    stopping, ready = threading.Event(), threading.Event()
    context: dict = {}
    result = {"code": 0}
    errors = ErrorChannel(sys.stderr)
    operational = _logging(settings_home)

    # Working: colour flows in from the outer dots to the hub, over and over, while the app works
    # out its state, reads or fetches, or runs something the person asked for from the menu.
    blink = {"frame": 0, "work": 0, "snapshot": Snapshot()}
    blink_timer = QtCore.QTimer()
    blink_timer.setInterval(FRAME_MS)

    def show_icon():
        snapshot = blink["snapshot"]
        working = snapshot.working or blink["work"] > 0
        if working and not blink_timer.isActive():
            blink["frame"] = 0
            blink_timer.start()
        elif not working and blink_timer.isActive():
            blink_timer.stop()
        tray.setIcon(icons.get(snapshot.machine, snapshot.fleet, blink["frame"] if working else None))

    def tick():
        blink["frame"] = (blink["frame"] + 1) % len(FRAMES)
        show_icon()

    blink_timer.timeout.connect(tick)

    def working(delta: int):
        blink["work"] = max(0, blink["work"] + delta)
        show_icon()

    def apply(snapshot: Snapshot):
        blink["snapshot"] = snapshot
        show_icon()
        tray.setToolTip(snapshot.tooltip())
        machine_line.setText(f"This machine: {snapshot.machine_text}")
        fleet_line.setText(f"Fleet: {snapshot.fleet_text}")
        activity_line.setText(f"Now: {snapshot.activity_text}")

    def open_view():
        """Double-click: open the face the person chose, web or window."""
        choice = {"face": view or "web", "web": web or "loopback", **(context.get("choice") or {})}
        if choice["face"] == "window":
            if context.get("url"):
                tray.showMessage("The Qt window comes later", "Opening the web view instead.")
                webbrowser.open(context["url"])
            else:
                tray.showMessage("The Qt window comes later",
                                 "Until then, turn the web view on: python Special/enroll_machine.py "
                                 "presentation --face web --web loopback")
        elif context.get("url"):
            webbrowser.open(context["url"])
        elif not context.get("ready"):
            tray.showMessage("Not running", "The peer is not running; hover the icon to see why.")

    def rescan():
        try:
            context["rescan"]()
            tray.showMessage("Rescan requested", "The peer will refresh which repositories exist.")
        except (KeyError, OSError) as exc:
            tray.showMessage("Rescan failed", type(exc).__name__)

    def preview():
        tray.showMessage("Catch-up preview", "Fetching remotes without changing branches or files.")
        working(+1)

        def work():
            try:
                message = context["catchup_preview"]()["message"]
                summary = next((line for line in message.splitlines() if line.startswith("Summary:")),
                               "Preview completed.")
                bridge.notify.emit("Catch-up preview", summary)
            except Exception:  # noqa: BLE001 - a menu action must never take the tray down
                bridge.notify.emit("Catch-up preview failed", "Run Special/catch_up.py to see why.")
            finally:
                bridge.work.emit(-1)
        threading.Thread(target=work, name="tray-catchup-preview", daemon=True).start()

    def toggle_autostart(checked):
        script = TRAY_SCRIPT
        try:
            if checked:
                result_ = autostart.enable(login_arguments, script=script)
                tray.showMessage("Start at login enabled", f"Registered via {result_['method']}.")
            else:
                autostart.disable()
                tray.showMessage("Start at login disabled", "gitSpecOps will not start at login.")
        except (OSError, ValueError):
            tray.showMessage("Could not change start at login", "Elaborate/start_at_login.py shows why.")

    menu = QtWidgets.QMenu()
    # The two signals in words, the detail behind the icon without opening a window.
    machine_line = menu.addAction("This machine: starting")
    machine_line.setEnabled(False)
    fleet_line = menu.addAction("Fleet: not known yet")
    fleet_line.setEnabled(False)
    activity_line = menu.addAction("Now: starting")
    activity_line.setEnabled(False)
    menu.addSeparator()
    menu.addAction("Open web view").triggered.connect(lambda: webbrowser.open(context["url"])
                                                      if context.get("url") else None)
    window_action = menu.addAction("Open window")
    window_action.setEnabled(False)
    window_action.setToolTip("The Qt window comes later; the web view is the full view today.")
    menu.addSeparator()
    menu.addAction("Rescan repositories").triggered.connect(rescan)
    menu.addAction("Preview catch-up (fresh fetch)").triggered.connect(preview)
    menu.addSeparator()
    login = menu.addAction("Start at login")
    login.setCheckable(True)
    try:
        login.setChecked(bool(autostart.status().get("enabled")))
    except (OSError, ValueError):
        login.setEnabled(False)
    login.toggled.connect(toggle_autostart)
    version_action = menu.addAction(version_line())
    version_action.setEnabled(False)
    menu.addSeparator()
    menu.addAction("Quit gitSpecOps").triggered.connect(app.quit)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: open_view() if reason ==
                           QtWidgets.QSystemTrayIcon.ActivationReason.DoubleClick else None)
    bridge.snapshot.connect(apply)
    bridge.work.connect(working)
    show_icon()  # blinks from the first moment: nothing is known yet
    bridge.notify.connect(lambda title, message: tray.showMessage(title, message))
    tray.show()

    def on_ready(info):
        operational.event("peer_ready")
        context.update(info, ready=True)
        ready.set()
        bridge.snapshot.emit(Snapshot(state="starting", url=info.get("url") or "", ready=True,
                                      text="gitSpecOps: reading the fleet..."))
        if open_on_start and info.get("url"):
            webbrowser.open(info["url"])

    def on_setup(url):
        context.update(url=url, ready=True)
        context["choice"] = {"face": "web", "web": "loopback"}
        bridge.snapshot.emit(setup_snapshot(url))
        bridge.notify.emit("Set up gitSpecOps", "Double-click the icon to choose your library folders.")

    def worker():
        try:
            context["choice"] = {}
            result["code"] = run_app(config_dir, settings_home, stopping=stopping, on_ready=on_ready,
                                     on_setup=on_setup, face=view, web=web, remote=remote,
                                     choice_out=context["choice"])
        except Exception as exc:  # noqa: BLE001 - the icon must survive to say why
            result["code"] = 1
            errors.reason = errors.reason or failure_reason(str(exc))
        finally:
            operational.event("peer_stopped", exit_code=max(0, int(result["code"])))
            if not stopping.is_set():
                # Stopped without being asked: keep a red icon up saying why until Quit.
                reason = errors.reason or GENERIC_FAILURE
                bridge.snapshot.emit(stopped_snapshot(reason))
                bridge.notify.emit("gitSpecOps is not running", reason)

    def poller():
        while not ready.wait(0.5):
            if stopping.is_set():
                return
        label = context.get("label") or "Fleet"
        status = check_for_update()  # once per run, not per poll
        if status["state"] == "outdated":
            bridge.notify.emit("Update available", status["message"])
        while not stopping.is_set():
            try:
                snapshot = snapshot_from_display(context["dashboard"](), context.get("url") or "", label)
            except Exception:  # noqa: BLE001 - a skin must survive any peer failure
                snapshot = error_snapshot(context.get("url") or "", label)
            bridge.snapshot.emit(snapshot)
            stopping.wait(poll_seconds)

    original = sys.stderr
    sys.stderr = errors
    operational.event("tray_starting")
    threads = [threading.Thread(target=worker, name="fleet-peer", daemon=True),
               threading.Thread(target=poller, name="tray-poll", daemon=True)]
    try:
        for thread in threads:
            thread.start()
        app.exec()
    finally:
        stopping.set()
        tray.hide()
        for thread in threads:
            thread.join(timeout=10)
        sys.stderr = original
        operational.close()
    return result["code"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tray", description=__doc__.split("\n", 1)[0])
    parser.add_argument("--config-dir", type=Path, help="local fleet state and legacy input directory")
    parser.add_argument("--settings-home", type=Path, help="common profile; defaults to the user-data home")
    parser.add_argument("--view", choices=("web", "window"),
                        help="what double-clicking the icon opens (default: the saved choice)")
    parser.add_argument("--web", choices=("off", "loopback", "tailnet"),
                        help="serve the web view for this run (default: the saved choice)")
    parser.add_argument("--open-on-start", action="store_true", help="open the view once the peer is ready")
    parser.add_argument("--remote", action="store_true",
                        help="also serve the web view on the tailnet (App/_web/remote.py)")
    args = parser.parse_args(argv)
    try:
        return run_tray(args.config_dir, args.settings_home, view=args.view, web=args.web,
                        open_on_start=args.open_on_start, remote=args.remote)
    except TrayUnavailable as exc:
        print(f"note: {exc}\nWithout a tray, App/serve_web.py serves the web view.", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"error: {failure_reason(str(exc))}", file=sys.stderr)
        return 2

