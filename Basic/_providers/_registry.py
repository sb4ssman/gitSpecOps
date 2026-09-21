"""The host seam: map a remote host to the provider that knows how to talk to it.

A provider answers two questions for its host -- "what repositories exist under this owner?"
and "what is this (possibly renamed) repository's canonical identity?" -- so every operation
above it stays host-neutral. An unknown host is not an error: it means host-agnostic behavior
(fast-forward what is already here; never invent clones, orphans or renames).

Providers register where they live: each module in this folder calls `register_provider()` on
import. The registry imports the built-in ones itself, the first time it is asked, so no caller
ever has to remember to. **Adding a host is one module plus one import line in
`_load_built_in_providers`.** Nothing is discovered or loaded dynamically.

Auth is not managed here or anywhere in gitSpecOps: the user authenticates their own host CLI
(`gh auth login`, `glab auth login`, ...), and providers only shell out to what is already
authenticated.
"""

from __future__ import annotations

from typing import Protocol

from Basic._identity import RepoRef, remote_host


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
_BUILT_INS_LOADED = False


def _load_built_in_providers() -> None:
    """Import every provider module shipped here; each registers itself on import."""
    global _BUILT_INS_LOADED
    if _BUILT_INS_LOADED:
        return
    _BUILT_INS_LOADED = True
    from Basic._providers import github  # noqa: F401  -- one line per host


def register_provider(host: str, provider) -> None:
    """Register a provider (instance or zero-arg factory) for a host, e.g. 'github.com'."""
    if not host:
        raise ValueError("host must be a non-empty string")
    _PROVIDERS[host.lower()] = provider


def registered_hosts() -> list[str]:
    """Hosts with a registered provider, sorted."""
    _load_built_in_providers()
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
    _load_built_in_providers()
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
