"""Explicit manual experiment; never launched by the offline test suite."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from urllib.parse import unquote, urlsplit


def inspect_backup(target: Path, backup_root: Path) -> dict:
    """Read only backups whose URI names the explicitly selected file; never emit content."""
    target = target.resolve(strict=True)
    saved = target.read_bytes()
    matches = []
    for candidate in backup_root.rglob("*"):
        if not candidate.is_file() or candidate.is_symlink():
            continue
        with candidate.open("rb") as stream:
            header = stream.readline(16384)
            if not header.endswith(b"\n"):
                continue
            uri = urlsplit(header.split(b" ", 1)[0].strip().decode("utf-8", errors="replace"))
            if uri.scheme != "file" or uri.netloc not in ("", "localhost"):
                continue
            decoded = unquote(uri.path)
            # VS Code percent-encodes the drive colon. Decode once, then remove the URI's
            # leading slash for a Windows drive; url2pathname differs between Python versions.
            if os.name == "nt" and len(decoded) >= 3 and decoded[0] == "/" \
                    and decoded[1].isalpha() and decoded[2] == ":":
                decoded = decoded[1:]
            if Path(decoded).resolve() != target:
                continue
            content = stream.read(10 * 1024 * 1024 + 1)
            if len(content) > 10 * 1024 * 1024:
                raise ValueError("matching backup exceeds this probe's 10 MiB inspection limit")
        # Encoding/newline differences alone are not evidence of an unsaved edit.
        normalize = lambda data: data.decode("utf-8-sig").replace("\r\n", "\n")
        matches.append({"backupBytes": len(content), "savedBytes": len(saved),
                        "contentDiffersFromSaved": normalize(content) != normalize(saved),
                        "backupAgeSeconds": round(max(0, time.time() - candidate.stat().st_mtime), 1)})
    return {"mode": "inspect-existing", "matchingBackups": len(matches), "matches": matches,
            "savedFileUnchangedDuringProbe": target.read_bytes() == saved,
            "editorExitObserved": False,
            "note": "Read-only snapshot; user confirms the edit is unsaved and editor still open."
                     " This mode does not measure typing-to-backup delay."}


def prepare() -> Path:
    root = Path(tempfile.mkdtemp(prefix="gitspecops-editor-probe-"))
    source = Path(__file__).resolve().parent
    extension = root / "extension"
    extension.mkdir()
    for name in ("package.json", "probe.js"):
        shutil.copyfile(source / name, extension / name)
    user = root / "profile" / "User"
    user.mkdir(parents=True)
    (root / "extensions").mkdir()
    (root / "workspace").mkdir()
    (root / "workspace" / "probe.txt").write_text("original saved content\n", encoding="utf-8")
    (user / "settings.json").write_text(json.dumps({
        "files.autoSave": "off", "files.hotExit": "onExitAndWindowClose",
        "security.workspace.trust.enabled": False, "telemetry.telemetryLevel": "off",
        "workbench.startupEditor": "none", "update.mode": "none",
        "extensions.autoCheckUpdates": False, "extensions.autoUpdate": False,
    }, indent=2), encoding="utf-8")
    return root


def code_executable(requested: str | None) -> str:
    found = requested or shutil.which("code")
    if not found:
        raise ValueError("VS Code was not found; use --code with its executable or launcher")
    path = Path(found).resolve()
    if os.name == "nt" and path.suffix.lower() in (".cmd", ".bat"):
        # The standard Windows launcher lives in <install>/bin/code.cmd. Use its executable
        # directly so argument passing does not involve cmd.exe or shell interpretation.
        path = path.parent.parent / "Code.exe"
    if not path.is_file() or (os.name == "nt" and path.suffix.lower() != ".exe"):
        raise ValueError("--code must identify an installed VS Code executable/launcher")
    # Portable mode can override --user-data-dir and would violate profile isolation.
    if (path.parent / "data").exists():
        raise ValueError("portable VS Code detected; use a standard installation for isolation")
    return str(path)


def run(root: Path, executable: str) -> int:
    args = [executable, "--user-data-dir", str(root / "profile"),
            "--extensions-dir", str(root / "extensions"),
            f"--extensionDevelopmentPath={root / 'extension'}",
            f"--extensionTestsPath={root / 'extension' / 'probe.js'}",
            "--disable-workspace-trust", "--skip-welcome", "--skip-release-notes",
            str(root / "workspace")]
    startup = None
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
    environment = dict(os.environ)
    environment.pop("ELECTRON_RUN_AS_NODE", None)
    with (root / "stdout.log").open("wb") as stdout, (root / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen(args, stdout=stdout, stderr=stderr, env=environment,
                                   startupinfo=startup)
        deadline = time.monotonic() + 90
        result_path = root / "result.json"
        while time.monotonic() < deadline:
            if result_path.exists():
                # The JS harness publishes the result with a same-directory atomic rename.
                result = json.loads(result_path.read_text(encoding="utf-8"))
                print(json.dumps(result, indent=2))
                return 0 if result.get("passed") is True else 1
            if process.poll() not in (None, 0):
                break
            time.sleep(0.5)
    print("Inconclusive: no result from the isolated test host. Inspect its temporary logs.")
    print("If its editor window remains open, close that isolated window.")
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="explicitly launch isolated VS Code")
    mode.add_argument("--inspect-file", type=Path,
                      help="read an existing backup for this file without launching or editing")
    parser.add_argument("--backup-root", type=Path, help="VS Code Backups directory for inspection")
    parser.add_argument("--code", help="VS Code executable/launcher, otherwise found on PATH")
    args = parser.parse_args()
    try:
        if args.inspect_file:
            backup_root = args.backup_root
            if backup_root is None and os.name == "nt":
                backup_root = Path(os.environ["APPDATA"]) / "Code" / "Backups"
            if backup_root is None or not backup_root.is_dir():
                raise ValueError("select an existing VS Code Backups directory with --backup-root")
            result = inspect_backup(args.inspect_file, backup_root)
            print(json.dumps(result, indent=2))
            return 0 if result["matchingBackups"] else 1
        if args.backup_root:
            raise ValueError("--backup-root requires --inspect-file")
        executable = code_executable(args.code) if args.run else None
        root = prepare()
        print(f"Disposable probe directory: {root}", flush=True)
        if executable is None:
            print("Prepared only. Run this script with --run to prepare and launch a fresh probe.")
            return 0
        return run(root, executable)
    except (OSError, ValueError) as exc:
        print(f"Probe could not complete: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
