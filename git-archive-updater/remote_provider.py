"""
remote_provider
===============

Archive-side facade over the shared provider registry (shared/providers.py). The
contract, the host->provider resolution, and RepoRef now live in shared; the GitHub
provider registers itself here -- tool-side registration keeps shared free of tool
imports. Exports kept for the archive modules: RemoteProvider, RepoRef, provider_for.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from shared.providers import (  # noqa: E402
    RemoteProvider,
    provider_for as _registry_provider_for,
    register_provider,
)
from shared.remote_identity import RepoRef  # noqa: E402,F401

try:
    from .provider_github import GitHubProvider
except ImportError:
    from provider_github import GitHubProvider

# Providers this tool ships with. One line per host.
register_provider("github.com", GitHubProvider)


def provider_for(remote_url: str | None) -> RemoteProvider | None:
    """Resolve a remote URL to its provider, or None (host-agnostic fallback)."""
    return _registry_provider_for(remote_url)
