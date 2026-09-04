"""Fleet convergence: which repositories do my peers have that I do not?

This is the half of the product that Git and a per-machine dashboard cannot answer. The
awkward part is that the privacy boundary is doing its job: a peer publishes only
`HMAC(fleet_secret, host/owner/name)`, so a machine cannot clone what it cannot name.

The resolution is that the hash is *deterministic*. Ask the provider what repositories exist
under the namespaces you already work in, hash each candidate under the same fleet secret,
and match. A repository you can see is identified without its name ever crossing the
transport; a repository you genuinely cannot see (private, no access) stays an opaque hash,
which is the correct answer rather than a leak.

Nothing here clones. Cloning is a mutation and it already has an owner — `archive_sync.py`
discovers and clones through the same provider seam. This module reports the gap and hands
over the exact command; it never grows a second cloner.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from manifest import repository_id  # noqa: E402


@dataclass
class MissingRepo:
    """A repository some peer reports that this machine does not have."""
    repo_id: str
    machines: list[str] = field(default_factory=list)
    host: str | None = None
    owner: str | None = None
    name: str | None = None

    @property
    def identified(self) -> bool:
        return bool(self.owner and self.name)

    @property
    def label(self) -> str:
        return f"{self.owner}/{self.name}" if self.identified else f"repo:{self.repo_id[:8]}"


def local_repo_ids(views, machine_id: str) -> set[str]:
    """Repository ids this machine itself reported."""
    for view in views:
        if view.machine_id == machine_id:
            return set(view.repositories)
    return set()


def missing_from(views, machine_id: str) -> dict[str, list[str]]:
    """repo_id -> the peer machine labels reporting it, for ids this machine lacks.

    Only peers count: a repository this machine already has is not missing, and a
    repository nobody has is not in any manifest to begin with.
    """
    mine = local_repo_ids(views, machine_id)
    found: dict[str, list[str]] = {}
    for view in views:
        if view.machine_id == machine_id:
            continue
        for repo_id in view.repositories:
            if repo_id in mine:
                continue
            found.setdefault(repo_id, []).append(view.label)
    return {repo_id: sorted(labels) for repo_id, labels in sorted(found.items())}


def namespaces_from_catalog(catalog: dict[str, dict]) -> list[tuple[str, str]]:
    """(host, owner) pairs this machine already works in — the default search space.

    Deliberately not "every namespace on the account": the tool should look where the user
    already is, not enumerate their whole GitHub presence unprompted.
    """
    pairs = {
        (entry["host"], entry["owner"])
        for entry in catalog.values()
        if entry.get("host") and entry.get("owner")
    }
    return sorted(pairs)


def resolve_missing(missing: dict[str, list[str]], namespaces: list[tuple[str, str]],
                    secret: str, provider_for_host, known: dict[str, dict] | None = None,
                    progress=None) -> tuple[list[MissingRepo], list[str]]:
    """Name as many missing repository ids as the local catalog and providers can account for.

    The catalog is consulted first: a repository this machine has seen before, or named on an
    earlier run, needs no network call at all. Only genuinely unknown ids reach a provider.

    Returns (missing repos — identified ones first, provider errors). A namespace that fails
    is reported and skipped: one unreachable org must not hide the rest of the answer.
    """
    repos = {repo_id: MissingRepo(repo_id=repo_id, machines=machines)
             for repo_id, machines in missing.items()}
    for repo_id, entry in (known or {}).items():
        repo = repos.get(repo_id)
        if repo is not None and entry.get("owner") and entry.get("name"):
            repo.host, repo.owner, repo.name = entry.get("host"), entry["owner"], entry["name"]
    unresolved = {repo_id for repo_id, repo in repos.items() if not repo.identified}
    errors: list[str] = []

    for host, owner in namespaces:
        if not unresolved:
            break
        if progress is not None:
            progress(host, owner, len(unresolved))
        provider = provider_for_host(host)
        if provider is None:
            errors.append(f"no provider registered for {host} (namespace {owner} skipped)")
            continue
        listed, error = provider.list_repos(owner)
        if error or listed is None:
            errors.append(f"{host}/{owner}: {error or 'no repositories returned'}")
            continue
        for ref in listed:
            repo_id = repository_id(ref.host or host, ref.owner, ref.name, secret)
            if repo_id in unresolved:
                found = repos[repo_id]
                found.host, found.owner, found.name = ref.host or host, ref.owner, ref.name
                unresolved.discard(repo_id)

    ordered = sorted(repos.values(), key=lambda r: (not r.identified, r.label.lower()))
    return ordered, errors


def catalog_updates(missing: list[MissingRepo]) -> dict[str, dict]:
    """Catalog entries for newly identified peer repositories, so future tables read plainly.

    No `path`: this machine does not have these yet. That absence is what distinguishes a
    known-but-absent repository from one sitting on disk.
    """
    return {
        repo.repo_id: {"display_name": repo.name, "host": repo.host,
                       "owner": repo.owner, "name": repo.name}
        for repo in missing if repo.identified
    }


def roots_by_owner(catalog: dict[str, dict]) -> dict[str, str]:
    """owner -> the local folder that owner's repositories already live in.

    The archive layout is `<parent>/<owner>/<repo>`, so the parent of any repository this
    machine already has under that owner is where a clone of a sibling belongs. Derived from
    real paths rather than assumed, so an unusual layout produces no suggestion instead of a
    wrong one.
    """
    counts: dict[str, dict[str, int]] = {}
    for entry in catalog.values():
        owner, path = entry.get("owner"), entry.get("path")
        if not owner or not path:
            continue
        parent = str(Path(path).parent)
        counts.setdefault(owner, {})
        counts[owner][parent] = counts[owner].get(parent, 0) + 1
    return {owner: max(parents, key=parents.get) for owner, parents in counts.items() if parents}


def render_report(missing: list[MissingRepo], errors: list[str],
                  namespaces: list[tuple[str, str]], owner_roots: dict[str, str] | None = None
                  ) -> str:
    """A readable convergence report, ending in the command that would close the gap."""
    lines = []
    if not missing:
        lines.append("This machine has every repository its peers report. Nothing to converge.")
        return "\n".join(lines + [f"warning: {error}" for error in errors])

    identified = [repo for repo in missing if repo.identified]
    unidentified = [repo for repo in missing if not repo.identified]

    lines.append(f"{len(missing)} repositor(ies) reported by peers are not on this machine.")
    lines.append("")
    width = max((len(repo.label) for repo in missing), default=10)
    lines.append(f"{'Repository'.ljust(width)}  Present on")
    lines.append(f"{'-' * width}  {'-' * 10}")
    for repo in missing:
        lines.append(f"{repo.label.ljust(width)}  {', '.join(repo.machines)}")

    if unidentified:
        lines.append("")
        lines.append(
            f"{len(unidentified)} could not be named from the namespaces searched "
            f"({', '.join(f'{h}/{o}' for h, o in namespaces) or 'none'}). That is expected for a "
            "repository you have no access to — its identity stays opaque by design. Add "
            "--namespace OWNER to search somewhere else.")

    if identified:
        lines.append("")
        lines.append("To clone them, hand each namespace to the archive engine, which already "
                     "discovers and clones through the same provider seam:")
        owner_roots = owner_roots or {}
        for owner in sorted({repo.owner for repo in identified if repo.owner}):
            root = owner_roots.get(owner, f"<folder holding your {owner} repositories>")
            lines.append(f"    python3 git-archive-updater/archive_sync.py --root {root} "
                         f"--github-owner {owner} --sync")
        lines.append("")
        lines.append("`--sync` updates existing repositories and clones the missing ones. It "
                     "previews and asks before applying. This tool clones nothing itself, on "
                     "purpose.")
    for error in errors:
        lines.append(f"warning: {error}")
    return "\n".join(lines)
