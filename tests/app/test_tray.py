"""The Qt tray's model, its failure reasons, and start-at-login. Offline and non-mutating.

- The tray is a skin: every number and state comes from the display document, and an
  unrecognized contract version is refused instead of guessed.
- A start that fails says why for the known causes, and never shows the raw text.
- Start-at-login is exercised against an in-memory backend: no real login entry is written.
- With PySide6 installed, the tray is built offscreen; with no system tray it steps aside.
"""
import io
import os
import sys
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

import Elaborate._fleet.autostart as fleet_autostart  # noqa: E402
from App._tray.model import (GENERIC_FAILURE, KNOWN_FAILURES, error_snapshot,  # noqa: E402
                             failure_reason, snapshot_from_display, stopped_snapshot)
from Elaborate._fleet.display import build_display  # noqa: E402
from Special._sync.manifest import build_manifest, fleet_id_for  # noqa: E402

SECRET = "22" * 32
FLEET = fleet_id_for(SECRET)


def report(machine="ts-one", dirty=0, observed=None):
    return {"manifest": build_manifest(FLEET, machine, machine, [{
        "repo_id": "c" * 32, "branch_id": "d" * 16, "has_upstream": True,
        "upstream_observed_at": None, "ahead": 0, "behind": 0,
        "staged": 0, "unstaged": dirty, "untracked": 0, "stashes": 0, "operation": None,
    }], observed_at=observed), "names": {"c" * 32: {
        "host": "github.com", "owner": "example", "name": "work"}}, "issues": []}


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def test_clean_fleet_reads_as_ok():
    snapshot = snapshot_from_display(build_display([report()], FLEET), "u", "prime")
    check(snapshot.state == "ok", f"clean fleet should be ok, got {snapshot.state}")
    check("all clear" in snapshot.text, snapshot.text)


def test_dirty_fleet_reads_as_attention():
    snapshot = snapshot_from_display(build_display([report(dirty=2)], FLEET), "u", "prime")
    check(snapshot.state == "attention" and snapshot.attention == 1, snapshot.text)


def test_stale_machine_is_surfaced():
    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    snapshot = snapshot_from_display(build_display([report(observed=old)], FLEET), "u", "prime")
    check(snapshot.stale == 1 and "stale" in snapshot.text, snapshot.text)


def test_unsupported_contract_version_refuses_to_guess():
    document = {"contract": {"name": "gitspecops.fleet.display", "version": 99}, "summary": {}}
    snapshot = snapshot_from_display(document, "u", "prime")
    check(snapshot.state == "error" and "not supported" in snapshot.text, snapshot.text)


def test_foreign_contract_is_rejected():
    document = {"contract": {"name": "something.else", "version": 1}, "summary": {}}
    check(snapshot_from_display(document, "u", "p").state == "error", "foreign contract accepted")


def test_error_snapshot_keeps_the_dashboard_reachable():
    snapshot = error_snapshot("http://127.0.0.1:8760/", "prime")
    check(snapshot.state == "error" and snapshot.ready is True, "a failed poll keeps the link")


def test_known_start_failures_get_a_specific_reason_and_nothing_raw():
    lines = {"error: no saved configuration; run setup first": "not set up",
             "error: this fleet app is already running for this configuration": "already running",
             "error: [WinError 10048] Only one usage of each socket address": "port is in use",
             "error: every configured repository root must exist": "not valid"}
    for line, expected in lines.items():
        reason = failure_reason(line)
        check(expected in reason, f"{line!r} -> {reason!r}")
        check(reason in {message for _needles, message in KNOWN_FAILURES}, "reason must be a fixed sentence")
    private = "error: C:/private/place/secret-repo exploded"
    check(failure_reason(private) == GENERIC_FAILURE, "unknown causes stay generic")
    check("private" not in stopped_snapshot(failure_reason(private)).text, "raw text must never show")


def test_error_channel_forwards_and_keeps_only_the_fixed_reason():
    from App._tray.qt import ErrorChannel

    console = io.StringIO()
    channel = ErrorChannel(console)
    channel.write("Dashboard: http://127.0.0.1:8760/\nerror: no saved ")
    channel.write("configuration at C:/private/place\n")
    check("C:/private/place" in console.getvalue(), "console output is forwarded unchanged")
    check(channel.reason and "not set up" in channel.reason, channel.reason)
    check("private" not in channel.reason, "the raw line is never kept")
    check(not hasattr(channel, "last_error"), "no raw error attribute exists")


def test_start_at_login_registers_the_tray_command():
    from App._tray.qt import TRAY_SCRIPT

    check(TRAY_SCRIPT == Path(__file__).resolve().parents[2] / "App" / "tray.py", str(TRAY_SCRIPT))
    command = fleet_autostart.launch_command(["--settings-home", "x"])
    check(command[1].endswith(str(Path("App") / "tray.py")), command)


class FakeBackend:
    """Stands in for the registry / XDG / LaunchAgent so tests never touch the real machine."""

    def __init__(self):
        self.value = None

    def status(self):
        return {"enabled": self.value is not None, "target": self.value}

    def enable(self, command):
        self.value = " ".join(command)
        return self.value

    def disable(self):
        existed, self.value = self.value is not None, None
        return existed


def test_autostart_roundtrip_without_touching_the_machine():
    backend = FakeBackend()
    original = dict(fleet_autostart._BACKENDS)
    key = "linux" if sys.platform.startswith("linux") else sys.platform
    fleet_autostart._BACKENDS[key] = ("fake backend", backend.status, backend.enable, backend.disable)
    try:
        check(fleet_autostart.status()["enabled"] is False, "should start disabled")
        check(fleet_autostart.enable(["--view", "web"])["enabled"] is True, "enable must succeed")
        check("--view" in backend.value, backend.value)
        check(fleet_autostart.disable()["removed"] is True, "disable must remove the entry")
    finally:
        fleet_autostart._BACKENDS.clear()
        fleet_autostart._BACKENDS.update(original)


def test_launch_command_is_absolute():
    command = fleet_autostart.launch_command(["--view", "web"])
    check(command[-2:] == ["--view", "web"] and Path(command[0]).is_absolute(), command)


def test_unsupported_platform_reports_a_reason():
    original = dict(fleet_autostart._BACKENDS)
    fleet_autostart._BACKENDS.clear()
    try:
        state = fleet_autostart.status()
        check(state["supported"] is False and state["reason"], state)
    finally:
        fleet_autostart._BACKENDS.update(original)


def test_without_a_system_tray_the_command_steps_aside():
    try:
        import PySide6  # noqa: F401
    except ImportError:
        print("skip: PySide6 not installed")
        return
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtGui, QtWidgets

    from App._tray import qt

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    check(not qt._icon(QtGui, (90, 190, 90)).isNull(), "the state icon must render")
    if QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
        print("skip: a real system tray is available; not starting a peer from a test")
        return
    errors = io.StringIO()
    with redirect_stderr(errors):
        code = qt.main([])
    check(code == 2 and "serve_web" in errors.getvalue(), errors.getvalue())
    del app


def main():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"ALL-TRAY-TESTS-PASS ({len(tests)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
