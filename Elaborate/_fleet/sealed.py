"""Seal the shared protected values for a synced folder: only machines with the fleet key open them.

Why:          a synced folder is replicated by someone else's servers. The shared record holds
              the protected values themselves, so it goes there only sealed (the user,
              2026-11-16: encryption is optional, installed and turned on in setup or the app).
Reads:        the fleet key (to derive the sealing key); sealed files in the synced folder.
May change:   this machine's own sealed file in <synced folder>/settings/.
Results:      records opened from the other machines' files.
Layer:        Elaborate: other machines.
Status:       working

AES-256-GCM from the `cryptography` package (optional: `uv sync --extra app --extra crypto`,
or setup / the App & setup tab). The key is HKDF-SHA256 of the fleet key, so changing the fleet
key changes it; the machine id is bound in as associated data, so a file renamed to another
machine's name does not open. Without the package nothing is written to the folder, and
Tailscale alone carries the values.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

INFO = b"gitspecops shared protected values v1"
FOLDER = "settings"
SUFFIX = ".sealed"


def available() -> bool:
    """Whether the optional `cryptography` package is installed here."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
    except ImportError:
        return False
    return True


REQUIREMENT = "cryptography>=43"
ROOT = Path(__file__).resolve().parents[2]
VENV = ROOT / ".venv"


def venv_has(package: str) -> bool:
    """Whether this folder's .venv has `package` (its import folder) installed."""
    return (VENV / "Lib" / "site-packages" / package).exists() or any(VENV.glob(f"lib/python*/site-packages/{package}"))


def sync_extras() -> list[str]:
    """The extras every `uv sync` here must name: uv makes .venv exactly what it is told, so a sync
    without them removes the desktop app's Qt and the encryption package."""
    return [*(["--extra", "app"] if venv_has("PySide6") else []),
            *(["--extra", "crypto"] if venv_has("cryptography") else [])]


def install() -> str:
    """Install the encryption package into this folder's .venv: with uv when there is uv, else with
    the .venv's own pip. Adds one package and changes nothing else. The caller has consent."""
    import shutil
    import subprocess
    python = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        raise RuntimeError("this folder has no .venv yet; setup's desktop app part creates it")
    uv = shutil.which("uv")
    command = ([uv, "pip", "install", "--python", str(python), REQUIREMENT] if uv
               else [str(python), "-m", "pip", "install", "--disable-pip-version-check", REQUIREMENT])
    done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=600,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if done.returncode != 0:
        tail = (done.stderr or done.stdout).strip().splitlines()[-1:] or ["no output"]
        raise RuntimeError(f"installing {REQUIREMENT} did not finish: {tail[0][:200]}")
    return f"installed {REQUIREMENT} into this folder's .venv"


def _key(fleet_secret: str) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=INFO).derive(bytes.fromhex(fleet_secret))


def seal(record: dict, fleet_secret: str, machine_id: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    return b"GSO1" + nonce + AESGCM(_key(fleet_secret)).encrypt(
        nonce, json.dumps(record).encode(), machine_id.encode())


def open_sealed(blob: bytes, fleet_secret: str, machine_id: str) -> dict:
    """The record, or ValueError when it is not ours or was changed on the way."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if blob[:4] != b"GSO1" or len(blob) < 4 + 12 + 16:
        raise ValueError("not a sealed gitSpecOps file")
    try:
        data = AESGCM(_key(fleet_secret)).decrypt(blob[4:16], blob[16:], machine_id.encode())
    except InvalidTag:
        raise ValueError("this sealed file is not from this fleet, or it was changed") from None
    return json.loads(data)


def write_own(root, record: dict, fleet_secret: str, machine_id: str) -> Path:
    from Basic._files import atomic_write_bytes
    from Special._sync.manifest import SAFE_MACHINE_ID
    if not SAFE_MACHINE_ID.fullmatch(machine_id):
        raise ValueError("machine_id may contain only letters, digits, dot, underscore, and dash")
    folder = Path(root) / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    return atomic_write_bytes(folder / f"{machine_id}{SUFFIX}", seal(record, fleet_secret, machine_id))


def read_others(root, fleet_secret: str, machine_id: str) -> list[dict]:
    """Every other machine's record that opens with this fleet's key; others are skipped."""
    folder = Path(root) / FOLDER
    if not folder.is_dir():
        return []
    records = []
    for path in sorted(folder.glob(f"*{SUFFIX}")):
        other = path.name[:-len(SUFFIX)]
        if other == machine_id:
            continue
        try:
            records.append(open_sealed(path.read_bytes(), fleet_secret, other))
        except (OSError, ValueError):
            continue
    return records
