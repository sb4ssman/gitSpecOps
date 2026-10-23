"""Parse any common Git remote URL into a canonical host/owner/name. Pure string logic.

No git, no network, no filesystem, no policy. Host-agnostic on purpose: which host a URL names
is a fact; what to do about that host belongs to `Basic/_providers/`.
"""

from __future__ import annotations

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
