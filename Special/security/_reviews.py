"""Content-bound local example reviews, stored privately and applied by the common scanner.

Only uncertain built-in candidates can be accepted. Prohibited identities, strong credentials,
external-engine findings and coverage gaps cannot be waived here. Decisions bind one repo,
check, location, line, value and complete checked text; raw bindings/reasons never print.
Immutable decision/revocation records live under the selected profile, not beside source.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from Special.security._private_files import _unlinked, private_path, read_private_json

REVIEWABLE = frozenset({"email address", "tailnet address", "assigned credential", "URL credential",
                       "leak-description near commit id", "commit identity email", "image GPS position"})
REVIEW_ID = re.compile(r"review-[0-9a-f]{32}")
CONTENT_ID = re.compile(r"[0-9a-f]{64}")
CONTEXT_KINDS = frozenset({"content", "path", "archive-path", "archive-member", "metadata",
                           "archive-metadata", "identity", "message", "ref", "tag"})


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def repository_scope(repo):
    return os.path.normcase(os.path.abspath(repo)).replace("\\", "/")


def directory(home, repo):
    return Path(home) / "security" / "reviews" / digest(repository_scope(repo))


def evidence(repo, finding):
    """Private binding usable across tree/proposed/outgoing scans of identical content."""
    if (finding.check not in REVIEWABLE or finding.classification not in ("candidate", "review") or
            finding.severity == "high" or not CONTENT_ID.fullmatch(finding.content_id)):
        raise ValueError("this finding cannot be accepted as an example")
    binding = {"repository": repository_scope(repo), "check": finding.check,
               "classification": finding.classification, "where": finding.where,
               "line": finding.line, "value": finding.value, "content_id": finding.content_id,
               "context_kind": finding.context_kind, "occurrence": finding.occurrence,
               "object_id": finding.object_id if finding.context_kind in {"identity", "message", "ref", "tag"} else ""}
    _validate_binding(binding, repo)
    return binding


def _validate_binding(binding, repo):
    if (not isinstance(binding, dict) or set(binding) != {"repository", "check", "classification", "where", "line", "value", "content_id", "context_kind", "occurrence", "object_id"} or
            binding["repository"] != repository_scope(repo) or not isinstance(binding["check"], str) or binding["check"] not in REVIEWABLE or
            binding["classification"] not in ("candidate", "review") or
            type(binding["line"]) is not int or binding["line"] < 0 or
            type(binding["occurrence"]) is not int or binding["occurrence"] < 1 or
            not isinstance(binding["context_kind"], str) or binding["context_kind"] not in CONTEXT_KINDS or
            not isinstance(binding["object_id"], str) or
            (binding["object_id"] and not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", binding["object_id"])) or
            any(not isinstance(binding[key], str) or not binding[key] or len(binding[key]) > 65536
                for key in ("where", "value", "content_id")) or not CONTENT_ID.fullmatch(binding["content_id"])):
        raise ValueError("invalid review binding")


def load(home, repo, *, configured=False):
    """Read one repo's bounded immutable records. Corrupt/unreadable state never disappears."""
    folder = directory(home, repo)
    _unlinked(folder)
    try:
        info = folder.lstat()
    except FileNotFoundError:
        return {}, digest([])
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("review storage is not a directory")
    private_path(folder / "probe.json")
    files = []
    for path in folder.iterdir():
        files.append(path)
        if len(files) > 10000:
            raise ValueError("too many review records")
    records, revoked, total = [], set(), 0
    for path in sorted(files):
        record = read_private_json(path, limit=256 * 1024)
        total += len(json.dumps(record, ensure_ascii=True).encode("utf-8"))
        if total > 32 * 1024 * 1024:
            raise ValueError("review records exceed the aggregate size limit")
        if (not isinstance(record, dict) or type(record.get("schema_version")) is not int or record.get("schema_version") != 1 or
                record.get("repository") != repository_scope(repo) or
                type(record.get("requires_settings")) is not bool or (record["requires_settings"] and not configured) or
                not isinstance(record.get("created_at"), str) or not record["created_at"].endswith("+00:00") or
                not isinstance(record.get("review_id"), str) or not REVIEW_ID.fullmatch(record["review_id"]) or
                not isinstance(record.get("reason"), str) or not record["reason"].strip() or len(record["reason"]) > 2000):
            raise ValueError("invalid private review record")
        datetime.fromisoformat(record["created_at"])
        if record.get("decision") == "accept-example":
            if set(record) != {"schema_version", "repository", "requires_settings", "created_at", "review_id", "reason", "decision", "evidence", "source_scan"} or path.name != record["review_id"] + ".json":
                raise ValueError("invalid example review record")
            _validate_binding(record["evidence"], repo)
            if not isinstance(record["source_scan"], str) or not re.fullmatch(r"scan-[0-9a-f]{32}", record["source_scan"]):
                raise ValueError("invalid review source")
        elif record.get("decision") == "revoke":
            if set(record) != {"schema_version", "repository", "requires_settings", "created_at", "review_id", "reason", "decision"} or path.name != record["review_id"] + ".revoke.json":
                raise ValueError("invalid review revocation")
            revoked.add(record["review_id"])
        else:
            raise ValueError("unknown review decision")
        records.append((path.name, record))
    accepted = {}
    for _, record in records:
        if record["decision"] == "accept-example" and record["review_id"] not in revoked:
            key = digest(record["evidence"])
            if key in accepted:
                raise ValueError("duplicate active example reviews require repair")
            accepted[key] = record["review_id"]
    return accepted, digest(records)


def apply(report, policy):
    """Annotate accepted examples without removing findings or altering any coverage gaps."""
    accepted = getattr(policy, "reviewed_examples", {})
    occurrences = {}
    for index, finding in enumerate(report.findings):
        key = (finding.check, finding.classification, finding.where, finding.line, finding.value,
               finding.content_id, finding.context_kind, finding.object_id if finding.context_kind in {"identity", "message", "ref", "tag"} else "")
        occurrences[key] = occurrences.get(key, 0) + 1
        finding = replace(finding, review_id="", occurrence=occurrences[key])
        report.findings[index] = finding
        try:
            review_id = accepted.get(digest(evidence(report.repository, finding)))
        except ValueError:
            continue
        if review_id:
            report.findings[index] = replace(finding, review_id=review_id)
