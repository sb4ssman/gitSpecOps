"""Generic personal shapes are context; exact private values are checked separately."""
import re

from Special.security._findings import Finding

RULES = {
    "local path": re.compile(r"(?i)[A-Z]:\\(?:Users\\[^\\\s\"']+|Github\b|Projects\b)|/(?:home|Users)/[^/\s\"']+"),
    "tailnet address": re.compile(r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"),
    "email address": re.compile(r"(?i)(?<![\w.+-])[A-Z0-9_.+-]{1,64}@[A-Z0-9-]{1,63}(?:\.[A-Z0-9-]{1,63})*\.[A-Z]{2,63}\b"),
}
LEAK_WORDS = re.compile(r"(?i)\b(?:leak|purge|scrub|still served|support ticket)\b")
COMMIT_ID = re.compile(r"(?<![A-Za-z0-9])[0-9a-f]{7,40}(?![A-Za-z0-9])")


def check(text, where, policy, object_id=""):
    for name, pattern in RULES.items():
        for match in pattern.finditer(text):
            if name == "email address" and (match[0].lower().endswith("@users.noreply.github.com") or
                                             match[0].lower() == "noreply@github.com"):
                continue
            if name == "email address":
                domain = match[0].lower().split("@", 1)[1]
                if domain.endswith((".test", ".invalid", ".example")) or domain in {"example.com", "example.org", "example.net"}:
                    continue  # Reserved documentation domains; explicit watch values still flag.
            if not policy.allowed(text, *match.span()):
                yield Finding(name, "quiet" if name == "local path" else "review", match[0],
                              where, object_id, text.count("\n", 0, match.start()) + 1)
    for match in LEAK_WORDS.finditer(text):
        nearby = text[max(0, match.start()-160):match.end()+160]
        if COMMIT_ID.search(nearby) and not policy.allowed(text, *match.span()):
            yield Finding("leak-description near commit id", "review", match[0], where,
                          object_id, text.count("\n", 0, match.start()) + 1)
