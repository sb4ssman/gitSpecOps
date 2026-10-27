"""Offline credential candidates; dedicated external scanning remains a separate check."""
import re

from Special.security._findings import Finding

RULES = {
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----\s*(?:[A-Za-z-]+:[^\n]*\n\s*)*[A-Za-z0-9+/=]{40}"),
    "assigned credential": re.compile(r"(?i)\b(?:password|passwd|secret|token|api[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]\s*[\"']([^\"'\s]{8,})[\"']"),
    "URL credential": re.compile(r"(?i)\b(?:https?|ftp)://[^/\s:@]+:([^/@\s]+)@"),
    "64-hex candidate": re.compile(r"\b[0-9a-f]{64}\b", re.I),
}


def check(text, where, policy, object_id=""):
    for name, pattern in RULES.items():
        for match in pattern.finditer(text):
            start, end = match.span(1) if name in {"assigned credential", "URL credential"} else match.span()
            value = text[start:end]
            if name == "64-hex candidate" and (len(set(value.lower())) < 10 or
                    re.search(r"(?i)(?:sha-?256|checksum|digest|integrity|hash)\W{0,6}$", text[max(0,start-24):start])):
                continue
            if name == "assigned credential" and re.search(r"(?i)^(?:sample|example|dummy|placeholder|changeme|fake|redacted|xxxx|<|\$\{)", value):
                continue
            if not policy.allowed(text, start, end):
                yield Finding(name, "candidate", value, where, object_id, text.count("\n", 0, start) + 1)
