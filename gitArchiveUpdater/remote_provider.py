"""
remote_provider
===============

The seam that keeps the tool cross-git. Discovery of "what repos exist remotely" is
host-specific (GitHub via `gh`, GitLab via `glab`, etc.). Updating existing clones is NOT
host-specific and lives elsewhere. This module defines the provider contract and a registry
that picks a provider from a remote host. Unknown host -> None -> the archive degrades to
host-agnostic update-only, which is exactly the "loose archive" behavior.

A provider produces `RepoRef` objects (defined in archive_diff, the pure layer). The two
operations every provider must offer:

    list_repos(owner)   -> the authoritative set for a namespace
    resolve(repo_spec)  -> follow renames/redirects to a stable id + canonical owner/name

`resolve` is what survives namespace renames: listing the OLD owner 404s, but resolving any
one repo under the old path redirects and reveals the new canonical owner.
"""

from __future__ import annotations

from typing import Protocol

try:
    from .archive_diff import RepoRef
    from .git_inspect import remote_host
except ImportError:
    from archive_diff import RepoRef
    from git_inspect import remote_host


class RemoteProvider(Protocol):
    name: str

    def list_repos(self, owner: str) -> tuple[list[RepoRef] | None, str | None]:
        """Authoritative repos for a namespace. Returns (repos, error)."""
        ...

    def resolve(self, repo_spec: str) -> tuple[RepoRef | None, str | None]:
        """Resolve an owner/name or URL to a canonical RepoRef, following renames. (ref, error)."""
        ...


# host substring -> factory. Kept tiny and explicit; add providers here.
def provider_for(remote_url: str | None) -> RemoteProvider | None:
    """Pick a provider for a remote URL by host, or None if no provider handles it."""
    host = remote_host(remote_url)
    if not host:
        return None
    if host == "github.com" or host.endswith(".github.com"):
        # Lazy import avoids a circular dependency (provider imports RepoRef from here's deps).
        try:
            from .provider_github import GitHubProvider
        except ImportError:
            from provider_github import GitHubProvider
        return GitHubProvider()
    # gitlab / gitea / bitbucket / self-hosted: not implemented yet -> update-only.
    return None
