# Qt shell trial

**Question:** on this OS and desktop, does PySide6 (Qt) give gitSpecOps a working tray /
menu-bar icon and a usable native window? Decided 2026-10-22: the App is Qt; this trial checks
it on each desktop before the App is built on it.

**What it does:** shows a tray icon (green when nothing needs attention, amber otherwise) with a
menu (Open, Refresh, Quit), and a window: the fleet table -- one column per machine -- and the
selected repository's detail (branch, commit, counts per machine). It renders the same versioned
display document the web dashboard renders and refuses a version it does not know.

**Side effects:** none. `--demo` uses an invented fleet. `--root` observes a folder of
repositories **read-only**: no fetch, nothing published, nothing written except an optional
screenshot. Closing the window leaves the tray icon running; quit from its menu.

**Prerequisites:** the repository's `.venv` with PySide6 (the App's only dependency; the
operations never import it):

```sh
# Debian 13 / KDE Plasma (from the gitSpecOps checkout)
sh run_setup.sh                         # or: python3 -m venv .venv   (needs python3-venv)
.venv/bin/python tests/run_all.py       # first: the suite has never run on Linux
.venv/bin/python -m pip install PySide6-Essentials
.venv/bin/python tests/probes/qt_shell/probe.py --demo
.venv/bin/python tests/probes/qt_shell/probe.py --root ~/<your library>
```

```powershell
# Windows
uv pip install --python .venv\Scripts\python.exe PySide6-Essentials
.venv\Scripts\python.exe tests\probes\qt_shell\probe.py --demo
```

`--screenshot FILE.png --seconds N` saves the window and quits by itself; keep screenshots of a
real library in `.agents/output/` (ignored) -- they show real repository names.

**What to look for, and report:**

1. The first line printed: the Qt platform (`wayland`, `xcb`, `windows`, `cocoa`) and whether a
   system tray is available.
2. Does the icon appear in the tray / menu bar? Does its menu open? Does clicking it open the
   window? Does closing the window keep the icon?
3. Does the window look native and readable (light and dark themes)?

**What it does not establish:** notifications, start-at-login, packaging, or any action
(pull, push, commit) -- those come with the App itself.

**Results so far:**

| Date | OS / desktop | Platform | Tray | Window |
|---|---|---|---|---|
| 2026-10-23 | Windows 11 | windows | yes | yes, native dark theme; 22 real repositories read-only |
| | Debian 13, KDE Plasma (Wayland) | | | |
| | macOS | | | |
