"""Private proposed-commit facts and transient context. No commits or presentation.

Proposal reads create no files or Git objects. Contexts contain index/path metadata and
fingerprints, not source bytes or matched values; callers keep them private and temporary.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

from Basic._facts import next_commit_identity
from Basic._objects import read_blobs
from Basic._run import run_git
from Special._settings import SettingsError
from Special.security._findings import linked
from Special.security._material import MAX_FILE_BYTES
from Special.security._me import policy_revision

HOOKS = ("pre-commit", "prepare-commit-msg", "commit-msg", "post-commit")
CONTEXT_ENV = "GITSO_COMMIT_CONTEXT"


def digest(value):
    """Internal integrity token; never publish a matched-value fingerprint."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def git(repo, arguments):
    result = run_git(repo, arguments)
    if result.returncode:
        raise SettingsError("Git could not read the proposed commit state")
    return result.stdout


def head(repo):
    """Attached branch and parent, including an unborn branch."""
    branch = git(repo, ["symbolic-ref", "-q", "HEAD"]).strip()
    result = run_git(repo, ["rev-parse", "--verify", "--quiet", "HEAD"])
    if not branch.startswith("refs/heads/") or result.returncode not in (0, 1):
        raise SettingsError("an attached, readable branch is required")
    return [branch, result.stdout.strip() if result.returncode == 0 else None]


def index(repo):
    """Active index manifest, honoring Git's temporary GIT_INDEX_FILE inside hooks."""
    result = {}
    for entry in git(repo, ["ls-files", "--stage", "-z"]).split("\0"):
        if not entry:
            continue
        metadata, separator, name = entry.partition("\t")
        parts = metadata.split()
        if not separator or len(parts) != 3 or parts[2] != "0" or "\ufffd" in name:
            raise SettingsError("unmerged or unreadable index entries require review")
        result[name] = parts[:2]
    return result


def tree(repo, parent):
    if parent is None:
        return {}
    result = {}
    for entry in git(repo, ["ls-tree", "-r", "-z", parent]).split("\0"):
        if entry:
            metadata, _, name = entry.partition("\t")
            mode, _, oid = metadata.split()
            if "\ufffd" in name:
                raise SettingsError("unreadable parent paths require review")
            result[name] = [mode, oid]
    return result


def paths(repo, selected):
    """Literal repo-relative files/deletions only; no directory/pathspec expansion or links."""
    if not isinstance(selected, (list, tuple)) or not selected:
        raise SettingsError("name at least one file")
    values = []
    for value in selected:
        if not isinstance(value, str):
            raise SettingsError("selected paths must be file names")
        value = value.replace("\\", "/")
        if (any(item in ("", ".", "..") or item.casefold() == ".git" for item in value.split("/")) or
                any(char in value for char in "\0\r\n:") or Path(value).is_absolute()):
            raise SettingsError("select literal repository-relative file paths")
        path = repo / value
        if any(linked(item) for item in (path, *path.parents) if item != repo and repo in item.parents):
            raise SettingsError("selected files must not traverse links")
        if path.exists() and not path.is_file():
            raise SettingsError("select files individually; directory/submodule selection requires review")
        values.append(value)
    return list(dict.fromkeys(values))


def raw_files(repo, selected):
    """Bounded working-tree inputs. None means deletion; failures are explicit coverage gaps."""
    for name in selected:
        try:
            with (repo / name).open("rb") as stream:
                data = stream.read(MAX_FILE_BYTES + 1)
            yield (name, None, "selected file exceeds scan size limit") if len(data) > MAX_FILE_BYTES else (name, data, "")
        except FileNotFoundError:
            yield name, None, ""
        except OSError:
            yield name, None, "selected file could not be read"


def file_revisions(repo, selected):
    result = {}
    for name, data, reason in raw_files(repo, selected):
        if reason:
            raise SettingsError("selected file cannot be bound safely")
        mode = stat.S_IMODE((repo / name).stat().st_mode) if data is not None else None
        result[name] = [hashlib.sha256(data).hexdigest() if data is not None else None, mode]
    return result


def index_files(repo, selected, manifest):
    """Only selected staged bytes; unrelated staged contents never enter the scanner."""
    for name in selected:
        entry = manifest.get(name)
        if entry is None:
            yield name, None, ""
            continue
        mode, oid = entry
        if mode not in ("100644", "100755"):
            yield name, None, "selected index entry type requires review"
            continue
        size = git(repo, ["cat-file", "-s", oid]).strip()
        if not size.isdigit() or int(size) > MAX_FILE_BYTES:
            yield name, None, "selected blob exceeds scan size limit"
            continue
        blobs = list(read_blobs(repo, [oid]))
        if len(blobs) != 1 or blobs[0][1] is None or len(blobs[0][1]) != int(size):
            yield name, None, "selected blob could not be read completely"
        else:
            yield name, blobs[0][1], ""


def constraints(repo):
    """Ordinary commits/traditional hooks first; refuse unsupported active Git operations."""
    directory = Path(git(repo, ["rev-parse", "--absolute-git-dir"]).strip())
    for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"):
        if (directory / name).exists():
            raise SettingsError("finish the existing Git operation before a checked commit")
    if git(repo, ["for-each-ref", "--format=%(refname)", "refs/replace/"]).strip() or (directory / "info/grafts").exists():
        raise SettingsError("replacement ancestry requires review before a checked commit")
    configured = run_git(repo, ["config", "--get-regexp", r"^hook\."])
    if configured.returncode not in (0, 1) or configured.returncode == 0:
        raise SettingsError("configured hook chains require compatibility review; existing hooks were not changed")
    match = re.search(r"git version (\d+)\.(\d+)", git(repo, ["version"]))
    if match is None or tuple(map(int, match.groups())) < (2, 36):
        raise SettingsError("checked commits require Git 2.36 or newer for native hook delegation")


def hook_state(repo, directory=None):
    directory = Path(directory) if directory is not None else Path(git(repo, ["rev-parse", "--path-format=absolute", "--git-path", "hooks"]).strip())
    revisions = {}
    for name in HOOKS:
        try:
            with (directory / name).open("rb") as stream:
                data = stream.read(4 * 1024 * 1024 + 1)
            if len(data) > 4 * 1024 * 1024:
                raise SettingsError("hook source exceeds supported review limit")
            revisions[name] = {"digest": hashlib.sha256(data).hexdigest(),
                               "mode": stat.S_IMODE((directory / name).stat().st_mode)}
        except FileNotFoundError:
            revisions[name] = None
    return str(directory), revisions


def proposal_state(repo, selected, message, policy):
    constraints(repo)
    entries, branch = index(repo), head(repo)
    parent = tree(repo, branch[1])
    for name in selected:
        if not (repo / name).exists() and name not in entries and name not in parent:
            raise SettingsError("a selected file is neither present nor a tracked deletion")
    hooks, revisions = hook_state(repo)
    return {"repo": str(repo), "paths": selected, "head": branch, "index": entries,
            "files": file_revisions(repo, selected), "identities": next_commit_identity(repo),
            "message": digest(message), "policy": policy_revision(policy),
            "hooks": hooks, "hook_revisions": revisions}


def write_context(path, context):
    """Atomic private temporary state; no full source bytes or finding values are saved."""
    temporary = path.with_suffix(".next")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(context, stream, ensure_ascii=True)
    os.replace(temporary, path)


def read_context(path):
    if linked(path) or not path.is_file():
        raise SettingsError("commit context is unavailable")
    context = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(context, dict) or type(context.get("schema_version")) is not int or context["schema_version"] != 1:
        raise SettingsError("unsupported commit context")
    return context
