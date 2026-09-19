"""Explicit, local-only inspection of VS Code hot-exit backups.

VS Code has no stable public backup API, so this is deliberately not a background watcher and
never transmits content.  It reads the URI header VS Code already writes, accepts a backup only
when it maps beneath a configured repository root, and returns metadata showing whether the
buffer differs from the saved file.  A user chooses when to inspect it.
"""
from __future__ import annotations

import os
from pathlib import Path
import time
from urllib.parse import unquote, urlsplit

MAX_BUFFER_BYTES = 10 * 1024 * 1024


def default_backup_root() -> Path | None:
    appdata = os.environ.get("APPDATA")
    return Path(appdata) / "Code" / "Backups" if appdata else None


def _file_uri(header: bytes) -> Path | None:
    try:
        uri = urlsplit(header.split(b" ", 1)[0].strip().decode("utf-8", errors="strict"))
    except UnicodeDecodeError:
        return None
    if uri.scheme != "file" or uri.netloc not in ("", "localhost"):
        return None
    value = unquote(uri.path)
    if os.name == "nt" and len(value) >= 3 and value[0] == "/" and value[1].isalpha() and value[2] == ":":
        value = value[1:]
    return Path(value)


def inspect(roots, backup_root, now=None) -> list[dict]:
    """Return metadata for unsaved VS Code buffers beneath known roots.  Reads no content out."""
    root_paths = [Path(root).resolve() for root in roots]
    backup_root = Path(backup_root).resolve(strict=True)
    moment = time.time() if now is None else now
    found = []
    for candidate in backup_root.rglob("*"):
        if not candidate.is_file() or candidate.is_symlink():
            continue
        try:
            with candidate.open("rb") as stream:
                header = stream.readline(16 * 1024)
                target = _file_uri(header)
                if target is None:
                    continue
                target = target.resolve(strict=True)
                root = next((item for item in root_paths if target.is_relative_to(item)), None)
                if root is None or not target.is_file():
                    continue
                content = stream.read(MAX_BUFFER_BYTES + 1)
                if len(content) > MAX_BUFFER_BYTES:
                    continue
                saved = target.read_bytes()
        except OSError:
            continue
        normalize = lambda value: value.decode("utf-8-sig", errors="replace").replace("\r\n", "\n")
        if normalize(content) == normalize(saved):
            continue
        found.append({"root": root_paths.index(root), "path": target.relative_to(root).as_posix(),
                      "backup_bytes": len(content), "saved_bytes": len(saved),
                      "age_seconds": round(max(0, moment - candidate.stat().st_mtime), 1),
                      "state": "unsaved content differs from saved file"})
    return sorted(found, key=lambda item: (item["root"], item["path"]))
