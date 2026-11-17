"""Resolve a repository from the page, on this machine: the operations gitSpecOps already has.

Why:          the page shows what needs doing everywhere (2026-11-17: "we can SEE the breadth...
              we need to make it EASY to RESOLVE issues"). This puts the existing operations one
              click away, for this machine's own copies only.
Reads:        this machine's checkouts of one repository (never a path from the page).
May change:   only by the operations it calls, each with its own checks: fetch and fast-forward
              (Basic), secure-commit and secure-push (plan first, applied only by its plan id),
              the not-counted list (enrollment). Opening a folder or an editor changes nothing.
Results:      a JSON-ready answer for the page.
Layer:        Special: this machine, once.
Status:       working

Commit and push run the same `gitso` commands a terminal would, so their safety checks, plans and
approvals are the same ones; the page shows the plan and applies it by its id.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GITSO = ROOT / "gitso.py"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DIFF_LIMIT = 200_000  # characters of diff shown at once
OPS = {"open-folder", "open-editor", "changes", "fetch", "pull", "commit-plan", "commit-apply",
       "push-plan", "push-apply", "not-counted", "count-again", "not-counted-list"}


def _git(path: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120, creationflags=NO_WINDOW)
    return done.stdout


def _gitso(*args: str) -> dict:
    """Run a gitso command as a terminal would, answering in JSON."""
    done = subprocess.run([sys.executable, str(GITSO), *args, "--json"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=900, cwd=str(ROOT),
                          creationflags=NO_WINDOW, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    try:
        record = json.loads(done.stdout)
    except ValueError:
        record = {"ok": False, "message": (done.stderr or done.stdout or "no answer").strip()[-1500:]}
    record.setdefault("ok", done.returncode == 0)
    return record


def _open(target: str) -> None:
    if os.name == "nt":
        os.startfile(target)  # noqa: S606 - a folder this machine observes, chosen by repository id
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target])


def editor() -> str | None:
    """VS Code's command, when installed (the PATH, then its usual Windows place)."""
    found = shutil.which("code")
    if found:
        return found
    if os.name == "nt":
        guess = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "bin" / "code.cmd"
        return str(guess) if guess.exists() else None
    mac = Path("/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code")
    return str(mac) if mac.exists() else None


def changes(path: Path) -> dict:
    """What is uncommitted here: each file's status, a summary, and the diff (local only)."""
    status = [line for line in _git(path, "status", "--porcelain=v1", "-uall").splitlines() if line.strip()]
    files = [{"status": line[:2], "path": line[3:].strip().strip('"')} for line in status]
    diff = _git(path, "diff") + _git(path, "diff", "--cached")
    return {"files": files, "summary": _git(path, "diff", "--stat", "HEAD").strip(),
            "diff": diff[:DIFF_LIMIT], "cut": len(diff) > DIFF_LIMIT}


def repo_action(op: str, payload: dict, checkouts, *, home=None) -> dict:
    """One operation on this machine's copy of a repository. `checkouts(repo_id)` gives its folders."""
    from Special._sync.enrollment import change_not_counted, enrollment
    if op not in OPS:
        raise ValueError("unknown repository action")
    if op == "not-counted-list":
        config = enrollment(home)
        return {"not_counted": list((config or {}).get("not_counted") or [])}
    if op == "count-again":
        path = str(payload.get("path") or "")
        current = (enrollment(home) or {}).get("not_counted") or []
        if path not in current:
            raise ValueError("that folder is not on the not-counted list")
        return {"not_counted": change_not_counted(remove=[path], home=home),
                "message": "Counted again from the next read of the library."}
    paths = list(checkouts(str(payload.get("repo_id") or "")) or [])
    if not paths:
        raise ValueError("this repository has no copy on this machine")
    index = payload.get("checkout", 0)
    if type(index) is not int or not 0 <= index < len(paths):
        raise ValueError("no such copy here")
    path = Path(paths[index])
    if op == "open-folder":
        _open(str(path))
        return {"message": f"Opened {path.name} in this computer's file browser."}
    if op == "open-editor":
        code = editor()
        if not code:
            raise ValueError("no editor found here (install VS Code and its 'code' command)")
        subprocess.Popen([code, str(path)], creationflags=NO_WINDOW, cwd=str(path))
        return {"message": f"Opened {path.name} in VS Code."}
    if op == "changes":
        return {"path_name": path.name, **changes(path)}
    if op == "fetch":
        return _gitso("fetch", str(path))
    if op == "pull":
        return _gitso("pull", str(path))
    if op in ("commit-plan", "commit-apply"):
        message = str(payload.get("message") or "").strip()
        files = payload.get("files")
        if not message or len(message) > 5000:
            raise ValueError("write a commit message (up to 5000 characters)")
        if not isinstance(files, list) or not files or len(files) > 500 or not all(isinstance(f, str) and f for f in files):
            raise ValueError("choose the files to commit")
        args = ["secure-commit", str(path), *files, "-m", message]
        if op == "commit-apply":
            args += ["--apply", str(payload.get("plan_id") or "")]
        return _gitso(*args)
    if op in ("push-plan", "push-apply"):
        args = ["secure-push", str(path)]
        if op == "push-apply":
            args += ["--apply", str(payload.get("plan_id") or "")]
        return _gitso(*args)
    # not-counted: this folder, by the person's choice; the next read leaves it out.
    return {"not_counted": change_not_counted(add=[str(path)], home=home),
            "message": f"{path.name} here is no longer counted. Settings lists it to count it again."}
