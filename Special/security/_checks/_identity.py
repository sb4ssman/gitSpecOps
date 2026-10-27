"""One identity/safe-value policy for file content, paths and metadata."""
import re

from Special.security._findings import Finding


def check(text, where, policy, object_id=""):
    for kind, values in policy.identities.items():
        for value in sorted(set(values)):
            if not value or (kind in {"configured name", "machine name"} and
                            (len(value) < 4 or value.lower() in {"user", "admin", "root", "home", "test", "runner", "localhost", "main", "github"})):
                continue
            pattern = re.compile(rf"(?i)(?<![A-Za-z0-9]){re.escape(value)}(?![A-Za-z0-9])")
            for match in pattern.finditer(text):
                if not policy.allowed(text, *match.span()):
                    yield Finding(kind, "leak", match[0], where, object_id,
                                  text.count("\n", 0, match.start()) + 1)
