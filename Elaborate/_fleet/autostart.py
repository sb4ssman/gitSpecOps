"""Per-user start-at-login registration. Consent lives with the caller; this only executes it.

Deliberately per-user, never system-wide: the fleet app must run **as the interactive user**, so
that Git ownership, the gh login, Tailscale identity and any synchronized-folder mount are the
same ones the user has. A machine-wide service running as SYSTEM would see a different gh
account and a different Tailscale identity -- the exact correctness trap recorded in
``.agents/WORKING-NOTES.md``. Nothing here elevates, and nothing here installs a service.

Every backend is reversible from the same API (``disable``) and inspectable (``status``), so a
user is never left with a startup entry they cannot find. No backend writes outside the user's
own profile.

Each system also has its own switch for start-up items, which people use without gitSpecOps:
Task Manager or Settings > Apps > Startup on Windows, Startup Applications on Linux desktops,
Login Items on macOS. ``status`` reads that switch, so an entry turned off there is reported as
off ("turned_off_elsewhere"), never as on. ``enable`` turns that switch back on; ``disable``
removes the entry and that switch's record of it, leaving nothing behind.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

APP_NAME = "GitSpecOpsFleet"
DISPLAY_NAME = "gitSpecOps Fleet"


def launch_command(argv=None, script=None) -> list[str]:
    """The command that reproduces this process at login.

    ``script`` must be passed explicitly by callers, because ``sys.argv[0]`` is the wrong
    answer in exactly the cases that matter: the same tray menu item can be clicked from
    ``sync_suggester.py fleet tray`` (which needs the ``fleet`` prefix), from ``fleet_app.py``
    (which does not), or from the frozen build (which has no script at all). Registering an
    argv the target cannot parse produces a login entry that silently fails every boot.

    Paths are resolved so the entry does not depend on the login shell's working directory.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve()), *argv]
    target = Path(script).resolve() if script else Path(__file__).resolve().parents[2] / "App" / "tray.py"
    return [str(Path(sys.executable).resolve()), str(target), *argv]


def _quote(command: list[str]) -> str:
    if sys.platform == "win32":
        return " ".join(f'"{part}"' if " " in part else part for part in command)
    return shlex.join(command)


# --------------------------------------------------------------------------- Windows


def _windows_key():
    import winreg
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                          r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                          winreg.KEY_READ | winreg.KEY_WRITE)


#: Task Manager's and Settings' own on/off switch for each Run entry. A missing value means on;
#: a value whose first byte is odd (03) means the person turned it off there.
_APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"


def _windows_turned_off() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _APPROVED) as key:
            data, _kind = winreg.QueryValueEx(key, APP_NAME)
    except FileNotFoundError:
        return False
    return bool(data) and bool(data[0] & 1)


def _windows_forget_switch():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _APPROVED, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP_NAME)
    except FileNotFoundError:
        pass


def _windows_status():
    import winreg
    try:
        with _windows_key() as key:
            value, _kind = winreg.QueryValueEx(key, APP_NAME)
    except FileNotFoundError:
        return {"enabled": False, "registered": False, "turned_off_elsewhere": False, "target": None}
    off = _windows_turned_off()
    return {"enabled": not off, "registered": True, "turned_off_elsewhere": off,
            "elsewhere": "Task Manager (Startup apps)" if off else None, "target": value}


def _windows_enable(command):
    import winreg
    # pythonw.exe keeps a source-run tray from flashing a console window at every login.
    if not getattr(sys, "frozen", False):
        pythonw = Path(command[0]).with_name("pythonw.exe")
        if pythonw.is_file():
            command = [str(pythonw), *command[1:]]
    with _windows_key() as key:
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _quote(command))
    _windows_forget_switch()  # turned off in Task Manager before: on again, as asked
    return _quote(command)


def _windows_disable():
    import winreg
    _windows_forget_switch()
    try:
        with _windows_key() as key:
            winreg.DeleteValue(key, APP_NAME)
        return True
    except FileNotFoundError:
        return False


# --------------------------------------------------------------------------- Linux


def _xdg_autostart_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "autostart" / f"{APP_NAME}.desktop"


def _linux_status():
    """Startup Applications (GNOME, Cinnamon, MATE, KDE) turn an entry off inside the file:
    ``Hidden=true`` or ``X-GNOME-Autostart-enabled=false``."""
    path = _xdg_autostart_path()
    if not path.is_file():
        return {"enabled": False, "registered": False, "turned_off_elsewhere": False, "target": None}
    fields = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep:
            fields.setdefault(name.strip(), value.strip())
    off = (fields.get("Hidden", "").lower() == "true"
           or fields.get("X-GNOME-Autostart-enabled", "").lower() == "false")
    return {"enabled": not off, "registered": True, "turned_off_elsewhere": off,
            "elsewhere": "Startup Applications" if off else None,
            "target": fields.get("Exec") or str(path)}


def _linux_enable(command):
    path = _xdg_autostart_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([
        "[Desktop Entry]", "Type=Application", f"Name={DISPLAY_NAME}",
        "Comment=Personal Git fleet observer", f"Exec={_quote(command)}",
        "Terminal=false", "X-GNOME-Autostart-enabled=true", "",
    ]), encoding="utf-8")
    return _quote(command)


def _linux_disable():
    path = _xdg_autostart_path()
    if path.is_file():
        path.unlink()
        return True
    return False


# --------------------------------------------------------------------------- systemd (headless)


def _systemd_unit_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "systemd" / "user" / f"{APP_NAME}.service"


def _systemctl(*args) -> bool:
    try:
        return subprocess.run(["systemctl", "--user", *args], capture_output=True,
                              timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def systemd_enable(command) -> str:
    """Headless Linux hosts have no desktop session to run an autostart entry.

    ``linger`` is NOT enabled here: that would keep the unit running with nobody logged in,
    which is a system-level decision the user must make themselves. The unit is reported as
    login-scoped so that expectation stays honest.
    """
    path = _systemd_unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([
        "[Unit]", f"Description={DISPLAY_NAME} observer", "After=network-online.target", "",
        "[Service]", "Type=simple", f"ExecStart={_quote(command)}", "Restart=on-failure",
        "RestartSec=15", "",
        "[Install]", "WantedBy=default.target", "",
    ]), encoding="utf-8")
    _systemctl("daemon-reload")
    _systemctl("enable", f"{APP_NAME}.service")
    return str(path)


def systemd_disable() -> bool:
    path = _systemd_unit_path()
    _systemctl("disable", "--now", f"{APP_NAME}.service")
    if path.is_file():
        path.unlink()
        _systemctl("daemon-reload")
        return True
    return False


# --------------------------------------------------------------------------- macOS


def _launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"com.gitspecops.{APP_NAME}.plist"


_MAC_LABEL = f"com.gitspecops.{APP_NAME}"


def _macos_domain() -> str:
    return f"gui/{os.getuid()}"


def _macos_turned_off() -> bool:
    """System Settings > General > Login Items, and `launchctl disable`, record the agent as
    disabled in launchd; `launchctl print-disabled` lists it. Not yet tried on a Mac."""
    try:
        out = subprocess.run(["launchctl", "print-disabled", _macos_domain()], capture_output=True,
                             text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    for line in out.splitlines():
        if f'"{_MAC_LABEL}"' in line:
            return line.rstrip().endswith(("disabled", "true"))
    return False


def _macos_status():
    path = _launch_agent_path()
    if not path.is_file():
        return {"enabled": False, "registered": False, "turned_off_elsewhere": False, "target": None}
    off = _macos_turned_off()
    return {"enabled": not off, "registered": True, "turned_off_elsewhere": off,
            "elsewhere": "Login Items" if off else None, "target": str(path)}


def _macos_enable(command):
    path = _launch_agent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    arguments = "".join(f"    <string>{part}</string>\n" for part in command)
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n<dict>\n'
        f"  <key>Label</key><string>{_MAC_LABEL}</string>\n"
        f"  <key>ProgramArguments</key>\n  <array>\n{arguments}  </array>\n"
        "  <key>RunAtLoad</key><true/>\n"
        "</dict>\n</plist>\n", encoding="utf-8")
    # Turned off in Login Items before: on again, as asked.
    subprocess.run(["launchctl", "enable", f"{_macos_domain()}/{_MAC_LABEL}"], capture_output=True,
                   check=False, timeout=30)
    subprocess.run(["launchctl", "load", str(path)], capture_output=True, check=False, timeout=30)
    return str(path)


def _macos_disable():
    path = _launch_agent_path()
    if path.is_file():
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True, check=False,
                       timeout=30)
        path.unlink()
        return True
    return False


# --------------------------------------------------------------------------- public API

_BACKENDS = {
    "win32": ("registry Run key (current user)", _windows_status, _windows_enable, _windows_disable),
    "linux": ("XDG autostart entry", _linux_status, _linux_enable, _linux_disable),
    "darwin": ("LaunchAgent", _macos_status, _macos_enable, _macos_disable),
}


def _backend():
    key = "linux" if sys.platform.startswith("linux") else sys.platform
    return _BACKENDS.get(key)


def status() -> dict:
    backend = _backend()
    if backend is None:
        return {"supported": False, "enabled": False, "method": None, "target": None,
                "reason": f"no start-at-login backend for {sys.platform}"}
    method, read, _enable, _disable = backend
    return {"supported": True, "method": method, "reason": None, **read()}


def enable(argv=None, script=None) -> dict:
    """Register a command to run at login. The caller is responsible for having consent."""
    backend = _backend()
    if backend is None:
        raise ValueError(f"no start-at-login backend for {sys.platform}")
    method, _read, write, _disable = backend
    target = write(launch_command(argv, script))
    return {"enabled": True, "method": method, "target": target}


def disable() -> dict:
    backend = _backend()
    if backend is None:
        raise ValueError(f"no start-at-login backend for {sys.platform}")
    method, _read, _write, remove = backend
    return {"enabled": False, "method": method, "removed": remove()}


def main(argv=None) -> int:
    """Standalone: ``python fleet_autostart.py [status|enable|disable] [-- args...]``"""
    import argparse
    import json

    from Basic._console import enable_unicode_output
    enable_unicode_output()
    parser = argparse.ArgumentParser(description="inspect or change start-at-login registration")
    parser.add_argument("action", choices=("status", "enable", "disable"), default="status",
                        nargs="?")
    parser.add_argument("--systemd", action="store_true",
                        help="Linux: use a systemd --user unit instead of an autostart entry")
    parser.add_argument("run_args", nargs=argparse.REMAINDER,
                        help="arguments the registered command should receive")
    args = parser.parse_args(argv)
    run_args = [a for a in args.run_args if a != "--"]
    if args.systemd and sys.platform.startswith("linux"):
        if args.action == "enable":
            print(json.dumps({"enabled": True, "method": "systemd --user",
                              "target": systemd_enable(launch_command(run_args))}, indent=2))
        elif args.action == "disable":
            print(json.dumps({"enabled": False, "removed": systemd_disable()}, indent=2))
        else:
            print(json.dumps({"supported": True, "method": "systemd --user",
                              "enabled": _systemd_unit_path().is_file()}, indent=2))
        return 0
    result = {"status": status, "enable": lambda: enable(run_args), "disable": disable}[args.action]()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    raise SystemExit(main())
