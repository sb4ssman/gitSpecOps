"""One identity/safe-value policy for file content, paths and metadata."""
import re

from Special._security._findings import Finding


def check(text, where, policy, object_id=""):
    for kind, values in policy.identities.items():
        for value in sorted(set(values)):
            if not value or (kind in {"configured name", "machine name"} and
                            (len(value) < 4 or value.lower() in {"user", "admin", "root", "home", "test", "runner", "localhost", "main", "github"})):
                continue
            edge = "A-Za-z0-9_" if kind == "never-publish-word" else "A-Za-z0-9"
            pattern = re.compile(rf"(?i)(?<![{edge}]){re.escape(value)}(?![{edge}])")
            name = "never-publish" if kind == "never-publish-word" else kind
            for match in pattern.finditer(text):
                if name == "never-publish" or not policy.allowed(text, *match.span()):
                    yield Finding(name, "leak", match[0], where, object_id,
                                  text.count("\n", 0, match.start()) + 1)
