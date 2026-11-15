"""Install a program from its official GitHub release, for setup, where no package manager has it.

Used only by setup, and only after the person said yes in the review. TruffleHog has no winget
package, so on Windows (and on Linux without Homebrew) this is how setup installs it:

1. ask GitHub for the project's latest release, and refuse a major version gitSpecOps does not read;
2. download this system's archive and the release's checksum file over HTTPS;
3. refuse the archive unless its SHA-256 matches the checksum file;
4. take only the program out of the archive (nothing else is extracted) into tools_home().

gitSpecOps finds programs there as well as on PATH (Basic._paths.find_program), so nothing is
added to PATH. The checksum guards the download; it is published beside the archive, so trust
still rests on the project's GitHub release.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import stat
import sys
import tarfile
import urllib.request
from pathlib import Path

from Basic._paths import tools_home

RELEASES = {
    # name: GitHub repository, the major version gitSpecOps reads, archive name pattern
    "trufflehog": {"repo": "trufflesecurity/trufflehog", "major": "3",
                   "archive": "trufflehog_{version}_{os}_{arch}.tar.gz",
                   "checksums": "trufflehog_{version}_checksums.txt"},
}
TIMEOUT = 60
HEADERS = {"User-Agent": "gitSpecOps-setup", "Accept": "application/vnd.github+json"}


def system() -> tuple[str, str] | None:
    """This system's (os, arch) as release archives name them; None when unsupported."""
    names = {"win32": "windows", "darwin": "darwin", "linux": "linux"}
    os_name = names.get("linux" if sys.platform.startswith("linux") else sys.platform)
    arch = {"amd64": "amd64", "x86_64": "amd64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower())
    return (os_name, arch) if os_name and arch else None


def available(name: str) -> bool:
    """Whether setup can install `name` from its release on this system (no network)."""
    return name in RELEASES and system() is not None


def describe(name: str) -> str:
    """What saying yes does, for the question and the review."""
    return (f"Downloads the official {name} release from github.com/{RELEASES[name]['repo']}, checks its "
            f"SHA-256 against the release's checksum file, and puts only the program in {tools_home()}.")


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310  https only, below
        return response.read()


def _https(url: str) -> str:
    if not url.startswith("https://"):
        raise RuntimeError("refused: not an https address")
    return url


def verify(archive: bytes, filename: str, checksums: bytes) -> None:
    """Raise unless the checksum file lists `filename` with this archive's SHA-256."""
    digest = hashlib.sha256(archive).hexdigest()
    for line in checksums.decode("utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == filename:
            if parts[0].lower() != digest:
                raise RuntimeError(f"{filename}: checksum does not match; nothing was installed")
            return
    raise RuntimeError(f"{filename} is not in the release's checksum file; nothing was installed")


def extract_program(archive: bytes, program: str, destination: Path) -> Path:
    """Write only `program` (a top-level regular file in the archive) to `destination`."""
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        member = next((m for m in tar.getmembers() if m.name.lstrip("./") == program), None)
        if member is None or not member.isfile():
            raise RuntimeError(f"{program} is not in the archive; nothing was installed")
        data = tar.extractfile(member).read()
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / program
    partial = target.with_name(target.name + ".partial")
    partial.write_bytes(data)
    partial.chmod(partial.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.replace(partial, target)
    return target


def install(name: str, fetch=_get) -> str:
    """Install the latest supported release of `name` into tools_home(); returns what happened."""
    spec, where = RELEASES[name], system()
    if where is None:
        raise RuntimeError(f"no {name} release for this system")
    release = json.loads(fetch(f"https://api.github.com/repos/{spec['repo']}/releases/latest"))
    version = str(release.get("tag_name", "")).lstrip("v")
    if version.split(".")[0] != spec["major"]:
        raise RuntimeError(f"{name} {version} is a version gitSpecOps does not read yet (it reads {spec['major']}.x)")
    assets = {a.get("name"): a.get("browser_download_url", "") for a in release.get("assets", [])}
    filename = spec["archive"].format(version=version, os=where[0], arch=where[1])
    sums = spec["checksums"].format(version=version)
    if filename not in assets or sums not in assets:
        raise RuntimeError(f"the {name} {version} release has no {filename}")
    archive, checksums = fetch(_https(assets[filename])), fetch(_https(assets[sums]))
    verify(archive, filename, checksums)
    program = name + (".exe" if where[0] == "windows" else "")
    target = extract_program(archive, program, tools_home())
    return f"{name} {version} installed in {target.parent}"
