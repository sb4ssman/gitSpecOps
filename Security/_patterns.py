"""What must never be published, and how to find it. Pure: no git, no files, no network.

One set of rules for every scanner: the repository's own hygiene test, `scan_tree`,
`scan_history` and the rewrite planner all match with these, so "is this a leak?" can never
get two answers.

Three families:

- **Secrets** -- shapes of credentials. A secret found anywhere must be *rotated*, whatever else
  is done; removing it from a file does not un-publish it.
- **Personal shapes** -- local paths and tailnet addresses, recognizable without knowing whose.
- **Identity** -- the person's own values (email, login, machine names, organizations), which
  no pattern can know in advance. They are supplied at run time (see `_seeds.py`), held only in
  memory, and reported by *kind*, never by value, unless the person asks to see them.

`ALLOWED` is tested against **the matched text only**. Until 2026-10-19 it was also tested
against the whole line, so anything allowed anywhere on a line -- any HTML tag, via the
placeholder entry -- excused a real path, address or token beside it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

SECRETS = {
    "a 64-hex value (the fleet-secret shape)": re.compile(r"\b[0-9a-f]{64}\b"),
    "a GitHub token": re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "an AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    # A header with a key after it (optional `Proc-Type:` lines, then base64). A header alone --
    # a scanner's own test string, a document about keys -- holds nothing to steal.
    "a private key block": re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----\s*(?:[A-Za-z-]+:[^\n]*\n\s*)*[A-Za-z0-9+/=]{40}"),
    "an assigned credential": re.compile(
        r"(?i)\b(password|passwd|secret|api_?key|token)\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']"),
}

PERSONAL = {
    # The account segment must look like a name, so the documented shape `C:\Users\…` is not one.
    "a Windows user path": re.compile(r"(?i)[A-Z]:\\Users\\[\w.$-]{2,}"),
    "a Windows drive path": re.compile(r"(?i)\b[D-Z]:\\(?:Github|Users|Projects)\b"),
    # /home/linuxbrew is Homebrew's documented prefix on Linux, the same on every machine.
    "a POSIX home path": re.compile(r"/home/(?!u/|someone/|linuxbrew(?![a-z0-9._-]))"
                                    r"[a-z0-9._-]{2,}"),
    "a real Tailscale address": re.compile(
        r"\b100\.(?:6[5-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"),
}

#: Values that look like findings but are documentation or invented data. Every entry is an
#: explicit decision, not a convenience.
ALLOWED = re.compile(
    r"""(?ix)
    example\.(com|test|org)     # reserved documentation domains
  | <[a-z-]+>                   # an intentional placeholder
    """)

#: Identity values too generic to scan for without drowning in noise.
GENERIC_IDENTITIES = frozenset({"user", "admin", "root", "home", "test", "runner", "localhost",
                                "owner", "main", "master", "local", "github"})
MIN_IDENTITY_LENGTH = 4


@dataclass(frozen=True)
class Finding:
    kind: str
    value: str
    start: int


#: What precedes a published checksum: `sha256:` in a uv.lock, `"sha256": "` in a download
#: manifest, `--hash=sha256:` in pip, `integrity` in npm. Hundreds per lockfile; never secrets.
_CHECKSUM_CONTEXT = re.compile(r"(?i)(sha-?256|checksum|digest|integrity|hash)\W{0,6}$")
#: Words that mark an assigned credential as a test fixture or a documentation example.
_FIXTURE_WORDS = re.compile(r"(?i)sample|example|dummy|placeholder|changeme|fake|redacted|xxxx")


def _random_hex(text: str, match) -> bool:
    # A random 64-hex secret uses nearly all sixteen digits; a run like `bbbbccccbbaa...`
    # (bitmap rows, padding in a game file) is data, not a key.
    return (len(set(match.group(0))) >= 10
            and not _CHECKSUM_CONTEXT.search(text[max(0, match.start() - 24):match.start()]))


#: Second opinions on a match, given the text around it: False drops the match.
_PLAUSIBLE = {
    "a 64-hex value (the fleet-secret shape)": _random_hex,
    "an assigned credential": lambda text, match: not _FIXTURE_WORDS.search(match.group(0)),
}


def find(text: str, patterns: dict) -> list[Finding]:
    """Every match of every pattern in `text`, unless the matched text itself is allowed."""
    found = []
    for kind, pattern in patterns.items():
        plausible = _PLAUSIBLE.get(kind)
        for match in pattern.finditer(text):
            value = match.group(0)
            if not ALLOWED.search(value) and (plausible is None or plausible(text, match)):
                found.append(Finding(kind, value, match.start()))
    return found


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def usable_identity(value: str) -> bool:
    value = (value or "").strip()
    return len(value) >= MIN_IDENTITY_LENGTH and value.lower() not in GENERIC_IDENTITIES


def identity_patterns(seeds: dict[str, list[str]], public_repositories=()) -> dict:
    """One case-insensitive pattern per kind of identity, matching whole values only.

    "Whole" means not inside a longer run of letters and digits. Punctuation does not shield a
    value: `runs/__private-org.txt` and `x-private-org` still name it (until 2026-10-19 an
    underscore or hyphen beside a value hid it from every scan).

    `public_repositories` names repositories whose `<owner>/<name>` is the project's public
    identity (a clone URL, a release slug): the owner is excused right there and nowhere else,
    so `<owner>/<name>-state` -- a private repository's name -- is still a finding.
    """
    public = "|".join(re.escape(name) for name in public_repositories)
    excuse = rf"(?!/(?:{public})(?![\w-]))" if public else ""
    patterns = {}
    for kind, values in seeds.items():
        usable = sorted({v.strip() for v in values if usable_identity(v)}, key=len, reverse=True)
        if usable:
            alternatives = "|".join(re.escape(v) for v in usable)
            patterns[kind] = re.compile(
                rf"(?i)(?<![A-Za-z0-9])(?:{alternatives})(?![A-Za-z0-9]){excuse}")
    return patterns


def mask(value: str) -> str:
    """Enough to recognize a value you already know, too little to learn one you do not."""
    value = value.strip()
    if "@" in value:
        local, _, domain = value.partition("@")
        return f"{local[:1]}***@{domain[:1]}***.{domain.rsplit('.', 1)[-1]}"
    if len(value) <= 6:
        return value[:1] + "***"
    return value[:3] + "***" + value[-2:]
