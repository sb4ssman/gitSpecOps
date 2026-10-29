"""Read-only tree/history scanning over Basic's Git readers and the shared check registry."""
from __future__ import annotations

import os
import re
import hashlib
from dataclasses import replace
from pathlib import Path

from Basic._objects import commits, file_versions, files_at, git_output, read_blobs
from Basic._run import CommandFailed, run_git, stream
from Special.security._checks import inspect
from Special.security._contents import image_metadata, is_archive, is_image, open_archive
from Special.security._findings import Finding, Report, linked
from Special.security._engines import EngineBatch
from Special.security import _reviews

MAX_FILE_BYTES = 32 * 1024 * 1024


def _text(report, text, where, policy, object_id="", *, content_id=None, context_kind="content"):
    findings = inspect(text, where, policy, object_id)
    report.findings.extend(replace(item, content_id=content_id if content_id is not None else item.content_id,
                                   context_kind=context_kind) for item in findings)
    runner = getattr(report, "_engine_runner", None)
    if runner is not None:
        runner.add(text, where, object_id)


def _bytes(report, data, where, policy, object_id=""):
    _text(report, data.decode("utf-8", errors="replace"), where, policy, object_id,
          content_id=hashlib.sha256(data).hexdigest())
    if data.startswith(b"version https://git-lfs.github.com/spec/v1"):
        report.gap(where, "Git LFS pointer only; payload not inspected")
    archive_name = where
    for signature, suffix in ((b"PK\x03\x04", ".zip"), (b"PK\x05\x06", ".zip"),
                              (b"\x1f\x8b", ".gz"), (b"BZh", ".bz2"), (b"\xfd7zXZ\0", ".xz")):
        if data.startswith(signature) and not is_archive(where):
            archive_name = where + suffix
    if is_archive(archive_name):
        opened = open_archive(archive_name, data)
        report.archives += 1
        for name, reason in opened.skipped:
            report.gap(where + ("!" + name if name else ""), reason)
        for name, content in opened.members:
            inner = where + "!" + name
            _text(report, name, inner + " [member path]", policy, object_id,
                  content_id=hashlib.sha256(data).hexdigest(), context_kind="archive-path")
            _text(report, content.decode("utf-8", errors="replace"), inner, policy, object_id,
                  content_id=hashlib.sha256(data).hexdigest(), context_kind="archive-member")
            if is_image(name):
                _image(report, content, inner, policy, object_id,
                       context_id=hashlib.sha256(data).hexdigest(), context_kind="archive-metadata")
            elif b"\0" in content[:8000] and not is_archive(name):
                report.gap(inner, "binary member: raw strings only")
    elif is_image(where):
        _image(report, data, where, policy, object_id)
    elif b"\0" in data[:8000] or where.lower().endswith((".pdf", ".7z", ".rar")):
        report.gap(where, "encoded/binary content: raw strings only")


def _image(report, data, where, policy, object_id, *, context_id=None, context_kind="metadata"):
    metadata = image_metadata(data)
    if metadata is None:
        report.gap(where, "image metadata format not recognized")
        return
    for reason in metadata.skipped:
        report.gap(where, reason)
    for text in metadata.texts:
        _text(report, text, where + " [metadata]", policy, object_id,
              content_id=context_id or hashlib.sha256(data).hexdigest(), context_kind=context_kind)
    if metadata.gps:
        report.findings.append(Finding("image GPS position", "review", "GPS present", where, object_id,
                                       content_id=context_id or hashlib.sha256(data).hexdigest(), context_kind=context_kind))


def _person(report, name, email, where, policy, object_id):
    _text(report, name + " <" + email + ">", where, policy, object_id, context_kind="identity")
    if email and not email.lower().endswith("@users.noreply.github.com") and email.lower() != "noreply@github.com":
        if not policy.allowed(email, 0, len(email)):
            report.findings.append(Finding("commit identity email", "review", email, where, object_id,
                                           content_id=hashlib.sha256((name + " <" + email + ">").encode("utf-8")).hexdigest(),
                                           context_kind="identity"))


def _tree(report, repo, policy):
    seen = set()
    entries = git_output(repo, ["ls-files", "--stage", "-z"]).split("\0")
    entries += ["100644 - 0\t" + name for name in
                git_output(repo, ["ls-files", "--others", "--exclude-standard", "-z"]).split("\0") if name]
    for entry in entries:
        meta, _, name = entry.partition("\t")
        fields = meta.split()
        if not name or name in seen:
            continue
        seen.add(name)
        first_path_finding = len(report.findings)
        _text(report, name, name + " [path]", policy, content_id="", context_kind="path")
        last_path_finding = len(report.findings)
        if len(fields) != 3 or fields[2] != "0":
            report.gap(name, "unmerged/unreadable index entry")
            continue
        if fields[0] == "160000":
            report.gap(name, "submodule contents not inspected")
            continue
        path = repo / name
        try:
            if any(linked(part)
                   for part in path.parents if part != repo and repo in part.parents):
                report.gap(name, "working-tree parent is a link")
                continue
            if linked(path):
                data = os.readlink(path).encode("utf-8")
            else:
                with path.open("rb") as stream:
                    data = stream.read(MAX_FILE_BYTES + 1)
            if len(data) > MAX_FILE_BYTES:
                report.gap(name, "file exceeds scan size limit")
                continue
        except OSError:
            report.gap(name, "tracked file missing or unreadable")
            continue
        report.files += 1
        path_content = hashlib.sha256(name.encode("utf-8") + b"\0" + data).hexdigest()
        for index in range(first_path_finding, last_path_finding):
            report.findings[index] = replace(report.findings[index], content_id=path_content)
        _bytes(report, data, name, policy)


def _ref_ids(repo):
    states = {}
    for line in git_output(repo, ["for-each-ref", "--format=%(refname)%00%(objectname)"]).splitlines():
        name, _, object_id = line.partition("\0")
        states[name] = object_id
    # Include a detached HEAD, or a checkout whose branch ref was omitted accidentally.
    head = run_git(repo, ["rev-parse", "--verify", "HEAD"])
    if head.returncode == 0:
        states["HEAD"] = head.stdout.strip()
    return states


def _small_blobs(report, repo, versions):
    """Ask sizes before loading bytes; oversized and missing objects remain coverage gaps."""
    ids = sorted(versions)
    expected = {}
    feed = (f"{object_id}\n".encode("ascii") for object_id in ids)
    with stream(["git", "cat-file", "--batch-check"], cwd=repo, timeout=1800, feed=feed) as process:
        for object_id in ids:
            fields = process.stdout.readline().decode("ascii").split()
            if not fields or fields[0] != object_id:
                raise CommandFailed("object size response incomplete or out of order")
            reason = ""
            if len(fields) == 2 and fields[1] == "missing":
                reason = "Git blob missing"
            elif len(fields) != 3 or fields[1] != "blob" or not fields[2].isdigit():
                raise CommandFailed("invalid object size response")
            elif int(fields[2]) > MAX_FILE_BYTES:
                reason = "blob exceeds scan size limit"
            else:
                expected[object_id] = int(fields[2])
            if reason:
                for name in versions[object_id]:
                    report.gap(name, reason)
    for object_id, data in read_blobs(repo, expected):
        if data is None or len(data) != expected[object_id]:
            for name in versions[object_id]:
                report.gap(name, "Git blob missing or truncated")
        else:
            yield object_id, data


def _history_limits(report, repo):
    """Refuse lazy object reads and record ancestry gaps before inspecting history."""
    promisor = run_git(repo, ["config", "--get-regexp", r"^remote\..*\.promisor$"])
    if promisor.returncode not in (0, 1):
        raise CommandFailed("cannot determine partial-clone status")
    if any(line.split()[-1].lower() in {"true", "yes", "1", "on"} for line in promisor.stdout.splitlines()):
        report.gap("history", "partial clone: scan refused to avoid automatic object downloads")
        return False
    if git_output(repo, ["rev-parse", "--is-shallow-repository"]).strip() == "true":
        report.gap("history", "shallow repository: earlier history not available")
    if git_output(repo, ["for-each-ref", "--format=%(refname)", "refs/replace/"]).strip():
        report.gap("history", "replacement refs may hide original objects")
    grafts = Path(git_output(repo, ["rev-parse", "--git-path", "info/grafts"]).strip())
    if (grafts if grafts.is_absolute() else repo / grafts).exists():
        report.gap("history", "legacy grafts may hide original ancestry")
    return True


def _history(report, repo, policy, refs):
    states = _ref_ids(repo)
    selected = list(states) if refs == ["--all"] else list(refs)
    if any(ref not in states for ref in selected):
        raise ValueError("select an existing full ref name or HEAD")
    report.refs = {ref: states[ref] for ref in selected}
    if not selected:
        raise ValueError("no commit refs to scan")
    if not _history_limits(report, repo):
        return
    tips, direct = [], {}
    for ref, object_id in report.refs.items():
        _text(report, ref, ref + " [ref name]", policy, object_id, context_kind="ref")
        current, visited = object_id, set()
        kind = git_output(repo, ["cat-file", "-t", current]).strip()
        while kind == "tag" and current not in visited:
            visited.add(current)
            raw = git_output(repo, ["cat-file", "tag", current])
            _text(report, raw, ref + " [tag object]", policy, current, context_kind="tag")
            match = re.search(r"^tagger (.*?) <([^>]*)>", raw, re.M)
            if match:
                _person(report, match[1], match[2], ref + " [tagger]", policy, current)
            current = raw.splitlines()[0].removeprefix("object ")
            kind = git_output(repo, ["cat-file", "-t", current]).strip()
        if kind == "tree":
            for name, blob in files_at(repo, current).items():
                direct.setdefault(blob, set()).add(name)
            listing = git_output(repo, ["ls-tree", "-r", current])
            if any(line.startswith("160000 ") for line in listing.splitlines()):
                report.gap(ref, "submodule payloads not inspected")
        elif kind == "blob":
            direct.setdefault(current, set()).add(ref + " [blob ref]")
        elif kind != "commit":
            report.gap(ref, "unsupported ref target type")
        elif current not in tips:
            tips.append(current)
    _history_versions(report, repo, policy, tips, direct)
    after = _ref_ids(repo)
    if (after != states if refs == ["--all"] else any(after.get(ref) != states[ref] for ref in selected)):
        report.gap("refs", "references changed during scan; rerun required")


def _history_versions(report, repo, policy, tips, direct=None):
    """Inspect each changed blob/path, raw commit identity/message and new gitlink in a range."""
    versions = file_versions(repo, tips) if tips else {}
    direct = direct or {}
    for blob, paths in direct.items():
        versions.setdefault(blob, set()).update(paths)
    path_findings = {}
    for object_id, paths in versions.items():
        for name in sorted(paths):
            first = len(report.findings)
            _text(report, name, name + " [path]", policy, object_id, content_id="", context_kind="path")
            path_findings[object_id, name] = (first, len(report.findings))
    for object_id, data in _small_blobs(report, repo, versions):
        paths = versions[object_id]
        for name in sorted(paths):
            report.files += 1
            first, last = path_findings[object_id, name]
            path_content = hashlib.sha256(name.encode("utf-8") + b"\0" + data).hexdigest()
            for index in range(first, last):
                report.findings[index] = replace(report.findings[index], content_id=path_content)
            _bytes(report, data, name, policy, object_id)
    for commit in commits(repo, tips) if tips else []:
        report.commits += 1
        _text(report, commit.message, "commit message", policy, commit.id, context_kind="message")
        for role, person in (("author", commit.author), ("committer", commit.committer)):
            _person(report, person.name, person.email, role, policy, commit.id)
    # Includes submodules removed in later commits, not just those at the current tips.
    raw = (git_output(repo, ["-c", "log.showSignature=false", "log", "--no-use-mailmap", "--format=",
                             "--raw", "-z", "-m", "--root", "--no-renames", *tips]) if tips else "")
    parts = raw.split("\0")
    for index, part in enumerate(parts[:-1]):
        fields = part.strip().split()
        if part.strip().startswith(":") and len(fields) >= 5 and fields[1] == "160000":
            report.gap(parts[index + 1], "historical submodule payload not inspected")


def _index(report, repo, policy):
    """Read staged changed-file bytes only, without filters, working files or index writes."""
    change_args = ["diff", "--cached", "--no-ext-diff", "--no-textconv", "--name-only", "--no-renames", "--diff-filter=ACMTU", "-z"]
    changes = git_output(repo, change_args)
    names = set(changes.split("\0")) - {""}
    entries = git_output(repo, ["ls-files", "--stage", "-z"])
    versions = {}
    for entry in entries.split("\0"):
        meta, _, name = entry.partition("\t")
        if name not in names:
            continue
        fields = meta.split()
        if len(fields) != 3 or fields[2] != "0":
            report.gap(name, "unmerged/unreadable index entry")
        elif fields[0] == "160000":
            report.gap(name, "submodule contents not inspected")
        else:
            versions.setdefault(fields[1], set()).add(name)
    _history_versions(report, repo, policy, [], direct=versions)
    if entries != git_output(repo, ["ls-files", "--stage", "-z"]) or changes != git_output(repo, change_args):
        report.gap("index", "staged scope changed during inspection; rerun")


def _outgoing(report, repo, policy, refs):
    """Exact immutable base..tip material, including introduce-then-remove and merges."""
    if (len(refs) != 2 or any(not isinstance(ref, str) or
                            re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", ref) is None for ref in refs)):
        raise ValueError("outgoing scans require two full commit object ids")
    base, tip = refs
    report.refs = {"base": base, "tip": tip}
    if not _history_limits(report, repo):
        return
    for object_id in refs:
        if git_output(repo, ["cat-file", "-t", object_id]).strip() != "commit":
            raise ValueError("outgoing endpoints must be commits")
    ancestry = run_git(repo, ["merge-base", "--is-ancestor", base, tip])
    if ancestry.returncode != 0:
        report.gap("outgoing", "destination is not an available ancestor; push needs review")
        return
    _history_versions(report, repo, policy, [f"{base}..{tip}"])


def _proposed(report, policy, proposal):
    """Named proposed bytes plus message/identities; None content represents a deletion.

    Files are streamed as (relative name, bytes-or-None, optional gap reason). The caller owns
    safe path/index selection; no other working-tree or staged contents are read here.
    """
    for name, data, reason in proposal["files"]:
        if reason:
            report.gap(name, reason)
            continue
        if data is None:
            continue
        _text(report, name, name + " [path]", policy,
              content_id=hashlib.sha256(name.encode("utf-8") + b"\0" + data).hexdigest(), context_kind="path")
        report.files += 1
        _bytes(report, data, name, policy)
    _text(report, proposal["message"], "proposed commit message", policy, context_kind="message")
    for role in ("author", "committer"):
        identity = proposal["identities"].get(role)
        if identity is None:
            report.gap(role, "proposed identity could not be determined")
        else:
            _person(report, *identity, "proposed " + role, policy, "")


def scan(repo: Path, policy, *, material="tree", refs=None, engines=None, executables=None,
         reference_names=(), proposal=None):
    """Scan selected material with built-in checks and explicitly selected optional engines.

    None uses policy.engines; an empty list disables external engines for this invocation.
    Missing/failed selected integrations are coverage gaps. No source files or settings change.
    """
    repo = Path(repo).resolve()
    report = Report(str(repo), material, policy=policy.summary(), gaps=list(policy.gaps),
                    private_values=tuple(value for values in policy.identities.values() for value in values
                                         if not policy.allowed(value, 0, len(value))))
    runner = EngineBatch(report, policy, policy.engines if engines is None else engines,
                         executables=executables)
    report._engine_runner = runner
    try:
        for name in reference_names:
            _text(report, name, "publication ref", policy, context_kind="ref")
        if material == "tree":
            _tree(report, repo, policy)
        elif material == "index":
            _index(report, repo, policy)
        elif material == "history":
            _history(report, repo, policy, list(refs or ["--all"]))
        elif material == "outgoing":
            _outgoing(report, repo, policy, list(refs or ()))
        elif material == "proposed":
            _proposed(report, policy, proposal)
        else:
            raise ValueError("unknown material selection")
    except (CommandFailed, OSError, ValueError) as exc:
        report.gap("scan", type(exc).__name__ + ": Git/material read failed")
    finally:
        try:
            runner.finish()
        finally:
            del report._engine_runner
    _reviews.apply(report, policy)
    return report
