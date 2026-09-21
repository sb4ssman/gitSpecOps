"""Remote URL parsing: every common shape, plus the inputs that must not parse.

Formerly the built-in self-test of `shared/remote_identity.py`, which only ran when someone
invoked that module by hand. Here it runs with the suite.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _bootstrap import setup  # noqa: E402

setup()

from Basic._identity import normalize_owner_name, parse_remote_url  # noqa: E402

CASES = [
    ("https://github.com/Owner/Repo.git", ("github.com", "Owner", "Repo"), "owner/repo"),
    ("https://github.com/Owner/Repo", ("github.com", "Owner", "Repo"), "owner/repo"),
    ("git@github.com:owner/repo.git", ("github.com", "owner", "repo"), "owner/repo"),
    ("ssh://git@github.com/owner/repo.git", ("github.com", "owner", "repo"), "owner/repo"),
    ("https://user@bitbucket.org/team/repo", ("bitbucket.org", "team", "repo"), "team/repo"),
    ("https://gitlab.com/group/sub/repo.git", ("gitlab.com", "group", "repo"), "group/repo"),
    ("/only/a/local/path", None, None),
    ("https://host/only-one", None, None),
    ("", None, None),
    (None, None, None),
]

failures: list[str] = []
for url, want_parse, want_norm in CASES:
    got_parse = parse_remote_url(url)
    got_norm = normalize_owner_name(url)
    if got_parse != want_parse:
        failures.append(f"parse_remote_url({url!r}): got {got_parse!r}, want {want_parse!r}")
    if got_norm != want_norm:
        failures.append(f"normalize_owner_name({url!r}): got {got_norm!r}, want {want_norm!r}")

if failures:
    print("FAIL:")
    for failure in failures:
        print(f"  - {failure}")
    raise SystemExit(1)
print(f"ALL-IDENTITY-TESTS-PASS ({len(CASES)} cases)")
