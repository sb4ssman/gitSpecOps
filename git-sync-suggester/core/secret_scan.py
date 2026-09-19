"""Credential screening for recovery snapshots.

This control became load-bearing when snapshots were settled as unencrypted (see
`docs/RECOVERY-DESIGN.md`). That is not a downgrade: encryption never addressed the realistic
harm here. The danger is not a stranger reading the sync folder -- it is a live credential
sitting in an uncommitted file, replicated to every machine in the fleet and restored later,
long after it should have been rotated. Ciphertext would have propagated that just as faithfully.

Rules that make the difference between a useful screen and a harmful one:

**Screen what the snapshot introduces.** For patches that is the lines a file section *adds*;
context and removed lines are already in the committed base, so flagging them would refuse a
snapshot for rotating a secret *out*. Carried untracked files are screened whole.

**A match refuses the whole snapshot.** It is never downgraded to a warning, because the user is
not present at capture time to make that call.

**A finding reports the path and the rule, never the matched text.** A refusal message is
written to logs and to the dashboard; copying the secret into it would be the same mistake in a
different place.

**Allowance is by path, and narrow.** `allow_paths` lets a user deliberately carry one file --
their own `.env`, say -- while everything else stays screened. Switching protection off entirely
is a separate, local, recorded choice made in `capture.CapturePolicy`, not here.

Pattern matching is best effort and cannot prove a secret is absent, and binary content cannot
be pattern-screened at all. It is one control among explicit enrollment, exclusions and limits.
"""
from __future__ import annotations

import base64
import binascii
import re

from patch_parse import PatchUnreadable, parse_patch

# Each rule is (name, compiled pattern). Patterns match the *shape* of a credential, which is
# why they are anchored on distinctive prefixes and lengths rather than on the word "secret".
RULES = (
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("Stripe secret key", re.compile(r"\b[sr]k_(?:live|test)_[0-9A-Za-z]{16,}\b")),
    ("OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    ("JSON Web Token", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\."
                                  r"[A-Za-z0-9_\-]{10,}\b")),
    ("PuTTY private key", re.compile(r"PuTTY-User-Key-File-\d")),
    ("assigned credential", re.compile(
        r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|client[_-]?secret)\b"
        r"\s*[:=]\s*[\"']?(?!\s*$)(?!(?:changeme|example|placeholder|your[_-]|<|\$\{|%\()"
        r")[^\s\"']{8,}")),
)


def findings_in_text(text: str, where: str, allow=()) -> list[str]:
    """`rule in where` for each rule that matches. Never includes the matched value."""
    found = []
    for name, pattern in RULES:
        if name in allow:
            continue
        if pattern.search(text):
            found.append(f"{name} in {where}")
    return found


def scan_bundle(bundle, allow=(), allow_paths=()) -> list[str]:
    """Screen a `capture.Bundle` before it is written anywhere. Returns findings; empty is clean.

    `allow` names rules to skip; `allow_paths` names repository-relative paths to skip.
    """
    allowed = set(allow_paths)
    found = []
    for label, patch in (("staged changes", bundle.staged_patch),
                         ("unstaged changes", bundle.unstaged_patch)):
        try:
            entries = parse_patch(patch)
        except PatchUnreadable:
            # Unscreened content is not captured.
            found.append(f"unreadable patch in {label}, so it could not be screened")
            continue
        for entry in entries:
            if entry["path"] in allowed or entry["binary"]:
                continue
            where = f"{entry['path'] or 'an unnamed file'} ({label})"
            found.extend(findings_in_text("\n".join(entry["added"]), where, allow))
    for item in bundle.files:
        if item.get("path") in allowed:
            continue
        try:
            content = base64.b64decode(item["content_base64"], validate=True)
        except (binascii.Error, ValueError, KeyError, TypeError):
            # Unreadable content cannot be screened, and unscreened content is not captured.
            found.append(f"unreadable content in {item.get('path', 'a selected file')}")
            continue
        found.extend(findings_in_text(content.decode("utf-8", errors="replace"),
                                      item["path"], allow))
    return found
