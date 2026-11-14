"""Native, read-only filesystem change notifications for fleet observation.

There is deliberately no timer-based directory scan here. Linux uses inotify, Windows uses
ReadDirectoryChangesW and macOS uses FSEvents. All wait in the kernel while the configured
library is quiet.
The caller debounces returned paths and decides which known repository needs a Git status
refresh. New repository discovery remains an explicit inventory rescan.

Two failure modes are reported rather than swallowed, because either one used to leave the
dashboard showing old state indefinitely with nothing to say so:

- **Overflow.** When too many changes arrive at once (a large checkout, a branch switch), the
  kernel discards the individual records. `overflowed()` tells the caller to take a fresh
  inventory instead of trusting that nothing changed.
- **A watch that stops.** A Windows watch thread that fails (the drive went away) used to exit
  silently; `wait()` now raises so the caller can restart watching.
"""
from __future__ import annotations

import ctypes
import errno
import os
import queue
import select
import struct
import sys
import threading
import time
from pathlib import Path, PurePath

_IGNORED_DIRS = frozenset({
    ".svn", ".hg", "__pycache__", ".tox", ".nox", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".venv", "venv", "env", "node_modules", "bower_components",
    "site-packages", "dist-packages", ".cache", ".cargo", ".rustup", ".npm", ".nvm",
    ".nuget", ".dotnet", ".gradle", ".m2", ".android", ".docker", ".terraform",
    "AppData", "Library", ".Trash", "$RECYCLE.BIN", "System Volume Information",
})


def ignored_relative(name: str) -> bool:
    """Whether a path *relative to a watched root* falls in an ignored directory.

    Only the portion below the root may be tested. The root's own prefix is the user's choice
    and is never filtered -- a library under %LOCALAPPDATA% (AppData) or any folder called
    Library/env/venv would otherwise discard every event and observe nothing, silently.
    """
    return any(part in _IGNORED_DIRS for part in PurePath(name).parts)


def _prune(current: Path, names: list[str]) -> None:
    """Avoid dependency/build caches and Git object stores that cannot change status."""
    names[:] = [name for name in names if name not in _IGNORED_DIRS]
    if current.name == ".git":
        names[:] = [name for name in names if name not in {"objects", "lfs"}]


class LinuxEvents:
    _EVENT = struct.Struct("iIII")
    _MASK = (0x00000004 |  # IN_ATTRIB
             0x00000008 |  # IN_CLOSE_WRITE
             0x00000080 |  # IN_MOVED_TO
             0x00000040 |  # IN_MOVED_FROM
             0x00000100 |  # IN_CREATE
             0x00000200 |  # IN_DELETE
             0x00000400 |  # IN_DELETE_SELF
             0x00000800)   # IN_MOVE_SELF
    _IS_DIR = 0x40000000
    _IGNORED = 0x00008000
    _Q_OVERFLOW = 0x00004000

    def __init__(self, roots: list[Path]):
        libc = ctypes.CDLL(None, use_errno=True)
        self._add_watch = libc.inotify_add_watch
        self._add_watch.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32)
        self._add_watch.restype = ctypes.c_int
        init = libc.inotify_init1
        init.argtypes = (ctypes.c_int,)
        init.restype = ctypes.c_int
        self.fd = init(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1 failed")
        self.paths: dict[int, Path] = {}
        self._overflow = False
        try:
            for root in roots:
                self._add_tree(root)
        except Exception:
            self.close()
            raise

    def _watch(self, path: Path) -> None:
        raw = os.fsencode(path)
        wd = self._add_watch(self.fd, raw, self._MASK)
        if wd < 0:
            code = ctypes.get_errno()
            if code in (errno.ENOENT, errno.ENOTDIR, errno.EACCES):
                return
            if code == errno.ENOSPC:
                raise OSError(code, "inotify watch limit reached; reduce the selected roots")
            raise OSError(code, f"cannot watch {path}")
        self.paths[wd] = path

    def _add_tree(self, root: Path) -> None:
        for current, dirs, _files in os.walk(root, followlinks=False):
            base = Path(current)
            _prune(base, dirs)
            self._watch(base)

    def wait(self, timeout: float) -> set[Path]:
        readable, _, _ = select.select([self.fd], [], [], max(0.0, timeout))
        if not readable:
            return set()
        changed: set[Path] = set()
        while True:
            try:
                data = os.read(self.fd, 1024 * 256)
            except BlockingIOError:
                break
            offset = 0
            while offset + self._EVENT.size <= len(data):
                wd, mask, _cookie, length = self._EVENT.unpack_from(data, offset)
                offset += self._EVENT.size
                name = os.fsdecode(data[offset:offset + length].split(b"\0", 1)[0])
                offset += length
                if mask & self._Q_OVERFLOW:
                    self._overflow = True
                    continue
                base = self.paths.get(wd)
                if base is None:
                    continue
                path = base / name if name else base
                changed.add(path)
                if mask & self._IGNORED:
                    self.paths.pop(wd, None)
                elif mask & self._IS_DIR and mask & (0x00000080 | 0x00000100):
                    if path.name not in _IGNORED_DIRS:
                        self._add_tree(path)
            if len(data) < 1024 * 256:
                break
        return changed

    def take_overflow(self) -> bool:
        overflow, self._overflow = self._overflow, False
        return overflow

    def close(self) -> None:
        if getattr(self, "fd", -1) >= 0:
            os.close(self.fd)
            self.fd = -1


class WindowsEvents:
    """One blocking kernel watch per selected library root, not per repository."""
    _INVALID_HANDLE = ctypes.c_void_p(-1).value

    def __init__(self, roots: list[Path]):
        from ctypes import wintypes

        self._wintypes = wintypes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateFileW.argtypes = (
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
        self._kernel32.CreateFileW.restype = wintypes.HANDLE
        self._kernel32.ReadDirectoryChangesW.argtypes = (
            wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, wintypes.BOOL,
            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID, wintypes.LPVOID)
        self._kernel32.ReadDirectoryChangesW.restype = wintypes.BOOL
        self._kernel32.CancelIoEx.argtypes = (wintypes.HANDLE, wintypes.LPVOID)
        self._kernel32.CancelIoEx.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._queue: queue.Queue[Path] = queue.Queue()
        self._closed = threading.Event()
        self._handles = []
        self._threads = []
        self._error: str | None = None
        self._overflow = False
        for root in roots:
            handle = self._kernel32.CreateFileW(
                str(root), 0x0001, 0x00000001 | 0x00000002 | 0x00000004, None, 3,
                0x02000000, None)  # FILE_LIST_DIRECTORY, shares, OPEN_EXISTING, BACKUP_SEMANTICS
            if handle == self._INVALID_HANDLE or handle is None:
                self.close()
                raise ctypes.WinError(ctypes.get_last_error())
            self._handles.append(handle)
            thread = threading.Thread(target=self._read, args=(handle, root), daemon=True)
            self._threads.append(thread)
            thread.start()

    def _read(self, handle, root: Path) -> None:
        buffer = ctypes.create_string_buffer(64 * 1024)
        returned = self._wintypes.DWORD()
        filters = 0x00000001 | 0x00000002 | 0x00000004 | 0x00000008 | 0x00000010
        while not self._closed.is_set():
            ok = self._kernel32.ReadDirectoryChangesW(
                handle, buffer, len(buffer), True, filters, ctypes.byref(returned), None, None)
            if not ok:
                if not self._closed.is_set():
                    self._error = f"watch on {root} failed: {ctypes.WinError(ctypes.get_last_error())}"
                return
            if returned.value == 0:
                # Success with no records means the kernel buffer overflowed and the individual
                # changes were discarded. Nothing here can say which repositories moved.
                self._overflow = True
                continue
            data = buffer.raw[:returned.value]
            offset = 0
            while offset + 12 <= len(data):
                next_offset, _action, name_bytes = struct.unpack_from("III", data, offset)
                start = offset + 12
                name = bytes(data[start:start + name_bytes]).decode("utf-16-le", errors="replace")
                # ReadDirectoryChangesW reports paths relative to the watched root; only those
                # may be tested. See ignored_relative() for what testing the absolute path cost.
                if not ignored_relative(name):
                    self._queue.put(root / name)
                if not next_offset:
                    break
                offset += next_offset

    def _raise_if_stopped(self) -> None:
        if self._error is not None and self._queue.empty():
            raise OSError(self._error)

    def wait(self, timeout: float) -> set[Path]:
        self._raise_if_stopped()
        try:
            first = self._queue.get(timeout=max(0.0, timeout))
        except queue.Empty:
            self._raise_if_stopped()
            return set()
        changed = {first}
        while True:
            try:
                changed.add(self._queue.get_nowait())
            except queue.Empty:
                return changed

    def take_overflow(self) -> bool:
        overflow, self._overflow = self._overflow, False
        return overflow

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        for handle in self._handles:
            self._kernel32.CancelIoEx(handle, None)
            self._kernel32.CloseHandle(handle)
        self._handles.clear()


class MacEvents:
    """FSEvents: one recursive kernel stream for every selected root, delivered on a private
    dispatch queue. No polling and no handle per folder. Paths arrive canonical (/private/var
    for /var), which is why NativeEvents resolves the roots first."""
    _SINCE_NOW = 0xFFFFFFFFFFFFFFFF          # kFSEventStreamEventIdSinceNow
    _FILE_EVENTS = 0x00000010                 # kFSEventStreamCreateFlagFileEvents
    _NO_DEFER = 0x00000002                    # kFSEventStreamCreateFlagNoDefer
    _MUST_SCAN = 0x00000001                   # kFSEventStreamEventFlagMustScanSubDirs
    _DROPPED = 0x00000002 | 0x00000004        # kFSEventStreamEventFlag{User,Kernel}Dropped
    _UTF8 = 0x08000100                        # kCFStringEncodingUTF8
    _CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                 ctypes.POINTER(ctypes.c_char_p), ctypes.POINTER(ctypes.c_uint32),
                                 ctypes.POINTER(ctypes.c_uint64))

    def __init__(self, roots: list[Path]):
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        cs = ctypes.CDLL("/System/Library/Frameworks/CoreServices.framework/CoreServices")
        system = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        cf.CFStringCreateWithCString.argtypes = (ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32)
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFArrayCreate.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_long,
                                     ctypes.c_void_p)
        cf.CFArrayCreate.restype = ctypes.c_void_p
        cf.CFRelease.argtypes = (ctypes.c_void_p,)
        cf.CFRelease.restype = None
        cs.FSEventStreamCreate.argtypes = (ctypes.c_void_p, self._CALLBACK, ctypes.c_void_p,
                                           ctypes.c_void_p, ctypes.c_uint64, ctypes.c_double,
                                           ctypes.c_uint32)
        cs.FSEventStreamCreate.restype = ctypes.c_void_p
        for name in ("FSEventStreamStop", "FSEventStreamInvalidate", "FSEventStreamRelease"):
            getattr(cs, name).argtypes = (ctypes.c_void_p,)
            getattr(cs, name).restype = None
        cs.FSEventStreamSetDispatchQueue.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        cs.FSEventStreamSetDispatchQueue.restype = None
        cs.FSEventStreamStart.argtypes = (ctypes.c_void_p,)
        cs.FSEventStreamStart.restype = ctypes.c_ubyte
        system.dispatch_queue_create.argtypes = (ctypes.c_char_p, ctypes.c_void_p)
        system.dispatch_queue_create.restype = ctypes.c_void_p
        system.dispatch_release.argtypes = (ctypes.c_void_p,)
        system.dispatch_release.restype = None
        self._cf, self._cs, self._system = cf, cs, system
        self._roots = roots
        self._queue: queue.Queue[Path] = queue.Queue()
        self._overflow = False
        self._stream = self._dispatch = None
        self._callback = self._CALLBACK(self._on_events)   # kept alive as long as the stream

        strings = [cf.CFStringCreateWithCString(None, os.fsencode(root), self._UTF8) for root in roots]
        callbacks = ctypes.c_void_p.in_dll(cf, "kCFTypeArrayCallBacks")
        paths = cf.CFArrayCreate(None, (ctypes.c_void_p * len(strings))(*strings), len(strings),
                                 ctypes.byref(callbacks))
        for item in strings:
            cf.CFRelease(item)          # the array holds its own reference
        try:
            self._stream = cs.FSEventStreamCreate(None, self._callback, None, paths, self._SINCE_NOW,
                                                  0.05, self._FILE_EVENTS | self._NO_DEFER)
        finally:
            cf.CFRelease(paths)         # the stream keeps its own copy
        if not self._stream:
            raise OSError("FSEventStreamCreate failed")
        self._dispatch = system.dispatch_queue_create(b"gitspecops.fsevents", None)
        cs.FSEventStreamSetDispatchQueue(self._stream, self._dispatch)
        if not cs.FSEventStreamStart(self._stream):
            self.close()
            raise OSError("FSEventStreamStart failed")

    def _relative(self, path: Path) -> str | None:
        for root in self._roots:
            if path == root or root in path.parents:
                return str(path.relative_to(root))
        return None

    def _on_events(self, _stream, _info, count, paths, flags, _ids):
        for index in range(count):
            if flags[index] & (self._MUST_SCAN | self._DROPPED):
                self._overflow = True
                continue
            path = Path(os.fsdecode(paths[index]))
            relative = self._relative(path)
            if relative is None or not ignored_relative(relative):
                self._queue.put(path)

    def wait(self, timeout: float) -> set[Path]:
        try:
            first = self._queue.get(timeout=max(0.0, timeout))
        except queue.Empty:
            return set()
        changed = {first}
        while True:
            try:
                changed.add(self._queue.get_nowait())
            except queue.Empty:
                return changed

    def take_overflow(self) -> bool:
        overflow, self._overflow = self._overflow, False
        return overflow

    def close(self) -> None:
        if self._stream:
            self._cs.FSEventStreamStop(self._stream)
            self._cs.FSEventStreamInvalidate(self._stream)
            self._cs.FSEventStreamRelease(self._stream)
            self._stream = None
        if self._dispatch:
            self._system.dispatch_release(self._dispatch)
            self._dispatch = None


class NativeEvents:
    """Small cross-platform boundary used by the observer loop and synthetic tests."""
    def __init__(self, roots: list[Path], backend=None):
        roots = [Path(root).expanduser().resolve() for root in roots]
        if backend is not None:
            self.backend = backend
        elif sys.platform.startswith("linux"):
            self.backend = LinuxEvents(roots)
        elif sys.platform == "win32":
            self.backend = WindowsEvents(roots)
        elif sys.platform == "darwin":
            self.backend = MacEvents(roots)
        else:
            raise OSError("native filesystem events are not implemented on this OS yet")

    def wait(self, timeout: float = 1.0, debounce: float = 0.75) -> set[Path]:
        changed = self.backend.wait(timeout)
        if not changed:
            return changed
        deadline = time.monotonic() + max(0.0, debounce)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return changed
            more = self.backend.wait(remaining)
            if not more:
                return changed
            changed.update(more)
            deadline = time.monotonic() + max(0.0, debounce)

    def overflowed(self) -> bool:
        """True once after changes were dropped; the caller must take a fresh inventory."""
        return self.backend.take_overflow()

    def close(self) -> None:
        self.backend.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
