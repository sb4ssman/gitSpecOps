"""
remote_identity
===============

SHARED SPECIAL OPERATION (read-only): parse any common Git remote URL into a canonical
identity. Pure string logic — no git, no network, no filesystem.

Shared rule: a method lives in `shared/` once two of the three special operations
(archive updater, org duplicator, sync suggester) need it. Stdlib only; no imports from
tool folders; no policy.

Standalone:

    python shared/remote_identity.py <url> [<url> ...]      # parse URLs
    python shared/remote_identity.py                        # built-in self-test
"""

from __future__ import annotations

import sys
from dataclasses import dataclass


def parse_remote_url(url: str | None) -> tuple[str, str, str] | None:
    """Parse any common git remote URL into (host, owner, name), host-agnostic.

    Handles:
        https://host/owner/.../name(.git)
        git@host:owner/.../name(.git)
        ssh://git@host/owner/.../name(.git)
    For nested namespaces (e.g. GitLab groups) the first path segment is the owner and
    the last is the name; the middle is ignored for identity purposes.
    Returns None when the URL is not a recognizable git remote.
    """
    if not url:
        return None
    text = url.strip()
    host = ""
    if text.startswith("git@"):
        # git@host:owner/name
        rest = text[len("git@"):]
        host, _, path = rest.partition(":")
    elif "://" in text:
        # scheme://[user@]host/owner/name
        _scheme, _, rest = text.partition("://")
        if "@" in rest.split("/", 1)[0]:
            rest = rest.split("@", 1)[1]
        host, _, path = rest.partition("/")
    else:
        return None
    if not host or not path:
        return None
    path = path.rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    segments = [seg for seg in path.split("/") if seg]
    if len(segments) < 2:
        return None
    owner, name = segments[0], segments[-1]
    return host.lower(), owner, name


def remote_host(url: str | None) -> str | None:
    """The host of a git remote URL, or None."""
    parsed = parse_remote_url(url)
    return parsed[0] if parsed else None


def normalize_owner_name(url: str | None) -> str | None:
    """Lowercased 'owner/name' from any common git URL, host-agnostic. None if unparseable."""
    if not url:
        return None
    text = url.strip()
    if text.startswith("git@"):
        _, _, path = text[len("git@"):].partition(":")
    elif "://" in text:
        _, _, rest = text.partition("://")
        if "@" in rest.split("/", 1)[0]:
            rest = rest.split("@", 1)[1]
        _, _, path = rest.partition("/")
    else:
        return None
    path = path.rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    segments = [s for s in path.split("/") if s]
    if len(segments) < 2:
        return None
    return f"{segments[0].lower()}/{segments[-1].lower()}"


@dataclass
class RepoRef:
    """A remote repository, as reported by a provider. `id` is a provider-stable identity
    that survives repo and namespace (owner/org/group) renames."""
    id: str
    owner: str
    name: str
    url: str
    host: str = "github.com"
    private: bool = False
    fork: bool = False
    archived: bool = False


def _self_test() -> int:
    cases = [
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
    for url, want_parse, want_norm in cases:
        got_parse = parse_remote_url(url)
        got_norm = normalize_owner_name(url)
        if got_parse != want_parse:
            failures.append(f"parse_remote_url({url!r}): got {got_parse!r}, want {want_parse!r}")
        if got_norm != want_norm:
            failures.append(f"normalize_owner_name({url!r}): got {got_norm!r}, want {want_norm!r}")
    if failures:
        print("SELF-TEST FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("remote_identity self-test passed.")
    return 0


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if not argv:
        return _self_test()
    for url in argv:
        parsed = parse_remote_url(url)
        if parsed is None:
            print(f"{url!r}: not a recognizable git remote")
        else:
            host, owner, name = parsed
            print(f"{url!r}: host={host} owner={owner} name={name} owner/name={normalize_owner_name(url)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
