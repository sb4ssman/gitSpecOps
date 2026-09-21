"""GitHub, through the user's own authenticated `gh` CLI. Every `gh` invocation lives here.

Three kinds of thing, all one host operation each, none with policy:

- **The `gh` boundary.** `run_gh` runs `gh` through `Basic/_run.py` (bounded, tree-killed on
  timeout) with prompts disabled, so a missing login fails instead of asking. Auth is never
  configured here: `gh auth login` is the user's.
- **The provider.** `GitHubProvider` answers the registry's two questions (list a namespace,
  resolve a possibly renamed repository) and registers itself for github.com on import.
- **Host operations callers need beyond the provider contract**: inventory with details, LFS
  probe, namespace membership, repository creation, duplicate comparison, the latest release.
  They return data or raise `GhError`; printing, exiting, pacing and confirmation belong to the
  operation that calls them.
"""

from __future__ import annotations

import base64
import binascii
import json

from Basic._identity import RepoRef
from Basic._providers._registry import register_provider
from Basic._run import run

GH_TIMEOUT_SECONDS = 120

#: `gh` honors this: a command that would need an interactive answer fails instead of waiting.
_NEVER_PROMPT = {"GH_PROMPT_DISABLED": "1"}


class GhError(RuntimeError):
    """Raised when gh is missing, times out, or (with check=True) exits nonzero."""


def run_gh(args: list[str], check: bool = True, capture: bool = True,
           timeout: float = GH_TIMEOUT_SECONDS):
    """Run `gh` with args and return the completed process. Raises GhError on failure."""
    proc = run(["gh", *args], timeout=timeout, capture=capture, env=_NEVER_PROMPT)
    if proc.missing:
        raise GhError("gh CLI not found; install from https://cli.github.com")
    if proc.timed_out:
        raise GhError(f"gh timed out after {timeout}s: gh {' '.join(args)}")
    if check and proc.returncode != 0:
        detail = (proc.stderr or "").strip() or "unknown error"
        raise GhError(f"gh {' '.join(args)} failed: {detail}")
    return proc


def gh_installed() -> bool:
    try:
        run_gh(["--version"])
        return True
    except GhError:
        return False


def gh_authenticated() -> bool:
    """`gh auth status` exits nonzero (and reports on stderr) when there is no login."""
    try:
        return run_gh(["auth", "status"], check=False).returncode == 0
    except GhError:
        return False


# -------------------------------------------------------------------------------------
# The provider
# -------------------------------------------------------------------------------------
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


register_provider("github.com", GitHubProvider)


# -------------------------------------------------------------------------------------
# Host operations beyond the provider contract
# -------------------------------------------------------------------------------------
_REPO_FIELDS = "name,createdAt,isPrivate,isFork,isArchived,description,diskUsage"


def org_access_error(org: str) -> str | None:
    """Read-access probe for a namespace. Returns an error message, or None when accessible."""
    try:
        run_gh(["repo", "list", org, "--limit", "1", "--json", "name"])
        return None
    except GhError as exc:
        return str(exc)


def fetch_org_repos(org: str) -> list[dict]:
    """A namespace's repositories with size/visibility details. Raises GhError or JSONDecodeError."""
    result = run_gh(["repo", "list", org, "--limit", "1000", "--json", _REPO_FIELDS])
    text = (result.stdout or "").strip()
    if not text:
        raise GhError(f"gh returned an empty repo list for {org}")
    return json.loads(text)


def check_repo_for_lfs(org: str, repo_name: str, timeout: float = 20) -> bool:
    """Best-effort: does this repo's .gitattributes declare an LFS filter?

    A network/timeout error or a repo without .gitattributes both mean "assume not" -- this
    only drives a warning line, never behavior, so it must never raise.
    """
    try:
        result = run_gh(["api", f"/repos/{org}/{repo_name}/contents/.gitattributes",
                         "--jq", ".content"], check=False, timeout=timeout)
    except GhError:
        return False
    if result.returncode != 0 or not result.stdout.strip():
        return False
    try:
        content = base64.b64decode(result.stdout.strip()).decode("utf-8", errors="ignore")
    except (binascii.Error, ValueError):
        return False
    return "filter=lfs" in content


def resolve_repo_details(spec: str) -> dict:
    """Resolve owner/name or URL into the fields single-repo download needs.

    Raises GhError (missing repo / no access / bad spec) or json.JSONDecodeError.
    """
    spec = spec.strip()
    if not spec or spec.startswith("-"):
        raise GhError(f"not a repository spec: {spec!r}")
    result = run_gh(["repo", "view", spec, "--json",
                     "name,owner,isPrivate,isFork,isArchived,diskUsage,description"])
    text = (result.stdout or "").strip()
    if not text:
        raise GhError(f"gh returned nothing for {spec!r}")
    return json.loads(text)


def create_repo(org: str, repo_name: str, private: bool = True, description: str | None = None) -> None:
    """Create one repository. Confirmation policy stays with the caller."""
    args = ["repo", "create", f"{org}/{repo_name}",
            "--private" if private else "--public", "--clone=false"]
    if description:
        args.extend(["--description", description.replace('"', "'")])
    run_gh(args)


def ensure_repo(org: str, repo_name: str, private: bool = True,
                description: str | None = None) -> bool:
    """Create a repository only when it does not exist. Returns True when created."""
    existing = run_gh(["repo", "view", f"{org}/{repo_name}"], check=False)
    if existing.returncode == 0:
        return False
    create_repo(org, repo_name, private=private, description=description)
    return True


def list_my_orgs() -> list[dict]:
    """Namespaces the authenticated account can read: [{'login', 'role', 'state'}, ...].

    The first entry is ALWAYS the user's own account (personal: True) -- personal repos are a
    namespace just like an org. Then every org membership; role is 'admin' (owner) or 'member'
    and does not gate reading -- access does, which callers verify per namespace.
    """
    me = run_gh(["api", "user", "--jq", ".login"]).stdout.strip()
    orgs, seen = [], set()
    if me:
        orgs.append({"login": me, "role": "owner", "state": "active", "personal": True})
        seen.add(me)
    result = run_gh(["api", "user/memberships/orgs", "--paginate",
                     "--jq", ".[] | {login: .organization.login, role: .role, state: .state}"])
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        login = item.get("login")
        if login and login not in seen:
            seen.add(login)
            orgs.append(item)
    return orgs


def compare_repos(source_org: str, dest_org: str, repo_name: str) -> tuple[bool, str]:
    """Are two same-named repos identical duplicates? Compares every branch head. Never raises."""
    try:
        source_info = run_gh(["api", f"/repos/{source_org}/{repo_name}",
                              "--jq", "{default_branch: .default_branch, size: .size}"])
        dest_info = run_gh(["api", f"/repos/{dest_org}/{repo_name}",
                            "--jq", "{default_branch: .default_branch, size: .size}"])
        source_data = json.loads(source_info.stdout.strip())
        dest_data = json.loads(dest_info.stdout.strip())
        if source_data["default_branch"] != dest_data["default_branch"]:
            return False, "Default branches don't match"

        def branches(org: str) -> set[str]:
            out = run_gh(["api", f"/repos/{org}/{repo_name}/branches", "--jq", ".[].name"])
            text = out.stdout.strip()
            return set(text.split("\n")) if text else set()

        source_branches, dest_branches = branches(source_org), branches(dest_org)
        if not dest_branches and source_branches:
            return False, "Destination repo has no branches"
        if source_branches != dest_branches:
            return False, (f"Branch count mismatch (source: {len(source_branches)}, "
                           f"dest: {len(dest_branches)})")
        for branch in source_branches:
            heads = [run_gh(["api", f"/repos/{org}/{repo_name}/branches/{branch}",
                             "--jq", ".commit.sha"]).stdout.strip()
                     for org in (source_org, dest_org)]
            if heads[0] != heads[1]:
                return False, f"Branch '{branch}' has different HEAD commits"
        # All branches match: identical regardless of reported size (GitHub's size lags).
        return True, "Repos are identical (all branches match)"
    except Exception as exc:  # noqa: BLE001 - a comparison failure is an answer, not a crash
        return False, f"Error comparing: {exc}"


def latest_release_tag(repository: str, timeout: float = 15) -> str | None:
    """The newest published release tag of owner/name, or None when it cannot be determined."""
    try:
        proc = run_gh(["release", "list", "--repo", repository, "--limit", "1",
                       "--json", "tagName"], check=False, timeout=timeout)
    except GhError:
        return None
    if proc.returncode or not proc.stdout.strip():
        return None
    try:
        releases = json.loads(proc.stdout)
    except ValueError:
        return None
    if not isinstance(releases, list) or not releases:
        return None
    tag = releases[0].get("tagName")
    return tag if isinstance(tag, str) and tag.strip() else None
