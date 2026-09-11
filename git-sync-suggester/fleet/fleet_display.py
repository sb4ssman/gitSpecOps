"""Pure, versioned display contract shared by every fleet presentation.

No database, HTTP, filesystem, HTML, CSS or network calls belong here. Skins consume the
same facts, attention tags, semantic tones, notices and capabilities; they do not classify
Git state. See DISPLAY-CONTRACT.md. This is separate from the private report schema.
"""
from __future__ import annotations

from datetime import datetime, timezone

from advice import describe_repository, repository_flags
from aggregate import age_seconds, build_rows, machine_views
from shared.version import VERSION  # the one place a version number is written down

CONTRACT_NAME = "gitspecops.fleet.display"
CONTRACT_VERSION = 1
PRODUCT_NAME = "gitSpecOps Sync-Suggester Fleet Management"


def _cell(cell):
    if not cell.present:
        return {"present": False, "freshness": "absent", "state": "absent",
                "description": "Not reported here", "tone": "muted", "tags": ["missing"],
                "facts": None}
    flags = repository_flags(cell.repo)
    tags = []
    if "dirty" in flags:
        tags.append("dirty")
    if flags & {"ahead", "diverged"}:
        tags.append("ahead")
    if cell.freshness != "current":
        tags.append("stale")
    description = describe_repository(cell.repo)
    if cell.freshness != "current":
        description = f"Last known: {description} ({cell.freshness})"
    if flags & {"dirty", "operation", "diverged"}:
        tone = "danger"
    elif flags & {"ahead", "behind", "stashed"} or cell.freshness != "current":
        tone = "warning"
    elif "no_upstream" in flags:
        tone = "neutral"
    else:
        tone = "success"
    return {"present": True, "freshness": cell.freshness, "state": cell.effective_state,
            "description": description, "tone": tone, "tags": tags,
            "facts": {key: cell.repo.get(key) for key in (
                "staged", "unstaged", "untracked", "stashes", "ahead", "behind",
                "operation", "has_upstream", "upstream_observed_at")}}


def build_display(reports, fleet_id, now=None, stale_seconds=120, settings=None):
    """Return JSON-compatible display v1. All clock-dependent rules use the supplied now."""
    now = now or datetime.now(timezone.utc)
    manifests = [r["manifest"] for r in reports]
    views = sorted(machine_views(manifests, now, stale_seconds / 3600, 7),
                   key=lambda v: (v.label.casefold(), v.machine_id))
    names = {}
    for report in reports:
        names.update(report["names"])
    catalog = {rid: {"display_name": f"{v['owner']}/{v['name']}"} for rid, v in names.items()}
    rows, groups = [], {}
    for row in build_rows(views, catalog):
        identity = names[row.repo_id]
        group_id = f"{identity['host']}/{identity['owner']}"
        group = groups.setdefault(group_id, {"id": group_id, "label": identity["owner"],
                                            "host": identity["host"], "count": 0, "attention": 0})
        cells = {mid: _cell(cell) for mid, cell in row.cells.items()}
        # Same severity policy as the CLI; missing/stale reports additionally deserve attention
        # in this live view. A client must not infer this from a numeric threshold or color.
        attention = row.severity >= 20 or any(
            not cell.present or cell.freshness != "current" for cell in row.cells.values())
        tags = set(tag for cell in cells.values() for tag in cell["tags"])
        if attention:
            tags.add("attention")
        for cell in cells.values():
            if attention:
                # Row-level advice can involve multiple devices; filtering by machine still
                # retains that advice, rather than implying that one clean cell is an all-clear.
                cell["tags"] = sorted(set(cell["tags"]) | {"attention"})
        group["count"] += 1
        group["attention"] += int(attention)
        rows.append({"id": row.repo_id, "name": row.name, "identity": dict(identity),
                     "namespace": identity["owner"], "group_id": group_id,
                     "severity": row.severity, "needs_attention": attention,
                     "tags": sorted(tags), "cells": cells,
                     "advice": ("Clean against cached refs; remote unverified"
                                if row.severity_key == "synced" else row.advice)})
    rows.sort(key=lambda r: (-r["severity"], r["name"].casefold(), r["id"]))
    machines = [{"id": v.machine_id, "label": v.label,
                 "age_seconds": age_seconds(v.observed_at, now), "freshness": v.freshness,
                 "observed_at": v.observed_at, "repository_count": len(v.repositories),
                 "tone": "success" if v.freshness == "current" else "warning"} for v in views]
    settings = settings or {}
    return {
        "contract": {"name": CONTRACT_NAME, "version": CONTRACT_VERSION},
        "product": {"name": PRODUCT_NAME, "version": VERSION, "channel": "development"},
        "generated_at": now.isoformat(), "fleet_id": fleet_id,
        "summary": {"repositories": len(rows), "attention": sum(r["needs_attention"] for r in rows),
                    "machines": len(machines),
                    "current_machines": sum(m["freshness"] == "current" for m in machines),
                    "stale_machines": sum(m["freshness"] != "current" for m in machines)},
        "machines": machines, "groups": sorted(groups.values(), key=lambda g: g["id"].casefold()),
        "rows": rows,
        "issues": [{"machine_id": r["manifest"]["machine_id"],
                    "machine": r["manifest"]["machine_label"], "items": list(r["issues"])}
                   for r in reports if r["issues"]],
        "filters": [{"id": "all", "label": "All repositories"},
                    {"id": "attention", "label": "Needs attention"},
                    {"id": "dirty", "label": "Uncommitted work"},
                    {"id": "ahead", "label": "Unpushed commits"},
                    {"id": "stale", "label": "Stale reports"},
                    {"id": "missing", "label": "Not reported on a machine"}],
        "notices": [{"id": "cached-refs", "tone": "neutral",
                     "text": "Ahead/behind uses cached Git refs. A clean report does not prove "
                             "that machines are on the same commit or current with GitHub."},
                    {"id": "staleness", "tone": "warning",
                     "text": f"Reports older than {stale_seconds:g} seconds are stale. "
                             "Last-known unfinished work stays visible."}],
        "capabilities": {"observe": {"available": True, "reason": "Status observation is running."},
                         "repository_actions": {"available": False, "reason":
                             "Fetch, pull, commit and push are not available from this dashboard."},
                         "baskets": {"available": False, "reason":
                             "Groups show observed organizations. Basket subscriptions are not available yet."},
                         "installation": {"available": False, "reason":
                             "This is a development preview. A supported desktop installer is not available yet."},
                         "self_update": {"available": False, "reason":
                             "Updates are developer-managed. Automatic updates are not enabled."}},
        "integrations": [
            {"id": "tailscale", "label": "Tailscale live monitoring", "available": True,
             "enabled": True, "description": "Near-live reports between connected fleet machines.",
             "detail": ("Filesystem events; targeted checks after "
                        f"{settings.get('debounce_seconds', 'unknown')} seconds quiet.")},
            {"id": "synced_folder", "label": "Synchronized folder / Obsidian", "available": True,
             "enabled": bool(settings.get("replica_folder")),
             "description": "Timed intermediate persistence through an existing folder-sync client.",
             "detail": (f"Every {settings.get('folder_seconds')} seconds."
                        if settings.get("replica_folder") else "No synchronized folder configured.")},
            {"id": "github", "label": "Private GitHub state repository", "available": True,
             "enabled": bool(settings.get("replica_repo")),
             "description": "Lower-frequency durable status history using existing gh authentication.",
             "detail": (f"Every {settings.get('github_seconds')} seconds."
                        if settings.get("replica_repo") else "No GitHub state repository configured.")},
        ],
        "features": [
            {"id": "continuous_scan", "label": "Event-driven repository observation",
             "available": True, "enabled": True,
             "description": "Native filesystem events trigger a read-only check of the changed repository.",
             "detail": (f"{settings.get('root_count', 'Unknown number of')} configured root(s); "
                        "no periodic inventory scan.")},
            {"id": "remote_actions", "label": "Remote fetch, pull, commit and push",
             "available": False, "enabled": False,
             "description": "Planned: reviewed, device-executed Git actions from the dashboard.",
             "detail": "No remote action endpoint exists in this preview."},
            {"id": "recovery_snapshots", "label": "Automatic unfinished-work recovery",
             "available": False, "enabled": False,
             "description": "Planned: opt-in encrypted recovery snapshots (stealth-stash / stealth-sync).",
             "detail": "No source content is currently copied into fleet storage."},
        ],
    }
