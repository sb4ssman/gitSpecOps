"""
providers
=========

SHARED PROVIDER PLUMBING: the cross-git seam resolver. Maps a remote host to a provider
object that answers "what repos exist under this owner" and "what is the canonical
identity of this repo" (following renames). Hosts live behind this contract so the
special operations stay host-neutral, and an unknown host degrades gracefully.

Providers themselves live with the tools that bring them (e.g. the GitHub provider in
git-archive-updater) and REGISTER here at import time -- shared never imports tool
folders. Adding a host = one provider module + one register_provider() call.

Auth is NOT managed here or anywhere in gitSpecOps: the user authenticates their own
host CLI (`gh auth login`, `glab auth login`, ...), and providers only shell out to what
is already authenticated.
"""

from __future__ import annotations

from typing import Protocol

try:
    from shared.remote_identity import RepoRef, remote_host
except ImportError:  # run directly from shared/
    from remote_identity import RepoRef, remote_host


class RemoteProvider(Protocol):
    name: str

    def list_repos(self, owner: str) -> tuple[list[RepoRef] | None, str | None]:
        """Authoritative repos for a namespace. Returns (repos, error)."""
        ...

    def resolve(self, repo_spec: str) -> tuple[RepoRef | None, str | None]:
        """Resolve owner/name or URL to a canonical RepoRef, following renames. (ref, error)."""
        ...


# host -> provider instance or zero-arg factory. Tiny and explicit on purpose.
_PROVIDERS: dict[str, object] = {}


def register_provider(host: str, provider) -> None:
    """Register a provider (instance or zero-arg factory) for a host, e.g. 'github.com'."""
    if not host:
        raise ValueError("host must be a non-empty string")
    _PROVIDERS[host.lower()] = provider


def registered_hosts() -> list[str]:
    """Hosts with a registered provider, sorted."""
    return sorted(_PROVIDERS)


def provider_for_host(host: str | None) -> RemoteProvider | None:
    """Pick a provider for a bare host, or None when no provider handles it.

    Namespace-level work ("what repos exist under this owner?") has no repository URL to
    parse yet, so it resolves by host directly. Matches the registered host exactly and any
    subdomain ('*.github.com'). Callers must handle None: an unknown host means
    host-agnostic behavior (update-only), never an error.
    """
    if not host:
        return None
    host = host.lower()
    if host in _PROVIDERS:
        entry = _PROVIDERS[host]
    else:
        entry = next((e for known, e in _PROVIDERS.items() if host.endswith("." + known)),
                     None)
        if entry is None:
            return None
    return entry() if callable(entry) else entry


def provider_for(remote_url: str | None) -> RemoteProvider | None:
    """Pick a provider for a remote URL's host, or None when no provider handles it.

    The URL must be a full repository remote; a namespace-only URL has no parseable host
    here, so use `provider_for_host` for that.
    """
    return provider_for_host(remote_host(remote_url))
