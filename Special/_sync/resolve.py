"""Resolve a repository from the page, on this machine: the operations gitSpecOps already has.

Why:          the page shows what needs doing everywhere (2026-11-17: "we can SEE the breadth...
              we need to make it EASY to RESOLVE issues"). This puts the existing operations one
              click away, for this machine's own copies only.
Reads:        this machine's checkouts of one repository (never a path from the page, except a
              folder to stop counting, which must lie inside one of this machine's libraries).
May change:   only by the operations it calls, each with its own checks: fetch and fast-forward
              (Basic), secure-commit and secure-push (plan first, applied only by its plan id),
              the not-counted list (enrollment). Opening a folder or an editor changes nothing.
              "Safe to delete?" fetches and reads; it never deletes. The person deletes.
Results:      a JSON-ready answer for the page.
Layer:        Special: this machine, once.
Status:       working

Every operation here is the same Python function its `gitso` command calls (`commit_checked`,
`push_checked`, Basic's `fetch` and `fast_forward`), given this app's settings profile and the
chosen copy. The page and the terminal are two faces on one operation: nothing is rebuilt as a
command line, so nothing (a profile, a target) can be lost on the way (an outside review,
2026-11-17). Commit and push plan first; the page applies exactly the plan it showed, by its id.
"""
from __future__ import annotations

import filecmp
import os
import shutil
import subprocess
import sys
from pathlib import Path

from Basic._run import run

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DIFF_LIMIT = 200_000  # characters of diff shown at once
LISTED = 200  # files listed by "Safe to delete?"
OPS = {"open-folder", "open-editor", "changes", "fetch", "pull", "commit-plan", "commit-apply",
       "push-plan", "push-apply", "not-counted", "count-again", "not-counted-list",
       "not-counted-folder", "copies", "retire-check"}
#: Ops that only read (or open a window); the peer runs them outside its action lock.
READ_ONLY = {"changes", "open-folder", "open-editor", "not-counted-list", "copies"}


def _git(path: Path, *args: str, check: bool = True) -> str:
    """Git's output. A failed read raises: "could not look" must never read as "nothing here"."""
    done = run(["git", "-C", str(path), *args], timeout=120)
    if check and done.returncode:
        raise ValueError(f"git {args[0]} failed here: {(done.stderr or done.stdout).strip()[-400:]}")
    return done.stdout


def _planned(operation, apply_id, good, finished) -> dict:
    """Plan, or apply exactly the plan the page showed: the rule a terminal's --apply follows
    (Basic/_cli.run_plan). `operation(apply, approve)` returns the operation's own result."""
    result = operation(bool(apply_id), apply_id or None)
    record = result.record()
    if apply_id and result.plan_id and result.plan_id != apply_id:
        return {**record, "ok": False, "applied": False,
                "message": "What would be done changed since you checked it, so nothing was done. Check it again."}
    return {**record, "ok": result.status in good, "applied": bool(apply_id) and result.status in finished}


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


def _status(path: Path, *extra: str) -> list[dict]:
    lines = [line for line in _git(path, "status", "--porcelain=v1", *extra).splitlines() if line.strip()]
    return [{"status": line[:2], "path": line[3:].strip().strip('"')} for line in lines]


def changes(path: Path) -> dict:
    """What is uncommitted here: each file's status, a summary, and the diff (local only)."""
    files = _status(path, "-uall")
    diff = _git(path, "diff") + _git(path, "diff", "--cached")
    return {"files": files, "summary": _git(path, "diff", "--stat", "HEAD", check=False).strip(),
            "diff": diff[:DIFF_LIMIT], "cut": len(diff) > DIFF_LIMIT}


def _libraries(home) -> list[Path]:
    from Special._sync.enrollment import enrollment
    app = enrollment(home)[1] or {}
    return [Path(root).resolve() for root in app.get("roots") or []]


def _where(path: Path, libraries) -> dict:
    """A copy as the person knows it: its library's name and the folders inside it."""
    from Special._sync.manifest import library_name
    resolved = Path(path).resolve()
    for root in libraries:
        if resolved == root or root in resolved.parents:
            inside = resolved.relative_to(root)
            return {"library": library_name(root), "inside": str(inside) if str(inside) != "." else ""}
    return {"library": "", "inside": str(resolved)}


def copies(paths, home=None) -> list[dict]:
    """Each copy of one repository on this machine, in checkout order, for choosing one."""
    libraries = _libraries(home)
    found = []
    for index, path in enumerate(paths):
        path = Path(path)
        branch = _git(path, "branch", "--show-current", check=False).strip()
        head = _git(path, "log", "-1", "--format=%h %cs %s", check=False).strip()
        found.append({"checkout": index, "path": str(path), **_where(path, libraries),
                      "branch": branch, "head": head[:120]})
    return found


def retire_check(path: Path, others: list[Path]) -> dict:
    """Safe to delete this copy? Fetch every remote, then prove: every commit is on a remote,
    nothing stashed, no operation in progress, and every uncommitted or untracked file is either
    deleted here or byte-identical in another copy on this machine. Ignored files (.env, build
    output) are listed, never judged. Nothing is deleted; the person does that."""
    from Basic._discovery import classify
    from Special._sync.actions import _wipe_row
    hit = classify(path)
    if hit is None:
        raise ValueError(f"{path.name} is no longer a Git repository")
    row = _wipe_row(hit, lambda _path: False)
    files, unsafe_files = [], 0
    for entry in _status(path, "-uall")[:LISTED]:
        if entry["status"].strip() == "D":
            entry["elsewhere"] = "deleted here; nothing to lose"
        else:
            entry["elsewhere"] = _compare(path, entry["path"], others)
            unsafe_files += not entry["elsewhere"].startswith("identical")
        files.append(entry)
    ignored = []
    for entry in _status(path, "--ignored", "--untracked-files=normal")[:LISTED * 2]:
        if entry["status"] == "!!":
            entry["elsewhere"] = _exists_elsewhere(entry["path"], others)
            ignored.append(entry)
    committed_ok = row["action"] in ("replaceable", "dirty")
    safe = committed_ok and unsafe_files == 0
    if safe:
        verdict = ("Safe to delete: every commit is on a remote, nothing is stashed"
                   + (", and every changed file is the same in another copy here." if files else
                      ", and nothing is uncommitted."))
    elif not committed_ok:
        verdict = f"Not safe to delete: {row['detail']}"
    else:
        verdict = (f"Not safe to delete yet: {unsafe_files} uncommitted or untracked file"
                   f"{'' if unsafe_files == 1 else 's'} exist only here (or differ). Commit, copy or discard them first.")
    return {"safe": safe, "verdict": verdict, "action": row["action"], "path": str(path),
            "files": files, "ignored": ignored[:LISTED],
            "note": "Ignored files (like .env or build output) are listed, not judged: look at them before deleting. "
                    "gitSpecOps never deletes a copy; open the folder and delete it yourself."}


def _label(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


def _compare(path: Path, relative: str, others: list[Path]) -> str:
    """Whether another copy on this machine holds this exact file at the same place."""
    source, answer = path / relative, "only here"
    for other in others:
        target = other / relative
        try:
            if not (source.is_file() and target.is_file()):
                continue
            if filecmp.cmp(str(source), str(target), shallow=False):
                return f"identical in {_label(other)}"
            answer = f"different in {_label(other)}"
        except OSError:
            continue
    return answer


def _exists_elsewhere(relative: str, others: list[Path]) -> str:
    for other in others:
        if (other / relative.rstrip("/")).exists():
            return f"also in {_label(other)}"
    return "only here"


def _not_counted_folder(folder: str, home) -> list[str]:
    from Special._sync.enrollment import change_not_counted
    target = Path(folder).expanduser()
    if not folder or not target.is_absolute() or not target.is_dir():
        raise ValueError("name an existing folder, by its full path")
    target = target.resolve()
    if not any(target == root or root in target.parents for root in _libraries(home)):
        raise ValueError("that folder is not inside one of this machine's libraries")
    return change_not_counted(add=[str(target)], home=home)


def _plan_id(payload: dict) -> str:
    plan = str(payload.get("plan_id") or "")
    if not plan:
        raise ValueError("check it first: there is no plan to apply")
    return plan


def repo_action(op: str, payload: dict, checkouts, *, home=None) -> dict:
    """One operation on this machine's copy of a repository. `checkouts(repo_id)` gives its folders."""
    from Special._sync.enrollment import change_not_counted, enrollment
    if op not in OPS:
        raise ValueError("unknown repository action")
    if op == "not-counted-list":
        return {"not_counted": list((enrollment(home)[1] or {}).get("not_counted") or [])}
    if op == "count-again":
        path = str(payload.get("path") or "")
        current = (enrollment(home)[1] or {}).get("not_counted") or []
        if path not in current:
            raise ValueError("that folder is not on the not-counted list")
        return {"not_counted": change_not_counted(remove=[path], home=home),
                "message": "Counted again from the next read of the library."}
    if op == "not-counted-folder":
        listed = _not_counted_folder(str(payload.get("path") or ""), home)
        return {"not_counted": listed,
                "message": "Nothing inside that folder is counted from the next read. Count again undoes it."}
    paths = [Path(item) for item in checkouts(str(payload.get("repo_id") or "")) or []]
    if not paths:
        raise ValueError("this repository has no copy on this machine")
    if op == "copies":
        return {"copies": copies(paths, home)}
    index = payload.get("checkout", 0)
    if type(index) is not int or not 0 <= index < len(paths):
        raise ValueError("no such copy here")
    path = paths[index]
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
    if op == "retire-check":
        return retire_check(path, [other for other in paths if other != path])
    if op == "fetch":
        from Basic.fetch import fetch
        done = fetch(path, quiet=True, timeout=120)
        return {"ok": done.returncode == 0,
                "message": "Fetched." if done.returncode == 0 else f"Fetch failed: {(done.stderr or done.stdout).strip()[-300:]}"}
    if op == "pull":
        from Basic.pull import fast_forward
        answer = fast_forward(path)
        return {"ok": not answer.startswith("failed:"), "message": answer[0].upper() + answer[1:] + "."}
    if op in ("commit-plan", "commit-apply"):
        message = str(payload.get("message") or "").strip()
        files = payload.get("files")
        if not message or len(message) > 5000:
            raise ValueError("write a commit message (up to 5000 characters)")
        if not isinstance(files, list) or not files or len(files) > 500 or not all(isinstance(f, str) and f for f in files):
            raise ValueError("choose the files to commit")
        from Special._security._commit.operation import commit_checked
        return _planned(lambda apply, approve: commit_checked(path, files, message, settings_home=home,
                                                              apply=apply, approve=approve),
                        _plan_id(payload) if op == "commit-apply" else None,
                        good=("ready", "committed", "nothing-to-commit"), finished=("committed", "nothing-to-commit"))
    if op in ("push-plan", "push-apply"):
        from Special._security._push import push_checked
        return _planned(lambda apply, approve: push_checked(path, settings_home=home, apply=apply, approve=approve),
                        _plan_id(payload) if op == "push-apply" else None,
                        good=("planned", "pushed", "already-current"), finished=("pushed", "already-current"))
    # not-counted: this folder, by the person's choice; the next read leaves it out.
    return {"not_counted": change_not_counted(add=[str(path)], home=home),
            "message": f"{path.name} here is no longer counted. Settings lists it to count it again."}
