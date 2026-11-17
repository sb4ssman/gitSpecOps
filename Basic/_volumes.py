"""Which disk a folder is on, as the disk itself says: read-only, stdlib-only, no policy.

Why:          one box with two operating systems (a dual-boot machine, 2026-11-17) sees one shared
              disk from both. The disk's own serial number is the same from each system, so a
              library on it can be recognised as the same library without writing anything.
Reads:        the volume serial (Windows), the filesystem UUID (Linux, via findmnt), the volume
              UUID (macOS, via diskutil); the folder's path from its volume's root.
May change:   nothing.
Results:      (volume key, path inside the volume), or None when it cannot be read.
Layer:        Basic: one host operation.
Status:       working

The key is the last eight hex digits of the serial or UUID: Windows shows a 32-bit NTFS serial,
Linux the full 64-bit one whose last 32 bits are the same number, and FAT/exFAT serials are 32
bits on both. Callers hash it with their own secret before it leaves the machine.
"""
from __future__ import annotations

import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path


def _key(text: str | None) -> str | None:
    digits = re.sub(r"[^0-9A-Fa-f]", "", text or "")
    return digits[-8:].upper() if len(digits) >= 8 else None


def _inside(path: Path, mount: Path) -> str:
    try:
        relative = path.relative_to(mount)
    except ValueError:
        return ""
    return "/".join(part.casefold() for part in relative.parts)


def _windows(path: Path):
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.windll.kernel32
    root = ctypes.create_unicode_buffer(260)
    if not kernel.GetVolumePathNameW(str(path), root, 260):
        return None
    serial = wintypes.DWORD()
    if not kernel.GetVolumeInformationW(root.value, None, 0, ctypes.byref(serial), None, None, None, 0):
        return None
    return f"{serial.value:08X}", _inside(path, Path(root.value))


def _run(argv: list[str]) -> str | None:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def _linux(path: Path):
    out = _run(["findmnt", "-n", "-o", "UUID,TARGET", "--target", str(path)])
    if not out or not out.strip():
        return None
    uuid, _, target = out.strip().partition(" ")
    key = _key(uuid)
    return (key, _inside(path, Path(target.strip()))) if key else None


def _macos(path: Path):
    df = _run(["df", "-P", str(path)])
    if not df:
        return None
    lines = df.strip().splitlines()
    if len(lines) < 2:
        return None
    mount = lines[-1].split(None, 5)[-1]
    info = _run(["diskutil", "info", "-plist", mount])
    if not info:
        return None
    try:
        data = plistlib.loads(info.encode())
    except (ValueError, plistlib.InvalidFileException):
        return None
    key = _key(data.get("VolumeUUID") or data.get("DiskUUID"))
    return (key, _inside(path, Path(mount))) if key else None


def volume_of(path) -> tuple[str, str] | None:
    """(volume key, the folder's path inside that volume, lower-case with "/") or None."""
    path = Path(path).resolve()
    try:
        if os.name == "nt":
            return _windows(path)
        if sys.platform == "darwin":
            return _macos(path)
        return _linux(path)
    except (OSError, ValueError, AttributeError):
        return None
