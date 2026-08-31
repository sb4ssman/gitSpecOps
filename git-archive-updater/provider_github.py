"""
provider_github
===============

GitHub implementation of RemoteProvider, via the `gh` CLI. Provider #1.

One task: answer "what repos exist under this GitHub owner" and "what is the canonical
identity of this (possibly renamed) repo." Everything GitHub-specific lives here; no other
module imports `gh`.

Standalone:

    python provider_github.py list moon-and-back
    python provider_github.py resolve solid-five-seven/ggm-wedding.com
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Shared modules live at the repo root (gh wrapper + provider identity).
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from shared.gh_cli import GhError, run_gh  # noqa: E402
from shared.remote_identity import RepoRef  # noqa: E402,F401

# Fields requested from `gh` for both list and view; maps 1:1 onto RepoRef in _ref_from_json.
_FIELDS = "id,name,nameWithOwner,url,isPrivate,isFork,isArchived"


def _ref_from_json(item: dict) -> RepoRef:
    owner = item.get("nameWithOwner", "/").split("/", 1)[0]
    return RepoRef(
        id=item["id"],
        owner=owner,
        name=item["name"],
        url=item["url"],
        host="github.com",
        private=item.get("isPrivate", False),
        fork=item.get("isFork", False),
        archived=item.get("isArchived", False),
    )


class GitHubProvider:
    name = "github"

    def list_repos(self, owner: str) -> tuple[list[RepoRef] | None, str | None]:
        try:
            proc = run_gh(["repo", "list", owner, "--json", _FIELDS, "--limit", "1000"])
            return [_ref_from_json(item) for item in json.loads(proc.stdout)], None
        except GhError as exc:
            return None, str(exc)
        except json.JSONDecodeError as exc:
            return None, f"gh repo list returned invalid JSON: {exc}"

    def resolve(self, repo_spec: str) -> tuple[RepoRef | None, str | None]:
        """Resolve owner/name or a full URL to its canonical RepoRef, following renames."""
        try:
            proc = run_gh(["repo", "view", repo_spec, "--json", _FIELDS])
            return _ref_from_json(json.loads(proc.stdout)), None
        except GhError as exc:
            return None, str(exc)
        except json.JSONDecodeError as exc:
            return None, f"gh repo view returned invalid JSON: {exc}"


def main() -> int:
    if len(sys.argv) < 3 or sys.argv[1] not in ("list", "resolve"):
        print("usage: python provider_github.py {list <owner> | resolve <owner/name|url>}", file=sys.stderr)
        return 2
    provider = GitHubProvider()
    if sys.argv[1] == "list":
        repos, error = provider.list_repos(sys.argv[2])
        if error:
            print(error, file=sys.stderr)
            return 1
        for r in repos:
            print(f"{r.id}  {r.owner}/{r.name}  {r.url}")
        return 0
    ref, error = provider.resolve(sys.argv[2])
    if error:
        print(error, file=sys.stderr)
        return 1
    print(f"{ref.id}  {ref.owner}/{ref.name}  {ref.url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
