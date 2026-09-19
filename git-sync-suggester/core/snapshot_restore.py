"""Recovery snapshot restore: rebuild captured work in a disposable checkout, or change nothing.

This is the step that makes a snapshot recovery rather than an archive. See
`docs/RECOVERY-DESIGN.md` ("Preview and restore") for the contract; the rules that shape this
module:

**The first target is disposable.** `prepare_disposable_checkout` clones a repository that holds
the snapshot's base into a new or empty folder and checks that base out. Restoring straight into
a working checkout that has its own changes is a later conflict workflow, never a fallback.

**Nothing is guessed.** A bundle preview marks unrestorable is refused. The target must be the
top of a checkout, at the base commit, with no staged, unstaged, or untracked changes and no Git
operation in progress. Carried files never overwrite anything, ignored files included.

**All or nothing.** Staged changes apply with `--index`, then unstaged changes on top, then the
carried untracked files. If any step fails, the checkout is reset to the base and every file this
restore created is removed, so a failed restore leaves the target as it found it.

**Success is verified, not assumed.** After applying, `git diff --staged` and `git diff` in the
target must reproduce the captured patches byte for byte, and every carried file must match its
digest. Otherwise the restore is rolled back and refused.

**Fidelity boundary, measured on Windows with Git 2.52.** What is exact is Git's content: the
staged and unstaged state as Git sees it. Working-tree bytes of patched text files follow *this*
checkout's line-ending settings (`core.autocrlf`, `.gitattributes`), exactly as an ordinary
checkout of the same content would. Carried untracked files are written raw and are
byte-identical. Whitespace handling is pinned on the command line because a user's
`apply.whitespace=fix` would silently rewrite restored content and `error` would refuse it.

Nothing here commits, pushes, fetches, or touches the repository the checkout was cloned from.
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
import subprocess

from capture import NO_HELPERS, SAFE_GIT_ENV, in_progress_operation
from snapshot_preview import base_available, preview

PATCH_FLAGS = ["--binary", "--no-color", "--no-ext-diff", "--no-textconv",
               "--src-prefix=a/", "--dst-prefix=b/"]
# Command-line config outranks every config file, so a repository's own apply settings cannot
# alter or block restored content.
PINNED = [*NO_HELPERS, "-c", "apply.whitespace=nowarn"]
GIT_TIMEOUT_SECONDS = 120


class RestoreRefused(Exception):
    """Restore stopped deliberately. The target is unchanged, or was rolled back to its base."""


def _git(repository: Path, args, data: bytes | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", *PINNED, *args], cwd=repository, input=data,
                              capture_output=True, timeout=GIT_TIMEOUT_SECONDS,
                              env={**os.environ, **SAFE_GIT_ENV}, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RestoreRefused(f"git could not complete ({exc.__class__.__name__})") from exc


def _stdout(result: subprocess.CompletedProcess) -> str:
    return result.stdout.decode("utf-8", errors="replace").strip()


def prepare_disposable_checkout(source_repository, base_commit: str, destination) -> Path:
    """Clone `source_repository` into `destination` and check out the snapshot's base.

    The source is only read. The base must already be in it: fetching is the user's explicit
    choice, never something restore does on their behalf.
    """
    source = Path(source_repository).resolve(strict=True)
    destination = Path(destination)
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise RestoreRefused("the disposable checkout location must be new or an empty folder")
    if not base_available(source, base_commit):
        raise RestoreRefused("this repository does not have the snapshot's base commit; fetch it "
                             "explicitly, then try again")
    clone = _git(source.parent, ["clone", "--quiet", "--no-checkout", str(source),
                                 str(destination)])
    if clone.returncode:
        raise RestoreRefused("could not create the disposable checkout")
    checkout = _git(destination, ["checkout", "--quiet", "--detach", base_commit])
    if checkout.returncode:
        raise RestoreRefused("the base commit is not reachable from this repository's branches or "
                             f"tags, so it could not be checked out in {destination}")
    head = _git(destination, ["rev-parse", "HEAD"])
    if head.returncode or _stdout(head) != base_commit:
        raise RestoreRefused("the disposable checkout did not end up at the base commit")
    return destination.resolve()


def _carried_destination(target: Path, relative: str) -> Path:
    """Where a carried file goes, refusing any route through a link or over a non-directory."""
    parts = relative.split("/")
    current = target
    for part in parts[:-1]:
        current = current / part
        if os.path.lexists(current) and (current.is_symlink() or not current.is_dir()):
            raise RestoreRefused(f"{relative} would be written through a link or over a file")
    destination = target.joinpath(*parts)
    try:
        destination.resolve(strict=False).relative_to(target)
    except ValueError as exc:
        raise RestoreRefused(f"{relative} resolves outside the target checkout") from exc
    return destination


def _check_target(target: Path, base_commit: str) -> None:
    top = _git(target, ["rev-parse", "--show-toplevel"])
    if top.returncode or Path(_stdout(top)).resolve() != target:
        raise RestoreRefused("the target must be the top folder of a Git checkout")
    operation = in_progress_operation(target)
    if operation:
        raise RestoreRefused(f"a {operation} is in progress in the target checkout")
    head = _git(target, ["rev-parse", "HEAD"])
    if head.returncode or _stdout(head) != base_commit:
        raise RestoreRefused("the target checkout is not at the snapshot's base commit")
    status = _git(target, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    if status.returncode or status.stdout:
        raise RestoreRefused("the target checkout must be clean: no staged, unstaged or untracked "
                             "changes")


def _rollback(target: Path, base_commit: str, created: list[Path]) -> list[str]:
    """Return the target to its base and remove what this restore created. Reports, never raises."""
    failures = []
    reset = _git(target, ["reset", "--hard", "--quiet", base_commit])
    if reset.returncode:
        failures.append("could not reset the checkout to its base")
    for path in reversed(created):
        try:
            if path.is_file() and not path.is_symlink():
                path.unlink()
            parent = path.parent
            while parent != target and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
        except OSError:
            failures.append(f"could not remove {path.relative_to(target).as_posix()}")
    return failures


def restore(body: dict, target) -> dict:
    """Apply a snapshot to a clean checkout at its base. Verified on success, rolled back on failure."""
    view = preview(body)
    if not view["restorable"]:
        raise RestoreRefused("this snapshot cannot be restored safely: "
                             + "; ".join(view["problems"]))
    target = Path(target).resolve(strict=True)
    base = view["base_commit"]
    _check_target(target, base)

    carried = [(item, _carried_destination(target, item["path"])) for item in body["files"]]
    for item, destination in carried:
        # A clean status still allows ignored files, which is exactly where a precious local
        # file with a snapshot's name would sit unnoticed.
        if os.path.lexists(destination):
            raise RestoreRefused(f"{item['path']} already exists in the target; restore never "
                                 "overwrites a file")

    staged = body["staged_patch"].encode("utf-8")
    unstaged = body["unstaged_patch"].encode("utf-8")
    if staged:
        check = _git(target, ["apply", "--check", "--index", "--whitespace=nowarn", "-"], staged)
        if check.returncode:
            raise RestoreRefused("the staged changes do not apply to this checkout")

    created: list[Path] = []
    try:
        if staged and _git(target, ["apply", "--index", "--whitespace=nowarn", "-"],
                           staged).returncode:
            raise RestoreRefused("the staged changes could not be applied")
        if unstaged:
            if _git(target, ["apply", "--check", "--whitespace=nowarn", "-"], unstaged).returncode:
                raise RestoreRefused("the unstaged changes do not apply on top of the staged "
                                     "changes")
            # Files the unstaged patch creates are untracked afterwards, so a reset alone would
            # not remove them; remember the ones that did not exist beforehand.
            for entry in view["unstaged"]:
                if entry["change"] in ("added", "renamed", "copied"):
                    path = target.joinpath(*entry["path"].split("/"))
                    if not os.path.lexists(path):
                        created.append(path)
            if _git(target, ["apply", "--whitespace=nowarn", "-"], unstaged).returncode:
                raise RestoreRefused("the unstaged changes could not be applied")

        for item, destination in carried:
            _carried_destination(target, item["path"])  # recheck: patches may have made dirs
            data = base64.b64decode(item["content_base64"], validate=True)
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                handle = open(destination, "xb")  # exclusive: never overwrite
            except FileExistsError as exc:
                raise RestoreRefused(f"{item['path']} appeared in the target during restore; "
                                     "restore never overwrites a file") from exc
            created.append(destination)
            with handle:
                handle.write(data)
            # Keep the executable bit where the platform supports it.  The content digest
            # remains the fidelity promise, but this makes a carried script behave like the
            # committed version that a later retirement proof constructs.
            try:
                os.chmod(destination, item.get("mode", 0o100644) & 0o777)
            except OSError:
                pass

        got_staged = _git(target, ["diff", "--staged", *PATCH_FLAGS])
        got_unstaged = _git(target, ["diff", *PATCH_FLAGS])
        if got_staged.stdout != staged or got_unstaged.stdout != unstaged:
            raise RestoreRefused("the restored changes do not match the snapshot exactly")
        for item, destination in carried:
            if hashlib.sha256(destination.read_bytes()).hexdigest() != item["sha256"]:
                raise RestoreRefused(f"{item['path']} does not match the snapshot after writing")
    except (RestoreRefused, OSError) as exc:
        failures = _rollback(target, base, created)
        message = str(exc) if isinstance(exc, RestoreRefused) else "a file could not be written"
        if failures:
            raise RestoreRefused(f"{message}; rollback was incomplete: "
                                 + "; ".join(failures)) from exc
        raise RestoreRefused(f"{message}; the checkout was returned to its base") from exc

    return {"target": str(target), "base_commit": base, "branch": view["branch"],
            "source_machine": view["source_machine"], "staged": len(view["staged"]),
            "unstaged": len(view["unstaged"]), "untracked": len(view["untracked"]),
            "verified": True,
            "note": "Git's staged and unstaged content matches the snapshot exactly. Text files "
                    "follow this checkout's line-ending settings; carried untracked files are "
                    "byte-identical."}
