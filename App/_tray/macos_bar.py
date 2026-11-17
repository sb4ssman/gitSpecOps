"""macOS without Qt: build and start the native menu-bar icon (App/_tray/macos_menubar.swift).

Why:          a Mac too old for Qt (macOS 10.15) ran the app with no icon at all. Swift and
              AppKit come with the Command Line Tools, so the icon needs nothing installed.
Reads:        the Swift source; whether `swiftc` exists.
May change:   builds GitSpecOps.app in this machine's fleet folder (again only when the source
              changes) and starts it. Nothing outside the fleet folder; no sign-in item.
Results:      a short status line for the app's log; never raises.
Layer:        App: presence and presentation.
Status:       working (macOS 10.15, 2026-11-16)

The icon quits by itself when the app's process ends; its Quit asks the app to stop.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

SOURCE = Path(__file__).with_name("macos_menubar.swift")
BUNDLE = "GitSpecOps.app"
PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleExecutable</key><string>GitSpecOps</string>
  <key>CFBundleIdentifier</key><string>io.github.sb4ssman.gitspecops.menubar</string>
  <key>CFBundleName</key><string>gitSpecOps</string>
  <key>LSUIElement</key><true/>
</dict></plist>
"""


def swift_compiler() -> str | None:
    """The Swift compiler, when the Command Line Tools (or Xcode) are installed."""
    found = shutil.which("swiftc")
    if found:
        return found
    try:
        done = subprocess.run(["/usr/bin/xcrun", "--find", "swiftc"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    path = done.stdout.strip()
    return path if done.returncode == 0 and path and Path(path).exists() else None


def build(folder: Path) -> Path:
    """The bundle, compiled only when the Swift source changed since the last build."""
    bundle = folder / BUNDLE
    binary = bundle / "Contents" / "MacOS" / "GitSpecOps"
    stamp = folder / "menubar-source.sha256"
    digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    if binary.exists() and stamp.exists() and stamp.read_text().strip() == digest:
        return bundle
    compiler = swift_compiler()
    if not compiler:
        raise RuntimeError("no Swift compiler (install the Command Line Tools: xcode-select --install)")
    binary.parent.mkdir(parents=True, exist_ok=True)
    done = subprocess.run([compiler, "-O", str(SOURCE), "-o", str(binary)], capture_output=True, text=True,
                          timeout=600)
    if done.returncode:
        raise RuntimeError(f"the menu-bar icon did not compile: {(done.stderr or done.stdout)[-300:]}")
    (bundle / "Contents" / "Info.plist").write_text(PLIST, encoding="utf-8")
    stamp.write_text(digest, encoding="utf-8")
    return bundle


def start(folder: Path, page: str | None, pid: int | None = None) -> str:
    """Build (if needed) and start the icon for the app running as `pid`. A status line."""
    if sys.platform != "darwin":
        return "menu-bar icon: not a Mac"
    try:
        bundle = build(folder)
        gitso = Path.home() / ".gitspecops" / "bin" / "gitso"
        args = ["--pid", str(pid or os.getpid()), "--page", page or "http://127.0.0.1:8760/"]
        if gitso.exists():
            args += ["--gitso", str(gitso)]
        # -n: a new instance for this app run; -g: do not take focus.
        subprocess.run(["/usr/bin/open", "-n", "-g", str(bundle), "--args", *args], check=True,
                       capture_output=True, timeout=30)
        return "menu-bar icon: started"
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return f"menu-bar icon: not shown ({exc})"
