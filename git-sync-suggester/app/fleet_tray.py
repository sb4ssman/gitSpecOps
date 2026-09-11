"""Native system-tray shell for the fleet app. A skin: it renders, it never classifies.

Why this exists: the app was foreground-only, so it lived and died with a terminal window. A
fleet whose host is not running is not a fleet -- every observer's report goes nowhere and the
dashboard is simply refused. The tray makes "is it running?" answerable at a glance and makes
stopping it deliberate rather than accidental.

Boundaries, in the spirit of DISPLAY-CONTRACT.md:

- Every number and every colour here comes from the host's `gitspecops.fleet.display` document.
  The tray reads `summary.attention` and `machines[].freshness`; it never inspects a repository,
  never runs Git, and never decides what "needs attention" means. An unsupported contract
  version shows a plain warning instead of a guess.
- It offers no Git mutations. Rescan only asks the observer for one local inventory, which is
  the same read-only request `fleet rescan` already makes.
- The dashboard document is fetched on a worker thread. In connect mode that call is real HTTP
  with a 20s timeout, and a blocked message loop is a frozen, unkillable tray icon.

Implemented natively with ctypes because this project carries no runtime dependencies. Only
Windows has a stdlib-reachable tray; elsewhere `supported()` is False and the caller keeps the
console lifecycle rather than pretending.
"""
from __future__ import annotations

import ctypes
import sys
import threading
import webbrowser

from shared.version import check_for_update, version_line

CONTRACT_NAME = "gitspecops.fleet.display"
CONTRACT_VERSION = 1
POLL_SECONDS = 5.0

#: Icon body colours per state, as (blue, green, red). State is *reported*, never inferred here.
STATE_COLOURS = {
    "starting": (150, 150, 150),
    "ok": (90, 190, 90),
    "attention": (60, 180, 245),
    "error": (60, 60, 225),
}


class TrayUnavailable(RuntimeError):
    """No stdlib-reachable tray on this platform."""


def supported() -> bool:
    return sys.platform == "win32"


# --------------------------------------------------------------------------- Win32 plumbing

if sys.platform == "win32":
    # ctypes.wintypes raises on import off Windows, so it must stay inside this guard --
    # fleet_tray is imported by the cross-platform CLI and by the offline test suite.
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                                 wintypes.WPARAM, wintypes.LPARAM)

    WM_DESTROY, WM_COMMAND, WM_APP = 0x0002, 0x0111, 0x8000
    WM_LBUTTONDBLCLK, WM_RBUTTONUP, WM_LBUTTONUP = 0x0203, 0x0205, 0x0202
    WM_TRAYICON, WM_REFRESH = WM_APP + 1, WM_APP + 2
    NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
    NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x01, 0x02, 0x04, 0x10
    MF_STRING, MF_SEPARATOR, MF_GRAYED, MF_CHECKED = 0x0000, 0x0800, 0x0001, 0x0008
    TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x0002, 0x0100
    IDI_APPLICATION = 32512

    class NOTIFYICONDATA(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
            ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT),
            ("hIcon", wintypes.HICON), ("szTip", wintypes.WCHAR * 128),
            ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
            ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT),
            ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
            ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wintypes.HICON),
        ]

    class WNDCLASS(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    class ICONINFO(ctypes.Structure):
        _fields_ = [
            ("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
            ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HBITMAP),
            ("hbmColor", wintypes.HBITMAP),
        ]

    # 64-bit correctness. Every handle-taking function needs BOTH restype and argtypes: with
    # no argtypes ctypes marshals a Python int as a C int, so any handle above 2**31 raises
    # "int too long to convert". Handle values grow during a session, which makes the omission
    # intermittent -- the first tray icon built fine and a later one crashed inside the window
    # procedure. Declare the signatures rather than rely on small handles.
    HMENU, HWND, HICON = wintypes.HMENU, wintypes.HWND, wintypes.HICON
    UINT, DWORD, BOOL, INT = wintypes.UINT, wintypes.DWORD, wintypes.BOOL, ctypes.c_int
    UINT_PTR = wintypes.WPARAM
    LPVOID, LPCWSTR = wintypes.LPVOID, wintypes.LPCWSTR

    def _bind(function, restype, *argtypes):
        function.restype = restype
        function.argtypes = list(argtypes)

    _bind(user32.DefWindowProcW, LRESULT, HWND, UINT, wintypes.WPARAM, wintypes.LPARAM)
    _bind(user32.CreateWindowExW, HWND, DWORD, LPCWSTR, LPCWSTR, DWORD, INT, INT, INT, INT,
          HWND, HMENU, wintypes.HINSTANCE, LPVOID)
    _bind(user32.RegisterClassW, wintypes.ATOM, ctypes.POINTER(WNDCLASS))
    _bind(user32.CreatePopupMenu, HMENU)
    _bind(user32.AppendMenuW, BOOL, HMENU, UINT, UINT_PTR, LPCWSTR)
    _bind(user32.SetMenuDefaultItem, BOOL, HMENU, UINT, UINT)
    _bind(user32.TrackPopupMenu, BOOL, HMENU, UINT, INT, INT, INT, HWND, LPVOID)
    _bind(user32.DestroyMenu, BOOL, HMENU)
    _bind(user32.GetCursorPos, BOOL, ctypes.POINTER(wintypes.POINT))
    _bind(user32.SetForegroundWindow, BOOL, HWND)
    _bind(user32.PostMessageW, BOOL, HWND, UINT, wintypes.WPARAM, wintypes.LPARAM)
    _bind(user32.PostQuitMessage, None, INT)
    _bind(user32.GetMessageW, INT, ctypes.POINTER(wintypes.MSG), HWND, UINT, UINT)
    _bind(user32.TranslateMessage, BOOL, ctypes.POINTER(wintypes.MSG))
    _bind(user32.DispatchMessageW, LRESULT, ctypes.POINTER(wintypes.MSG))
    _bind(user32.RegisterWindowMessageW, UINT, LPCWSTR)
    _bind(user32.LoadIconW, HICON, wintypes.HINSTANCE, LPCWSTR)
    _bind(user32.CreateIconIndirect, HICON, ctypes.POINTER(ICONINFO))
    _bind(user32.DestroyIcon, BOOL, HICON)
    _bind(shell32.Shell_NotifyIconW, BOOL, DWORD, ctypes.POINTER(NOTIFYICONDATA))
    _bind(gdi32.CreateBitmap, wintypes.HBITMAP, INT, INT, UINT, UINT, LPVOID)
    _bind(gdi32.DeleteObject, BOOL, wintypes.HGDIOBJ)
    _bind(kernel32.GetModuleHandleW, wintypes.HMODULE, LPCWSTR)


def _make_icon(colour) -> int:
    """A 16x16 filled dot in the given colour. Built in memory; the build ships no .ico file."""
    size = 16
    blue, green, red = colour
    pixels = bytearray()
    centre, radius = (size - 1) / 2.0, size / 2.0 - 1.0
    for y in range(size):
        for x in range(size):
            inside = (x - centre) ** 2 + (y - centre) ** 2 <= radius ** 2
            # BGRA, premultiplied alpha not required for CreateIconIndirect's colour bitmap.
            pixels += bytes((blue, green, red, 255)) if inside else bytes((0, 0, 0, 0))
    colour_bitmap = gdi32.CreateBitmap(size, size, 1, 32, bytes(pixels))
    mask_bitmap = gdi32.CreateBitmap(size, size, 1, 1, bytes(size * size // 8))
    info = ICONINFO(True, 0, 0, mask_bitmap, colour_bitmap)
    icon = user32.CreateIconIndirect(ctypes.byref(info))
    gdi32.DeleteObject(colour_bitmap)
    gdi32.DeleteObject(mask_bitmap)
    if icon:
        return icon
    # MAKEINTRESOURCE: a stock icon id is an integer *cast* to a string pointer, not a string.
    stock = ctypes.cast(ctypes.c_void_p(IDI_APPLICATION), wintypes.LPCWSTR)
    return user32.LoadIconW(None, stock)


class _Snapshot:
    """What the tray last learned. Only fields the display contract actually defines."""

    def __init__(self):
        self.state = "starting"
        self.text = "Starting the fleet observer..."
        self.repositories = self.attention = self.machines = self.stale = 0
        self.url = ""
        self.ready = False


class WindowsTray:
    """Hidden window + notification icon. All Win32 calls stay on the thread that made them."""

    IDM_OPEN, IDM_INFO, IDM_RESCAN, IDM_AUTOSTART, IDM_QUIT = 1, 2, 3, 4, 5

    def __init__(self, stopping: threading.Event):
        self.stopping = stopping
        self.snapshot = _Snapshot()
        self.snapshot_config_dir = None  # set by on_ready; pins the login entry to this config
        # Filled in once by the poller thread. The check is read-only and never downloads; a
        # failed check stays "unknown" rather than silently claiming the build is current.
        self.version_text = version_line()
        self.lock = threading.Lock()
        self.handlers = {}
        self.hwnd = None
        self.icons = {}
        self.shown_state = None
        self.notified_state = None
        # Explorer restarts destroy every tray icon; this broadcast is how we learn to re-add.
        self.taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        self.proc = WNDPROC(self._wndproc)  # must outlive the window, or Windows calls freed memory

    # ---- lifecycle

    def create(self):
        class_name = "GitSpecOpsFleetTray"
        instance = kernel32.GetModuleHandleW(None)
        cls = WNDCLASS()
        cls.lpfnWndProc = self.proc
        cls.hInstance = instance
        cls.lpszClassName = class_name
        user32.RegisterClassW(ctypes.byref(cls))
        self.cls = cls  # keep alive alongside self.proc
        self.hwnd = user32.CreateWindowExW(0, class_name, "gitSpecOps Fleet", 0, 0, 0, 0, 0,
                                           None, None, instance, None)
        if not self.hwnd:
            raise TrayUnavailable("could not create the tray window")
        self._add_icon()

    def _icon_for(self, state):
        if state not in self.icons:
            self.icons[state] = _make_icon(STATE_COLOURS.get(state, STATE_COLOURS["starting"]))
        return self.icons[state]

    def _data(self, flags):
        data = NOTIFYICONDATA()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        data.hWnd = self.hwnd
        data.uID = 1
        data.uFlags = flags
        data.uCallbackMessage = WM_TRAYICON
        return data

    def _add_icon(self):
        with self.lock:
            snapshot = self.snapshot
            data = self._data(NIF_MESSAGE | NIF_ICON | NIF_TIP)
            data.hIcon = self._icon_for(snapshot.state)
            data.szTip = snapshot.text[:127]
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data))
        self.shown_state = snapshot.state

    def refresh(self):
        with self.lock:
            snapshot = self.snapshot
            state, text = snapshot.state, snapshot.text
        data = self._data(NIF_ICON | NIF_TIP)
        data.hIcon = self._icon_for(state)
        data.szTip = text[:127]
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data))
        # Announce only real transitions, and never the first paint -- a balloon on every
        # startup would train the user to dismiss the one that matters.
        if state != self.notified_state and self.notified_state is not None:
            if state in ("attention", "error"):
                self.notify("Fleet needs attention" if state == "attention" else "Fleet problem",
                            text)
            elif state == "ok" and self.shown_state in ("attention", "error"):
                self.notify("Fleet clear", text)
        self.notified_state = state
        self.shown_state = state

    def notify(self, title, message):
        data = self._data(NIF_INFO)
        data.szInfoTitle = title[:63]
        data.szInfo = message[:255]
        data.dwInfoFlags = 0
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data))

    def remove(self):
        if self.hwnd:
            data = self._data(0)
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))

    # ---- interaction

    def _menu(self):
        from fleet_autostart import status as autostart_status

        with self.lock:
            snapshot = self.snapshot
            ready, url = snapshot.ready, snapshot.url
            summary = (f"{snapshot.repositories} repositories, "
                       f"{snapshot.attention} need attention")
            machines = f"{snapshot.machines} machines, {snapshot.stale} stale"
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, MF_STRING | (0 if ready else MF_GRAYED), self.IDM_OPEN,
                           "Open dashboard")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING | MF_GRAYED, 0, self.version_text)
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING | MF_GRAYED, self.IDM_INFO, summary)
        user32.AppendMenuW(menu, MF_STRING | MF_GRAYED, 0, machines)
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING | (0 if ready else MF_GRAYED), self.IDM_RESCAN,
                           "Rescan repositories")
        try:
            enabled = autostart_status().get("enabled", False)
        except OSError:
            enabled = False
        user32.AppendMenuW(menu, MF_STRING | (MF_CHECKED if enabled else 0), self.IDM_AUTOSTART,
                           "Start at login")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, self.IDM_QUIT, "Quit gitSpecOps Fleet")
        user32.SetMenuDefaultItem(menu, self.IDM_OPEN, 0)
        return menu, url

    def _show_menu(self):
        menu, _url = self._menu()
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        # Required, or the menu refuses to close when the user clicks elsewhere.
        user32.SetForegroundWindow(self.hwnd)
        choice = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD, point.x, point.y,
                                       0, self.hwnd, None)
        user32.PostMessageW(self.hwnd, 0, 0, 0)
        user32.DestroyMenu(menu)
        if choice:
            self._command(choice)

    def _command(self, choice):
        if choice == self.IDM_OPEN:
            with self.lock:
                url = self.snapshot.url
            if url:
                webbrowser.open(url)
        elif choice == self.IDM_RESCAN:
            handler = self.handlers.get("rescan")
            if handler:
                try:
                    handler()
                    self.notify("Rescan requested",
                                "The observer will refresh which repositories exist.")
                except (OSError, ValueError) as exc:
                    self.notify("Rescan failed", str(exc))
        elif choice == self.IDM_AUTOSTART:
            self._toggle_autostart()
        elif choice == self.IDM_QUIT:
            self.stopping.set()
            user32.PostQuitMessage(0)

    def _toggle_autostart(self):
        import fleet_autostart

        try:
            if fleet_autostart.status().get("enabled"):
                fleet_autostart.disable()
                self.notify("Start at login disabled",
                            "The fleet observer will no longer start automatically.")
            else:
                import fleet_app

                with self.lock:
                    config_dir = self.snapshot_config_dir
                argv = ["--config-dir", str(config_dir), "tray"] if config_dir else ["tray"]
                result = fleet_autostart.enable(argv, script=fleet_app.__file__)
                self.notify("Start at login enabled",
                            f"Registered via {result['method']}.")
        except (OSError, ValueError) as exc:
            self.notify("Could not change start-at-login", str(exc))

    def _wndproc(self, hwnd, message, wparam, lparam):
        if message == WM_TRAYICON:
            event = lparam & 0xFFFF
            if event in (WM_RBUTTONUP, WM_LBUTTONUP):
                self._show_menu()
            elif event == WM_LBUTTONDBLCLK:
                self._command(self.IDM_OPEN)
            return 0
        if message == WM_REFRESH:
            self.refresh()
            return 0
        if message == self.taskbar_created:
            self.shown_state = self.notified_state = None
            self._add_icon()
            return 0
        if message == WM_COMMAND:
            self._command(wparam & 0xFFFF)
            return 0
        if message == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def pump(self):
        """Standard message loop; returns when WM_QUIT arrives or the worker stops."""
        message = wintypes.MSG()
        while True:
            result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
            if result in (0, -1):
                return
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))

    def post_refresh(self):
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_REFRESH, 0, 0)


# --------------------------------------------------------------------------- state mapping


def snapshot_from_display(document, url, label) -> _Snapshot:
    """Translate one display document into tray state. Reads the contract; decides nothing.

    An unsupported contract version is surfaced as an error rather than parsed optimistically:
    the whole point of the version field is that a skin stops instead of guessing.
    """
    snapshot = _Snapshot()
    snapshot.url = url
    snapshot.ready = True
    contract = document.get("contract") or {}
    if contract.get("name") != CONTRACT_NAME or contract.get("version") != CONTRACT_VERSION:
        snapshot.state = "error"
        snapshot.text = (f"{label}: dashboard contract "
                         f"{contract.get('name')} v{contract.get('version')} is not supported "
                         f"by this tray (expects v{CONTRACT_VERSION}).")
        return snapshot
    summary = document.get("summary") or {}
    snapshot.repositories = int(summary.get("repositories", 0))
    snapshot.attention = int(summary.get("attention", 0))
    snapshot.machines = int(summary.get("machines", 0))
    snapshot.stale = int(summary.get("stale_machines", 0))
    snapshot.state = "attention" if snapshot.attention else "ok"
    detail = (f"{snapshot.attention} of {snapshot.repositories} repositories need attention"
              if snapshot.attention else
              f"{snapshot.repositories} repositories, all clear")
    stale = f", {snapshot.stale} machine(s) stale" if snapshot.stale else ""
    snapshot.text = f"{label}: {detail}{stale}"
    return snapshot


def error_snapshot(url, label, exc) -> _Snapshot:
    snapshot = _Snapshot()
    snapshot.url = url
    snapshot.ready = bool(url)
    snapshot.state = "error"
    snapshot.text = f"{label}: cannot read the fleet dashboard ({exc})"[:200]
    return snapshot


# --------------------------------------------------------------------------- entry point


def run_tray(argv, poll_seconds: float = POLL_SECONDS) -> int:
    """Run the fleet app under a tray icon. Returns the app's exit code."""
    if not supported():
        raise TrayUnavailable(
            f"no stdlib system tray on {sys.platform}; run 'fleet run' and use start-at-login")
    from fleet_app import main as fleet_main

    stopping = threading.Event()
    tray = WindowsTray(stopping)
    tray.create()
    ready = threading.Event()
    context = {}
    result = {"code": 0}

    def on_ready(info):
        context.update(info)
        with tray.lock:
            tray.snapshot.url = info["url"]
            tray.snapshot.ready = True
            tray.snapshot_config_dir = info.get("config_dir")
        tray.handlers["rescan"] = info["rescan"]
        ready.set()
        tray.post_refresh()

    def worker():
        try:
            result["code"] = fleet_main(argv, stopping=stopping, on_ready=on_ready)
        finally:
            if not ready.is_set():
                # Setup never completed (no configuration, unreachable host, gh logged out).
                with tray.lock:
                    tray.snapshot = error_snapshot("", "Fleet app",
                                                   "the app exited before starting; see the console")
                tray.post_refresh()
            stopping.set()
            user32.PostMessageW(tray.hwnd, WM_DESTROY, 0, 0)

    def poller():
        """Never touches the UI thread; the message loop must stay responsive during HTTP."""
        ready.wait()
        label = context.get("label") or "Fleet"
        # Once per run, not per poll: nobody needs a release lookup every five seconds.
        status = check_for_update()
        tray.version_text = (f"{version_line()} — {status['latest']} available"
                             if status["state"] == "outdated" else version_line())
        if status["state"] == "outdated":
            tray.notify("Update available", status["message"])
        while not stopping.is_set():
            try:
                document = context["dashboard"]()
                snapshot = snapshot_from_display(document, context["url"], label)
            except Exception as exc:  # a skin must survive any host or transport failure
                snapshot = error_snapshot(context.get("url", ""), label, exc)
            with tray.lock:
                tray.snapshot = snapshot
            tray.post_refresh()
            stopping.wait(poll_seconds)

    threads = [threading.Thread(target=worker, name="fleet-app", daemon=True),
               threading.Thread(target=poller, name="fleet-tray-poll", daemon=True)]
    for thread in threads:
        thread.start()
    try:
        tray.pump()
    finally:
        stopping.set()
        tray.remove()
        for thread in threads:
            thread.join(timeout=10)
    return result["code"]


def main(argv=None) -> int:
    from shared.console import enable_unicode_output

    enable_unicode_output()
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        return run_tray(argv or ["run"])
    except TrayUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from _paths import bootstrap

    bootstrap()
    raise SystemExit(main())
