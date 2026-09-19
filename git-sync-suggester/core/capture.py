"""Recovery snapshots: building a bundle of saved-but-uncommitted work.

The medium tier's job is to rescue work that a commit has not yet protected. A status manifest
cannot do that -- it carries counts, not content -- so this module produces a *bundle*: the
patches and files needed to reconstruct a working tree elsewhere.

Read `docs/RECOVERY-DESIGN.md` first; it is the contract. The decisions from it that shape
everything here:

**Bundles are written in the clear.** Every tier already rides inside a system that authenticates
(a private GitHub repo, the user's sync account, Tailscale), and the work being captured is
already sitting in plaintext in the working tree on the same disk. Encryption would add a key to
distribute -- and to lose -- without closing a gap. `FORMAT` is declared in every bundle so an
encrypted format can be added later without touching capture, preview or restore.

**Staged and unstaged are captured separately.** A lone `git diff HEAD` flattens them, and loses
staged work that the working tree later reversed. Recovery that silently drops the index is not
recovery, so this takes two patches: HEAD->index and index->worktree.

**Protection is on by default and relaxable locally, never silently.** `CapturePolicy` decides
whether ignored files may be carried and whether credential protection applies. Screening is
intrinsic: a caller that forgets to ask for it still gets it, because a skipped check that nobody
noticed is the failure this project exists to prevent. Every relaxation is written into the
bundle's notes.

Nothing here mutates a repository. No `git stash`, no index writes, no checkout. Capture reads.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess

import secret_scan
from shared.git_facts import run_git

FORMAT = "gitspecops.recovery.bundle"
FORMAT_VERSION = 1

# Reading content must never invoke a user-configured helper: an external diff or textconv
# command would run arbitrary programs during what the user was told is a read-only capture.
SAFE_GIT_ENV = {
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_EXTERNAL_DIFF": "",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0",
}
NO_HELPERS = ["-c", "diff.external=", "-c", "core.fsmonitor=", "-c", "diff.noprefix=false"]

MAX_BUNDLE_BYTES = 10 * 1024 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_FILES = 200

# Likely credential files. Held back by name under secret protection unless a path is allowed.
SENSITIVE_NAMES = (".env", ".envrc", ".netrc", ".npmrc", ".pypirc", "id_rsa", "id_ed25519")
SENSITIVE_SUFFIXES = (".pem", ".key", ".pfx", ".p12", ".keystore", ".jks", ".ppk")


class CaptureRefused(Exception):
    """Capture stopped deliberately. The message is shown to the user; it names no secret."""


@dataclass(frozen=True)
class CapturePolicy:
    """Per-repository, local-only capture policy. Defaults protect; relaxing is recorded.

    `obey_gitignore`: an ignored file is never carried, even when explicitly selected.
    `secret_protection`: likely credential files are held back by name, and content the snapshot
        adds is screened; a finding refuses the whole snapshot.
    `allow_paths`: repository-relative paths that pass both, while protection stays on for
        everything else -- so carrying one `.env` does not mean screening nothing.
    """
    obey_gitignore: bool = True
    secret_protection: bool = True
    allow_paths: tuple = ()

    def validate(self) -> "CapturePolicy":
        for path in self.allow_paths:
            parts = path.split("/") if isinstance(path, str) else []
            if (not parts or "\\" in path or path.startswith("/")
                    or any(part in ("", ".", "..") or part.lower() == ".git" for part in parts)):
                raise CaptureRefused("allowed paths must be plain repository-relative file paths")
        return self

    def notes(self) -> list[str]:
        recorded = []
        if not self.obey_gitignore:
            recorded.append("policy: .gitignore is not obeyed for files selected in this "
                            "repository")
        if not self.secret_protection:
            recorded.append("policy: secret protection is off; nothing in this snapshot was "
                            "screened")
        elif self.allow_paths:
            recorded.append("policy: allowed without name exclusion or screening: "
                            + ", ".join(sorted(self.allow_paths)))
        return recorded


@dataclass
class Bundle:
    repo_id: str
    machine_id: str
    captured_at: str
    base_commit: str
    branch: str
    staged_patch: str
    unstaged_patch: str
    files: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        body = {"format": FORMAT, "format_version": FORMAT_VERSION,
                "repo_id": self.repo_id, "machine_id": self.machine_id,
                "captured_at": self.captured_at, "base_commit": self.base_commit,
                "branch": self.branch, "staged_patch": self.staged_patch,
                "unstaged_patch": self.unstaged_patch, "files": self.files,
                "notes": self.notes}
        body["checksum"] = checksum_of(body)
        return body

    @property
    def is_empty(self) -> bool:
        return not (self.staged_patch or self.unstaged_patch or self.files)


def checksum_of(body: dict) -> str:
    """Checksum over the bundle's content, excluding the checksum field itself."""
    payload = {key: value for key, value in sorted(body.items()) if key != "checksum"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()


def _git(repository: Path, args, timeout: int = 30):
    return run_git(repository, [*NO_HELPERS, *args], timeout=timeout, env=SAFE_GIT_ENV)


def _run_bytes(repository: Path, args, what: str, data: bytes | None = None,
               ok_codes=(0,)) -> bytes:
    try:
        result = subprocess.run(["git", *NO_HELPERS, *args], cwd=repository, input=data,
                                capture_output=True, timeout=30,
                                env={**os.environ, **SAFE_GIT_ENV}, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CaptureRefused(f"could not read {what} from this repository") from exc
    if result.returncode not in ok_codes:
        raise CaptureRefused(f"could not read {what} from this repository")
    return result.stdout


def _strict(raw: bytes, what: str) -> str:
    """Decode strictly: decoding with replacement would store a patch that silently differs
    from the files it describes."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CaptureRefused(f"{what} include text that is not valid UTF-8, which this version "
                             "cannot capture faithfully") from exc


def _text(repository: Path, args, what: str) -> str:
    return _strict(_run_bytes(repository, args, what), what)


def repository_state(repository: Path) -> dict:
    """The identity a restore has to match. Read before and after capture to detect churn."""
    head = _git(repository, ["rev-parse", "HEAD"])
    if head.returncode:
        # An unborn branch has no base to patch against; the design refuses rather than
        # pretending a patch could be applied to nothing.
        raise CaptureRefused("this repository has no commit yet, so there is no base to restore "
                             "against")
    branch = _git(repository, ["rev-parse", "--abbrev-ref", "HEAD"])
    tree = _git(repository, ["rev-parse", "HEAD^{tree}"])
    status = _text(repository, ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
                   "working tree status")
    return {"commit": head.stdout.strip(), "branch": branch.stdout.strip(),
            "tree": tree.stdout.strip(), "status": status}


def in_progress_operation(repository: Path) -> str:
    """Name a half-finished Git operation. Capturing mid-merge would restore a broken state."""
    git_dir = repository / ".git"
    for marker, label in (("MERGE_HEAD", "merge"), ("rebase-merge", "rebase"),
                          ("rebase-apply", "rebase"), ("CHERRY_PICK_HEAD", "cherry-pick"),
                          ("REVERT_HEAD", "revert"), ("BISECT_LOG", "bisect")):
        if (git_dir / marker).exists():
            return label
    return ""


def inside_git_dir(relative: str) -> bool:
    return any(part.lower() == ".git" for part in PurePosixPath(relative).parts)


def is_sensitive_name(relative: str) -> bool:
    path = PurePosixPath(relative)
    if any(part in SENSITIVE_NAMES for part in path.parts):
        return True
    return path.suffix.lower() in SENSITIVE_SUFFIXES


def ignored_paths(repository: Path, paths) -> set[str]:
    """The subset of `paths` Git's ignore rules match. Exit 1 from check-ignore means none."""
    paths = [path for path in paths if path]
    if not paths:
        return set()
    raw = _run_bytes(repository, ["check-ignore", "-z", "--stdin"], "the .gitignore rules",
                     data="\0".join(paths).encode("utf-8") + b"\0", ok_codes=(0, 1))
    return {item for item in _strict(raw, "ignored file names").split("\0") if item}


def untracked_candidates(repository: Path) -> list[str]:
    """Untracked files Git itself would not ignore. Selection is still explicit and opt-in."""
    listing = _text(repository, ["ls-files", "--others", "--exclude-standard", "-z"],
                    "the untracked file list")
    return sorted(item for item in listing.split("\0") if item)


def _read_selected(repository: Path, selected, notes: list, policy: CapturePolicy) -> list:
    chosen = sorted(set(selected))
    ignored = (ignored_paths(repository, [p for p in chosen if not inside_git_dir(p)])
               if policy.obey_gitignore else set())
    allowed = set(policy.allow_paths)
    files, total = [], 0
    for relative in chosen:
        if inside_git_dir(relative):
            notes.append(f"excluded, inside .git: {relative}")
            continue
        if relative in ignored:
            notes.append(f"excluded by .gitignore: {relative} (turn off obeying .gitignore for "
                         "this repository to carry it)")
            continue
        if policy.secret_protection and relative not in allowed and is_sensitive_name(relative):
            notes.append(f"excluded as a likely credential file: {relative} (allow its path to "
                         "carry it)")
            continue
        path = (repository / relative).resolve()
        try:
            # Never follow a link out of the repository, and never capture a directory entry.
            path.relative_to(repository.resolve())
        except ValueError:
            notes.append(f"excluded, outside the repository: {relative}")
            continue
        if path.is_symlink() or not path.is_file():
            notes.append(f"excluded, not a regular file: {relative}")
            continue
        data = path.read_bytes()
        if len(data) > MAX_FILE_BYTES:
            raise CaptureRefused(f"{relative} is larger than the {MAX_FILE_BYTES // 1024} KiB "
                                 "per-file limit; exclude it or raise the limit deliberately")
        total += len(data)
        if total > MAX_BUNDLE_BYTES or len(files) >= MAX_FILES:
            raise CaptureRefused("this snapshot exceeds the configured size limits; it is "
                                 "refused rather than silently truncated")
        # Git trees preserve only the executable bit for ordinary files.  Record that
        # portable Git mode rather than the host-specific chmod bits so a later proof
        # and restore can reconstruct the same tree on another OS.
        mode = 0o100755 if path.stat().st_mode & 0o111 else 0o100644
        files.append({"path": relative, "mode": mode, "size": len(data),
                      "sha256": hashlib.sha256(data).hexdigest(),
                      "content_base64": base64.b64encode(data).decode()})
    return files


def capture(repository: Path, repo_id: str, machine_id: str, *, untracked=(),
            policy: CapturePolicy | None = None, scan=None, now=None) -> Bundle:
    """Build a bundle for one repository, or refuse and say why. Never mutates the repository.

    `scan` replaces the screening function (tests only); it never switches screening off --
    only `policy.secret_protection=False` does that, and the bundle then says so.
    """
    policy = (policy or CapturePolicy()).validate()
    repository = Path(repository).resolve(strict=True)
    operation = in_progress_operation(repository)
    if operation:
        raise CaptureRefused(f"a {operation} is in progress; finish or abort it before this "
                             "repository can be captured faithfully")
    before = repository_state(repository)
    notes: list = policy.notes()

    # Prefixes are pinned: `diff.mnemonicPrefix` or `diff.noprefix` in a user's config would
    # otherwise change the path headers that preview and restore parse on another machine.
    fixed = ["--binary", "--no-color", "--no-ext-diff", "--no-textconv",
             "--src-prefix=a/", "--dst-prefix=b/"]
    staged = _text(repository, ["diff", "--staged", *fixed], "staged changes")
    unstaged = _text(repository, ["diff", *fixed], "unstaged changes")
    files = _read_selected(repository, untracked, notes, policy)

    after = repository_state(repository)
    if after != before:
        # An editor wrote during capture. Publishing a mixture of two moments would produce a
        # bundle that never existed on disk; the caller retries on the next quiet period.
        raise CaptureRefused("the repository changed while it was being captured; it will be "
                             "captured again once writing stops")

    total = len(staged.encode()) + len(unstaged.encode()) + sum(item["size"] for item in files)
    if total > MAX_BUNDLE_BYTES:
        raise CaptureRefused("this snapshot exceeds the configured size limits; it is refused "
                             "rather than silently truncated")

    bundle = Bundle(repo_id=repo_id, machine_id=machine_id,
                    captured_at=(now or datetime.now(timezone.utc)).isoformat(),
                    base_commit=before["commit"], branch=before["branch"],
                    staged_patch=staged, unstaged_patch=unstaged, files=files, notes=notes)
    if policy.secret_protection:
        findings = (scan or secret_scan.scan_bundle)(bundle, allow_paths=policy.allow_paths)
        if findings:
            # Report the location and the rule, never the matched value: an error message is
            # itself somewhere a secret must not be copied to.
            raise CaptureRefused("possible credentials found, so nothing was captured: "
                                 + "; ".join(findings))
    return bundle
