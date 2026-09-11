"""Build the fleet display document from published manifests alone — no host, no Tailscale.

This is the piece that makes the dashboard independent of any live connection. Every machine
writes one manifest that it alone owns into whichever transports it has (a synced folder, a
private GitHub repo). Those manifests are the fingerprints: a machine that is asleep, offline,
or gone still has its last report sitting there, and the freshness rules in `aggregate` already
say exactly how much that report can still be trusted.

So the dashboard's real input is "every manifest I can currently read", from any tier. A live
tailnet connection is one more way to obtain a *fresher* manifest — never a precondition for
having a dashboard at all.

Pure with respect to policy: it assembles inputs and hands them to `fleet_display.build_display`,
which remains the only module permitted to decide what fleet state means.
"""
from __future__ import annotations

from aggregate import load_manifests, newest_per_machine, split_by_fleet
from fleet_display import build_display


def _identity(repo_id: str, entry: dict | None) -> dict:
    """A readable identity when the local catalog knows one; an honest placeholder otherwise.

    Peers publish salted digests, so a repository this machine has never seen itself genuinely
    cannot be named here. That is the privacy boundary working as designed, not a defect --
    `converge` is what resolves those ids, and inventing a plausible name would be worse than
    showing the digest.
    """
    entry = entry or {}
    owner = entry.get("owner")
    name = entry.get("name") or entry.get("display_name")
    if owner and name:
        return {"host": entry.get("host") or "github.com", "owner": owner, "name": name}
    return {"host": "unidentified", "owner": "unidentified", "name": f"repo {repo_id[:8]}…"}


def reports_from_manifests(manifests: list[dict], catalog: dict | None = None,
                           issues: list[str] | None = None) -> list[dict]:
    """Adapt stored manifests into the report shape the display contract consumes."""
    catalog = catalog or {}
    reports = []
    for manifest in manifests:
        names = {}
        for record in manifest.get("repositories") or []:
            repo_id = record.get("repo_id")
            if repo_id:
                names[repo_id] = _identity(repo_id, catalog.get(repo_id))
        reports.append({"manifest": manifest, "names": names, "issues": []})
    if reports and issues:
        # Unreadable manifests are attached to the reading machine, so they surface in the UI
        # rather than vanishing: a manifest that cannot be parsed is a fact about the fleet.
        reports[0]["issues"] = list(issues)
    return reports


def display_from_manifests(manifests: list[dict], fleet_id: str | None = None,
                           catalog: dict | None = None, names: dict | None = None,
                           issues: list[str] | None = None, now=None,
                           settings: dict | None = None) -> dict:
    """Render the display from manifests gathered from *any* mix of sources.

    A peer reads the same machine from several places at once — its own observation, a synced
    folder, a private repo, a live pull — and those copies disagree by design, because they were
    written at different moments. `machine_views` keeps the newest per machine, so more
    transports can only ever improve freshness, never conflict. That is what makes the tiers
    complements rather than alternatives.

    `names` carries readable identities learned from live peers (which may share them inside a
    private tailnet); `catalog` carries the ones this machine knows itself. Neither is required.
    """
    issues = list(issues or [])
    if fleet_id:
        # A machine that joined with the wrong secret is reported, never silently merged.
        mine, strangers = split_by_fleet(manifests, fleet_id)
        if strangers:
            labels = sorted({m.get("machine_label") or m.get("machine_id") or "?"
                             for m in strangers})
            issues.append(f"{len(strangers)} manifest(s) belong to a different fleet id and "
                          f"were ignored: {', '.join(labels)}")
        manifests = mine
    # One view per machine: the same machine legitimately arrives from several sources at once
    # (its own observation, a synced folder, a state repo, a live pull). Newest wins, silently.
    manifests = newest_per_machine(manifests)
    combined = dict(catalog or {})
    for repo_id, identity in (names or {}).items():
        combined.setdefault(repo_id, identity)
    reports = reports_from_manifests(manifests, combined, issues)
    return build_display(reports, fleet_id or "local", now=now, settings=settings)


def display_from_transport(transport, config: dict, catalog: dict | None = None,
                           now=None, settings: dict | None = None) -> dict:
    """Read every peer manifest from one transport and render the display document."""
    manifests, issues = load_manifests(transport)
    return display_from_manifests(manifests, fleet_id=config.get("fleet_id"), catalog=catalog,
                                  issues=issues, now=now, settings=settings)
