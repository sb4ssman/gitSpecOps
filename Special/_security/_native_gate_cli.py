"""Inspect or install fail-closed Git hooks on one local checkout."""
from __future__ import annotations

import hashlib
import io
import json
import os
import shlex
import sys
import zipfile
from pathlib import Path

from Basic import _cli
from Basic._files import atomic_write_bytes
from Basic._run import run_git
from Special._security._native_gate import EVENTS, MODES, STATE
from Special._settings import select_home

COMMAND = "commit-gate"
ROOT = Path(__file__).resolve().parents[2]


def _location(repo):
    top = run_git(repo, ["rev-parse", "--show-toplevel"])
    hooks = run_git(repo, ["rev-parse", "--path-format=absolute", "--git-path", "hooks"])
    common = run_git(repo, ["rev-parse", "--path-format=absolute", "--git-common-dir"])
    if top.returncode or hooks.returncode or common.returncode or Path(top.stdout.strip()).resolve() != repo:
        raise ValueError("select a local checkout root")
    directory = Path(hooks.stdout.strip())
    if directory.resolve() != Path(common.stdout.strip()).resolve() / "hooks" or directory.is_symlink():
        raise ValueError("custom hooks directory needs integration")
    return directory


def _read(directory):
    state = directory / STATE
    if state.is_symlink():
        raise ValueError("linked hook policy")
    if not state.exists():
        return None
    record = json.loads(state.read_text(encoding="utf-8"))
    if not isinstance(record, dict) or record.get("mode") not in MODES:
        raise ValueError("invalid hook policy")
    for path in ("interpreter", "runtime", "home"):
        if not isinstance(record.get(path), str) or not Path(record[path]).is_absolute():
            raise ValueError("invalid hook runtime record")
    return record


def _script(directory, event, record):
    command = (record["interpreter"], "-I", "-B", record["runtime"], (directory / STATE).as_posix(), event)
    return ("#!/bin/sh\nexec " + " ".join(shlex.quote(arg) for arg in command) + ' "$@"\n').encode()


def _verify(directory, record):
    runtime = Path(record["runtime"])
    if not Path(record["interpreter"]).is_file() or not runtime.is_file() or runtime.is_symlink():
        return False
    if hashlib.sha256(runtime.read_bytes()).hexdigest() != runtime.stem:
        return False
    return all((hook := directory / event).is_file() and not hook.is_symlink()
               and os.access(hook, os.X_OK) and hook.read_bytes() == _script(directory, event, record)
               for event in EVENTS)


def _runtime():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(zipfile.ZipInfo("__main__.py"),
                         "from Special._security._native_gate import main\nraise SystemExit(main())\n")
        directories = set()
        for package in ("Basic", "Special", "_os"):
            for source in sorted((ROOT / package).rglob("*.py")):
                relative = source.relative_to(ROOT)
                for parent in relative.parents:
                    if parent.parts and parent not in directories:
                        archive.writestr(zipfile.ZipInfo(parent.as_posix() + "/"), b"")
                        directories.add(parent)
                entry = zipfile.ZipInfo(relative.as_posix())
                archive.writestr(entry, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


def _install(directory, record, payload):
    runtime = Path(record["runtime"])
    runtime.parent.mkdir(parents=True, exist_ok=True)
    if runtime.exists():
        if runtime.read_bytes() != payload:
            raise ValueError("installed runtime differs")
    else:
        atomic_write_bytes(runtime, payload)
    directory.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        for event in EVENTS:
            hook = directory / event
            with hook.open("xb") as handle:
                created.append(hook)
                handle.write(_script(directory, event, record))
            hook.chmod(0o755)
        atomic_write_bytes(directory / STATE, json.dumps(record, indent=2).encode())
    except BaseException:
        for hook in reversed(created):
            hook.unlink(missing_ok=True)
        raise


def main(argv=None):
    parser = _cli.parser(COMMAND, "Inspect or install Git's commit protection on a local checkout.")
    parser.add_argument("repo", type=Path)
    parser.add_argument("--mode", choices=MODES, help="scan, local-only (deny commits and pushes), or off")
    parser.add_argument("--settings-home", type=Path)
    _cli.add_apply(parser)
    args = parser.parse_args(argv)
    try:
        repo = args.repo.resolve()
        directory = _location(repo)
        current = _read(directory)
        if current and not _verify(directory, current):
            raise ValueError("managed hooks are incomplete or changed")
        if args.mode is None:
            mode = current["mode"] if current else "unmanaged"
            _cli.emit(args, _cli.document(COMMAND, True, mode=mode, hooks=str(directory)), lambda: print(mode))
            return 0
        if current is None and (args.mode == "off" or any(os.path.lexists(directory / event) for event in EVENTS)):
            raise ValueError("existing hooks need integration, or this checkout has no gate to turn off")
        home = select_home(args.settings_home, component="security")[0]
        payload = _runtime() if current is None else b""
        interpreter = Path(sys.executable)
        if interpreter.name.lower() == "pythonw.exe":
            interpreter = interpreter.with_name("python.exe")
        record = dict(current or {
            "interpreter": interpreter.as_posix(), "home": home.as_posix(),
            "runtime": (home / "hook-runtime" / (hashlib.sha256(payload).hexdigest() + ".pyz")).as_posix(),
        }, mode=args.mode)
        token = _cli.plan_id({"directory": str(directory), "current": current, "desired": record})
        if args.apply is not None and args.apply != token:
            raise ValueError("hook plan changed")
        if args.apply is None:
            _cli.emit(args, _cli.document(COMMAND, True, plan_id=token, mode=args.mode, hooks=str(directory)),
                      lambda: print(f"{args.mode}: {directory}\nPlan: {token}"))
            if not (_cli.interactive(args) and _cli.confirm("Apply this checkout's hook policy?")):
                return 0
        if _read(directory) != current or (current and not _verify(directory, current)):
            raise ValueError("hook state changed")
        if current is None:
            _install(directory, record, payload)
        else:
            atomic_write_bytes(directory / STATE, json.dumps(record, indent=2).encode())
        _cli.emit(args, _cli.document(COMMAND, True, mode=args.mode, hooks=str(directory)),
                  lambda: print(f"Active: {args.mode}"))
        return 0
    except (OSError, TypeError, ValueError) as error:
        message = str(error) if type(error) is ValueError else "hook policy unavailable"
        return _cli.fail(args, COMMAND, message, _cli.FAILED)
