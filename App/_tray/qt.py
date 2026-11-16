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
import os
import sys
import threading
import webbrowser
from pathlib import Path

#: What start-at-sign-in registers: the tray command itself.
TRAY_SCRIPT = Path(__file__).resolve().parents[1] / "tray.py"

from App._mark.geometry import FRAME_MS, FRAMES  # noqa: E402
from App._mark.qt import icon as mark_icon  # noqa: E402
from App._tray.model import (GENERIC_FAILURE, POLL_SECONDS, setup_snapshot, Snapshot, error_snapshot,  # noqa: E402
                             failure_code, failure_reason, snapshot_from_display, stopped_snapshot)

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
    """Counts-only operational events, as the app settings choose (defaults before enrollment)."""
    from Special._runtime.files import RuntimeIOError, excluded
    from Special._runtime.logger import configure_logging
    from Special._settings import resolve_document
    from Special._settings.fleet import fleet_home, load_fleet_settings

    home = fleet_home(settings_home)
    snapshot = load_fleet_settings(home)
    document = snapshot.document if snapshot is not None else {"schema_version": 2}
    settings = resolve_document(document, "app", home=home, configured=snapshot is not None,
                                home_source="common" if snapshot is not None else "runtime-default")
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
        from PySide6 import QtCore, QtWidgets
    except ImportError as exc:
        raise TrayUnavailable(missing_qt_message()) from exc
    from App._launch import profile_arguments, run_app
    from Basic._version import check_for_update, version_line
    from Elaborate._fleet import autostart

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)
    if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
        raise TrayUnavailable("this desktop has no system tray")
    # One tray per profile, held for this tray's whole life: a second copy (2026-11-15) doubled
    # the work and the windows. A second start says where the first one is, then leaves.
    from Special._settings.fleet import fleet_directory
    from Special._sync.lock import TRAY_LOCK, app_lock
    tray_lock = app_lock(fleet_directory(config_dir, home=settings_home), TRAY_LOCK)
    try:
        tray_lock.__enter__()
    except ValueError:
        QtWidgets.QMessageBox.information(
            None, "gitSpecOps", "gitSpecOps is already running for this profile. Its icon is by the "
            "clock (Windows may tuck it under the ^ arrow).")
        return 0

    profile = profile_arguments(config_dir, settings_home)
    # What start-at-sign-in registers: this tray, with the same choices it was started with.
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
                                 "Until then, turn the web view on: gitso machine "
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
                bridge.notify.emit("Catch-up preview failed", "Run Special/machine_catch_up.py to see why.")
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
            tray.showMessage("Could not change start at login", "Elaborate/start_at_sign_in.py shows why.")

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

    def show_login_state():
        # Read each time the menu opens: the person may have switched it in Task Manager,
        # Startup Applications or Login Items since. Showing it must not change it.
        try:
            state = autostart.status()
        except (OSError, ValueError):
            login.setEnabled(False)
            return
        login.blockSignals(True)
        login.setChecked(bool(state.get("enabled")))
        login.blockSignals(False)
        login.setText(f"Start at login (turned off in {state['elsewhere']})"
                      if state.get("turned_off_elsewhere") else "Start at login")

    show_login_state()
    menu.aboutToShow.connect(show_login_state)
    login.toggled.connect(toggle_autostart)
    version_action = menu.addAction(version_line())
    version_action.setEnabled(False)
    menu.addSeparator()
    menu.addAction("Quit gitSpecOps").triggered.connect(app.quit)
    tray.setContextMenu(menu)
    # `gitso tray --stop` leaves a quit request; it means the same as Quit on this menu. One left
    # over from before this start is not a request to this tray.
    from App._tray.control import QUIT_REQUEST
    quit_request = fleet_directory(config_dir, home=settings_home) / QUIT_REQUEST
    quit_request.unlink(missing_ok=True)
    quit_timer = QtCore.QTimer()
    quit_timer.setInterval(1000)

    def check_quit():
        if quit_request.exists():
            quit_request.unlink(missing_ok=True)
            app.quit()
    quit_timer.timeout.connect(check_quit)
    quit_timer.start()
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
            operational.event("peer_stopped", exit_code=max(0, int(result["code"])),
                              reason=failure_code(errors.reason))
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
    _record_process(config_dir, settings_home)
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
        tray_lock.__exit__(None, None, None)
    return result["code"]


def _leave_console() -> None:
    """A tray started on its own (App/_detach.py) belongs to no window. Should it have been given
    a console anyway, it lets go of it, so no window is ever tied to it: a console that only this
    process used closes with it (node1, 2026-11-16: a window stayed attached to the tray). Output
    then goes nowhere, as under pythonw; the log and `gitso tray --follow` show what it does."""
    if os.name == "nt":
        import ctypes
        kernel = ctypes.windll.kernel32
        if kernel.GetConsoleWindow():
            kernel.FreeConsole()
    devnull = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115 - lives as long as the app
    sys.stdout = sys.stderr = devnull


def _record_process(config_dir, settings_home) -> None:
    """How this tray runs, for `gitso tray`: its interpreter's name and whether a console window
    is attached. Names and yes/no only; local to this machine."""
    import json
    from Basic._files import atomic_write_bytes
    from Special._settings.fleet import fleet_directory
    console = False
    if os.name == "nt":
        import ctypes
        console = bool(ctypes.windll.kernel32.GetConsoleWindow())
    import subprocess
    try:  # the code this tray runs, so `gitso update` can tell an app older than its checkout
        commit = subprocess.run(["git", "-C", str(TRAY_SCRIPT.parents[1]), "rev-parse", "HEAD"],
                                capture_output=True, text=True, timeout=10,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = ""
    record = {"pid": os.getpid(), "interpreter": Path(sys.executable).name, "console_window": console,
              "commit": commit}
    try:
        atomic_write_bytes(fleet_directory(config_dir, home=settings_home) / "tray-process.json",
                           json.dumps(record).encode())
    except (OSError, ValueError):
        pass


def _control(args) -> int:
    """--follow, --open, --stop: talk to the running tray (App/_tray/control.py)."""
    from App._detach import running
    from App._tray import control
    from Basic import _cli
    if not running(args.config_dir, args.settings_home):
        return _cli.fail(args, "tray", "the app is not running; start it with gitso tray")
    try:
        if args.stop:
            stopped = control.request_stop(args.config_dir, args.settings_home)
            if not stopped:
                return _cli.fail(args, "tray", "the app did not quit within 15 seconds; quit it from its tray menu",
                                 _cli.FAILED)
            _cli.emit(args, _cli.document("tray", stopped=True), lambda: print("gitSpecOps has quit."))
            return 0
        if args.open:
            address = control.open_map(args.settings_home)
            _cli.emit(args, _cli.document("tray", opened=address), lambda: print(f"Opened {address}"))
            return 0
        print("Following gitSpecOps; Ctrl+C stops following (the app keeps running).", flush=True)
        for text in control.recent_events(args.settings_home):
            print(text, flush=True)
        return control.follow(args.settings_home, out=lambda text: print(text, flush=True))
    except (OSError, RuntimeError, ValueError) as exc:
        return _cli.fail(args, "tray", str(exc))


def main(argv=None) -> int:
    from Basic import _cli
    parser = _cli.parser("tray", __doc__.split("\n", 1)[0])
    parser.add_argument("--config-dir", type=Path, help="local fleet state directory")
    parser.add_argument("--settings-home", type=Path, help="common profile; defaults to the user-data home")
    parser.add_argument("--view", choices=("web", "window"),
                        help="what double-clicking the icon opens (default: the saved choice)")
    parser.add_argument("--web", choices=("off", "loopback", "tailnet"),
                        help="serve the web view for this run (default: the saved choice)")
    parser.add_argument("--open-on-start", action="store_true", help="open the view once the peer is ready")
    parser.add_argument("--remote", action="store_true",
                        help="also serve the web view on the tailnet (App/_web/remote.py)")
    parser.add_argument("--foreground", action="store_true",
                        help="run in this terminal and show its output; closing the terminal closes the app")
    control = parser.add_mutually_exclusive_group()
    control.add_argument("--follow", action="store_true",
                         help="while it runs: keep showing what it does, until Ctrl+C (the app keeps running)")
    control.add_argument("--open", action="store_true", help="open the web view at the map")
    control.add_argument("--stop", action="store_true", help="quit the running app")
    parser.add_argument("--detached", action="store_true", help=argparse.SUPPRESS)  # App/_detach.py's start
    args = parser.parse_args(argv)
    if args.follow or args.open or args.stop:
        return _control(args)
    if args.detached:
        _leave_console()
    # From a terminal (or setup), start the app on its own and return: closing that window must
    # not close the app (node1, 2026-11-15). Without a console (pythonw, start at sign-in) it is
    # already on its own, so it runs right here.
    if not (args.foreground or args.detached) and sys.stdout is not None:
        from App._detach import start
        forward = [*(["--config-dir", str(args.config_dir)] if args.config_dir else []),
                   *(["--settings-home", str(args.settings_home)] if args.settings_home else []),
                   *(["--view", args.view] if args.view else []), *(["--web", args.web] if args.web else []),
                   *(["--open-on-start"] if args.open_on_start else []), *(["--remote"] if args.remote else [])]
        from App._detach import ALREADY
        try:
            message = start(forward)
        except (OSError, RuntimeError) as exc:
            return _cli.fail(args, "tray", str(exc))
        from App._tray import control as tray_control
        running_now = tray_control.status_now(args.settings_home) if message == ALREADY else []
        events = tray_control.recent_events(args.settings_home)

        def screen():
            print(f"gitSpecOps {message}.")
            for text in running_now:
                print(f"  {text}")
            if events:
                print("Recently:")
                for text in events:
                    print(f"  {text}")
            print("It does not belong to this window: closing this window, or setup, leaves it running.\n"
                  "  gitso tray --follow   keep showing what it does (Ctrl+C stops following, not the app)\n"
                  "  gitso tray --open     open the web view at the map\n"
                  "  gitso tray --stop     quit it (or Quit on its tray menu)")
        _cli.emit(args, _cli.document("tray", message=message, status=running_now, recent=events), screen)
        return 0
    try:
        return run_tray(args.config_dir, args.settings_home, view=args.view, web=args.web,
                        open_on_start=args.open_on_start, remote=args.remote)
    except TrayUnavailable as exc:
        return _cli.fail(args, "tray", f"{exc}. Without a tray, gitso serve-web serves the web view.")
    except (OSError, ValueError) as exc:
        return _cli.fail(args, "tray", f"{failure_reason(str(exc))}.")

