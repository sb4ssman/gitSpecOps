"""Pure, versioned display contract shared by every fleet presentation.

No database, HTTP, filesystem, HTML, CSS or network calls belong here. Skins consume the
same facts, attention tags, semantic tones, notices and capabilities; they do not classify
Git state. See DISPLAY-CONTRACT.md. This is separate from the private report schema.
"""
from __future__ import annotations

from datetime import datetime, timezone

from Special._sync.advice import describe_repository, repository_flags
from Elaborate._fleet.aggregate import SEVERITY, age_seconds, build_rows, machine_views
from Basic._version import VERSION  # read from pyproject.toml, where it is written down once

CONTRACT_NAME = "gitspecops.fleet.display"
CONTRACT_VERSION = 1
PRODUCT_NAME = "gitSpecOps"
#: Readable names for the clouds repositories come from; any other host is shown as itself.
PROVIDER_NAMES = {"github.com": "GitHub", "gitlab.com": "GitLab", "bitbucket.org": "Bitbucket",
                  "local": "No remote (only on machines)"}


def _row_place(row, here=None) -> dict | None:
    """Where a repository lives, names only: where this machine keeps it when it has a copy;
    otherwise the place most machines report. Grouping by the fleet's most common place split a
    folder on the machine looking at it: ten of a folder's eleven repositories also sat on another
    machine's backup library and were grouped there, the eleventh apart (2026-11-16)."""
    from collections import Counter
    mine = row.cells.get(here) if here else None
    if mine is not None and mine.present and mine.repo.get("place"):
        return {"library": mine.repo["place"]["library"], "folder": mine.repo["place"]["folder"]}
    places = Counter((cell.repo["place"]["library"], cell.repo["place"]["folder"])
                     for cell in row.cells.values() if cell.present and cell.repo.get("place"))
    if not places:
        return None
    (library, folder), _count = max(places.items(), key=lambda item: (item[1], item[0]))
    # Not on this machine: say whose library it is, so it never merges into a library here of
    # the same name (the user: machine, then library, then folder).
    owner = next((machine_id for machine_id, cell in row.cells.items() if cell.present and cell.repo.get("place")
                  and (cell.repo["place"]["library"], cell.repo["place"]["folder"]) == (library, folder)), None)
    return {"library": library, "folder": folder, "machine": owner if here else None}


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 120:
        return f"{seconds} seconds"
    if seconds < 7200:
        return f"{seconds // 60} minutes"
    return f"{seconds // 3600} hours"


def staleness_text(stale_seconds: float, transports: dict) -> str:
    """When a machine counts as stale, said from the intervals chosen in setup (the user,
    2026-11-16: the page's fixed wording did not match the choice)."""
    if not transports:
        return ("This machine is not in a fleet, so only its own report is shown. Setup's Fleet "
                "step, or the Settings tab, starts or joins one.")
    ways = []
    if "tailnet" in transports:
        ways.append(f"over Tailscale every {_duration((transports['tailnet'] or {}).get('seconds') or 300)}")
    for name, label in (("folder", "through the synced folder"), ("repo", "through the state repository")):
        if transports.get(name, {}).get("seconds"):
            ways.append(f"{label} every {_duration(transports[name]['seconds'])}")
    checked = f"Machines check in {' and '.join(ways)}, as chosen in setup. " if ways else ""
    return (f"{checked}A machine that has not reported for {_duration(stale_seconds)} (two missed "
            "check-ins and a minute) is stale. Its last-known unfinished work stays visible.")


def _cell(cell):
    if not cell.present:
        return {"present": False, "freshness": "absent", "state": "absent",
                "description": "Not reported here", "tone": "muted", "tags": ["missing"],
                "needs_attention": False, "facts": None}
    flags = repository_flags(cell.repo)
    tags = []
    if "dirty" in flags:
        tags.append("dirty")
    if "no_remote" in flags:
        tags.append("local_only")
    if flags & {"ahead", "diverged", "unpushed"}:
        tags.append("ahead")
    if cell.freshness != "current":
        tags.append("stale")
    if len(cell.repo.get("copies") or []) > 1:
        tags.append("copies")  # more than one folder of it on this machine
    description = describe_repository(cell.repo)
    if cell.freshness != "current":
        description = f"Last known: {description} ({cell.freshness})"
    if flags & {"dirty", "operation", "diverged", "no_remote"}:
        tone = "danger"
    elif flags & {"ahead", "unpushed", "behind", "stashed"} or cell.freshness != "current":
        tone = "warning"
    elif "no_upstream" in flags:
        tone = "neutral"
    else:
        tone = "success"
    # This copy's own share of the row's attention rule: unfinished work here (stashed or worse).
    # Every view counts a machine's attention from this, never from the whole row.
    return {"present": True, "freshness": cell.freshness, "state": cell.effective_state,
            "description": description, "tone": tone, "tags": tags,
            "place": cell.repo.get("place"),  # where this machine keeps its copy (names only)
            # Each folder's own facts when this machine keeps it in more than one library.
            "copies": cell.repo.get("copies"),
            "needs_attention": SEVERITY.get(cell.effective_state, 0) >= SEVERITY["stashed"],
            "facts": {key: cell.repo.get(key) for key in (
                "staged", "unstaged", "untracked", "stashes", "ahead", "behind",
                "operation", "has_upstream", "upstream_observed_at", "has_remote", "unpushed",
                "branch", "head", "upstream_head", "checkouts",
                "identity")}}


def _defer_to_live_disks(rows, labels) -> None:
    """One box, two operating systems (2026-11-17): a machine that is not reporting kept a copy on
    a disk that another machine reports live right now. They are the same files, so the live
    report speaks for them: the quiet copy stays shown, says where it is seen now, and its old
    unfinished work no longer counts twice. A copy on a disk only it can read (a Linux-only or
    BitLocker library) keeps its last-known state and attention, as every stale copy does."""
    live = {}
    for row in rows:
        for machine_id, cell in row["cells"].items():
            if not cell["present"] or cell["freshness"] != "current":
                continue
            for copy in cell.get("copies") or [{"place": cell.get("place")}]:
                disk = (copy.get("place") or {}).get("disk")
                if disk:
                    live.setdefault((row["id"], disk), machine_id)
    for row in rows:
        changed = False
        for machine_id, cell in row["cells"].items():
            if not cell["present"] or cell["freshness"] == "current":
                continue
            disks = [(copy.get("place") or {}).get("disk") for copy in cell.get("copies") or [{"place": cell.get("place")}]]
            seen = {live.get((row["id"], disk)) for disk in disks}
            if not disks or None in disks or None in seen or machine_id in seen:
                continue
            other = sorted(seen)[0]
            cell["same_disk_as"] = other
            cell["description"] = f"Same disk as {labels.get(other, other)}, which reports it now"
            cell["tone"] = "muted"
            cell["needs_attention"] = False
            cell["tags"] = sorted((set(cell["tags"]) - {"attention"}) | {"same_disk"})
            changed = True
        if changed:
            row["needs_attention"] = any(c["present"] and c["needs_attention"] for c in row["cells"].values())


def _remote_checked(row, now, fetch_seconds) -> bool:
    """Every machine holding this repository fetched its remote within the fetch schedule."""
    if not fetch_seconds:
        return False
    for cell in row.cells.values():
        if not cell.present:
            continue
        age = age_seconds(cell.repo.get("upstream_observed_at"), now)
        if age is None or age > 2 * fetch_seconds + 300:
            return False
    return True


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def mark_state(rows, machines, reports, settings) -> dict:
    """The two signals every face shows (the tray icon, the web view's mark): this machine, and
    the fleet condensed to its worst machine. States: starting, ok, attention, error, none.

    A machine's own trouble is a copy on it that is not plainly in sync (uncommitted, unpushed,
    behind, diverged, stashed, unreadable) or a problem it reported. The fleet is "none" until
    this machine joins one, "starting" until another machine reports, then the worst of them:
    a machine that stopped reporting or has trouble of its own needs attention. Error is kept
    for failures of this machine's own peer, which only the tray can see."""
    me = settings.get("machine_id")
    issues = {r["manifest"]["machine_id"]: len(r["issues"]) for r in reports if r["issues"]}

    def trouble(machine_id):
        return sum(1 for row in rows
                   if (cell := row["cells"].get(machine_id)) and cell["present"]
                   and cell["state"] != "synced")

    mine = next((m for m in machines if m["id"] == me), None)
    if mine is None:
        machine = {"state": "starting", "text": "waiting for the first observation"}
    else:
        count, problems = trouble(me), issues.get(me, 0)
        parts = [f"{mine['repository_count']} repositories, {count} need attention" if count
                 else f"{mine['repository_count']} repositories, all in sync"]
        if problems:
            parts.append(_plural(problems, "problem", "problems"))
        machine = {"state": "attention" if count or problems else "ok", "text": ", ".join(parts)}
    others = [m for m in machines if m["id"] != me]
    if not settings.get("transport_config"):
        fleet = {"state": "none", "text": "not in a fleet"}
    elif not others:
        fleet = {"state": "starting", "text": "no other machine has reported yet"}
    else:
        needy = [m for m in others if m["freshness"] != "current" or trouble(m["id"]) or issues.get(m["id"])]
        # Every machine counted, this one included; each other machine that needs something named
        # with what (the user, 2026-11-16: "0 of 2 clear" said nothing anyone could use).
        total = _plural(len(others) + 1, "machine", "machines")
        if needy:
            def why(view):
                if view["freshness"] != "current":
                    return "not reporting"
                if trouble(view["id"]):
                    return f"{trouble(view['id'])} need attention"
                return "reported a problem"
            fleet = {"state": "attention",
                     "text": f"{total}; " + ", ".join(f"{view['label']}: {why(view)}" for view in needy),
                     # The header's one line (2026-11-17: "clip it to just this machine, and
                     # fleet"); the full text above stays for the tray and the tooltip.
                     "short": f"{total}, {len(needy)} of the others need{'s' if len(needy) == 1 else ''} attention"}
        else:
            fleet = {"state": "ok", "text": f"{total}; nothing needs attention on the others",
                     "short": f"{total}, all clear"}
    if settings.get("fleet_name") and settings.get("transport_config"):
        fleet["text"] = f"{settings['fleet_name']}: {fleet['text']}"  # the fleet by its name
        if "short" in fleet:
            fleet["short"] = f"{settings['fleet_name']}, {fleet['short']}"
    return {"machine": machine, "fleet": fleet}


def build_display(reports, fleet_id, now=None, stale_seconds=120, settings=None):
    """Return JSON-compatible display v1. All clock-dependent rules use the supplied now."""
    now = now or datetime.now(timezone.utc)
    settings = settings or {}
    desktop = settings.get("git_client") or {}
    local_ids = set(settings.get("local_repo_ids") or [])
    scopes = settings.get("baskets") or {}
    recovery = settings.get("recovery") or {}
    withheld_ids = set(settings.get("withheld_repo_ids") or [])
    unobserved = int(settings.get("unobserved_count") or 0)
    transport_config = settings.get("transport_config") or {}
    fetch_seconds = int(settings.get("fetch_seconds") or 0)
    manifests = [r["manifest"] for r in reports]
    views = sorted(machine_views(manifests, now, stale_seconds / 3600, 7),
                   key=lambda v: (v.label.casefold(), v.machine_id))
    names = {}
    for report in reports:
        names.update(report["names"])
    catalog = {rid: {"display_name": f"{v['owner']}/{v['name']}"} for rid, v in names.items()}
    rows, groups, place_groups = [], {}, {}
    labels = {view.machine_id: view.label for view in views}
    for row in build_rows(views, catalog):
        identity = names[row.repo_id]
        group_id = f"{identity['host']}/{identity['owner']}"
        group = groups.setdefault(group_id, {"id": group_id, "label": identity["owner"],
                                            "host": identity["host"], "count": 0, "attention": 0})
        place = _row_place(row, settings.get("machine_id"))
        elsewhere = (place or {}).get("machine")
        library = (f"{place['library']} on {labels.get(elsewhere, elsewhere)}" if elsewhere else place["library"]) if place else None
        place_id = (f"place/{elsewhere + '/' if elsewhere else ''}{place['library']}/{place['folder']}"
                    if place else "place/unknown")
        place = {"library": place["library"], "folder": place["folder"]} if place else None
        place_group = place_groups.setdefault(place_id, {
            "id": place_id, "label": (place["folder"] or "(directly in the library)") if place
            else "Folder not shared", "host": library if place else "Other machines",
            "count": 0, "attention": 0})
        cells = {mid: _cell(cell) for mid, cell in row.cells.items()}
        # Attention means unfinished work somewhere: stashed or worse, including work an old
        # report last showed (stale_work). A repository missing from a machine is normal, and a
        # clean copy on an old report stays "unknown" (never an all-clear) without needing
        # attention. A client must not infer this from a numeric threshold or color.
        attention = row.severity >= SEVERITY["stashed"]
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
        place_group["count"] += 1
        place_group["attention"] += int(attention)
        advice = row.advice
        if row.severity_key == "synced":
            advice = ("✓ up to date with the remote" if _remote_checked(row, now, fetch_seconds)
                      else "Clean against cached refs; remote unverified")
        rows.append({"id": row.repo_id, "name": row.name, "identity": dict(identity),
                     "namespace": identity["owner"], "group_id": group_id,
                     "place": place, "place_id": place_id,
                     "severity": row.severity, "needs_attention": attention,
                     "tags": sorted(tags), "cells": cells, "advice": advice})
    rows.sort(key=lambda r: (-r["severity"], r["name"].casefold(), r["id"]))
    machines = [{"id": v.machine_id, "label": v.label,
                 "age_seconds": age_seconds(v.observed_at, now), "freshness": v.freshness,
                 "observed_at": v.observed_at, "repository_count": len(v.repositories),
                 "tone": "success" if v.freshness == "current" else "warning"} for v in views]
    _defer_to_live_disks(rows, {m["id"]: m["label"] for m in machines})
    for row in rows:
        local = row["id"] in local_ids
        # Withholding is stated per row. A repository this machine keeps to itself looks
        # identical to one nobody has touched unless the dashboard says which it is.
        row["publication"] = {
            "published": not (local and row["id"] in withheld_ids),
            "reason": "Withheld from every transport and peer by this machine's publish basket."
                      if local and row["id"] in withheld_ids else "",
        }
        row["desktop_action"] = {
            "available": bool(desktop.get("available") and local),
            "label": f"Open in {desktop.get('label') or 'desktop Git client'}",
            "reason": (desktop.get("reason") or "Choose a desktop Git client in Settings.")
                      if local else "This repository has no observed checkout on this machine.",
        }
        row["security_action"] = {
            "available": bool(local and settings.get("security_available")),
            "label": "Check local security",
            "reason": "Read-only working files and cached outgoing history; findings stay local."
                      if local else "No locally observed checkout; peer security is not checked here.",
        }
    # The network map's policy: which machines hold copies of the same repositories, and whether
    # those copies are on the same commit. Skins draw it; they never work it out themselves.
    links = []
    ids = [machine["id"] for machine in machines]
    for index, first in enumerate(ids):
        for second in ids[index + 1:]:
            shared = differ = attention = 0
            for row in rows:
                one, two = row["cells"].get(first), row["cells"].get(second)
                if not (one and two and one["present"] and two["present"]):
                    continue
                shared += 1
                heads = ((one["facts"] or {}).get("head"), (two["facts"] or {}).get("head"))
                differ += int(all(heads) and heads[0] != heads[1])
                attention += int(row["needs_attention"])
            if shared:
                links.append({"a": first, "b": second, "shared": shared, "differ": differ,
                              "attention": attention})
    for row in rows:
        present = [cell for cell in row["cells"].values() if cell["present"]]
        heads = [(cell["facts"] or {}).get("head") for cell in present]
        # Unknown unless every copy shares its commit: a withheld head proves nothing.
        row["copies"] = {"present": len(present),
                         "heads_agree": None if not heads or None in heads else len(set(heads)) == 1}
    # Libraries under machines (the user, 2026-11-16): each machine's libraries, with how many
    # repositories each holds and how many of those copies need attention. From each copy's place,
    # or each of its folders when the machine keeps it in several.
    libraries: dict = {}
    for row in rows:
        for machine_id, cell in row["cells"].items():
            if not cell["present"]:
                continue
            folders = cell.get("copies")
            # One folder: the copy's own attention. Several: each folder's own facts, so a clean
            # backup library is not flagged for a dirty working copy in another library.
            per_library: dict = {}
            if folders:
                for copy in folders:
                    library = (copy.get("place") or {}).get("library") or ""
                    unfinished = any(copy.get(key) for key in (
                        "staged", "unstaged", "untracked", "stashes", "ahead", "behind"))
                    per_library[library] = per_library.get(library, False) or unfinished
            else:
                per_library[(cell.get("place") or {}).get("library") or ""] = cell["needs_attention"]
            disks = {((copy.get("place") or {}).get("library") or "", (copy.get("place") or {}).get("disk"))
                     for copy in (folders or [{"place": cell.get("place")}])}
            for library, attention in per_library.items():
                entry = libraries.setdefault((machine_id, library), {
                    "machine_id": machine_id, "library": library or None, "repositories": 0,
                    "attention": 0, "organizations": set(), "disk": None})
                entry["repositories"] += 1
                entry["attention"] += int(bool(attention) and not cell.get("same_disk_as"))
                entry["organizations"].add(row["namespace"])
                entry["disk"] = entry["disk"] or next((d for name, d in disks if name == library and d), None)
    library_list = [{**entry, "organizations": len(entry["organizations"])}
                    for _, entry in sorted(libraries.items(), key=lambda item: (item[0][0].casefold(), item[0][1].casefold()))]
    # The same disk seen from another machine (one box, two OSes): name the other library.
    for entry in library_list:
        entry["same_disk_as"] = [{"machine_id": other["machine_id"], "library": other["library"]}
                                 for other in library_list
                                 if entry["disk"] and other is not entry and other["disk"] == entry["disk"]]
    # Clouds: each provider the repositories come from, with its owners.
    providers: dict = {}
    for row in rows:
        host = row["identity"]["host"]
        entry = providers.setdefault(host, {"host": host, "label": PROVIDER_NAMES.get(host, host),
                                            "owners": set(), "repositories": 0, "attention": 0})
        entry["owners"].add(row["namespace"])
        entry["repositories"] += 1
        entry["attention"] += int(row["needs_attention"])
    provider_list = [{**entry, "owners": len(entry["owners"])} for entry in
                     sorted(providers.values(), key=lambda e: (e["host"] == "local", -e["repositories"]))]
    basket_notices = []
    if withheld_ids:
        basket_notices.append({"id": "withheld", "tone": "warning",
            "text": f"{len(withheld_ids)} repository(ies) on this machine are observed but not "
                    "published: no other machine can see their state, however bad it is."})
    if unobserved:
        basket_notices.append({"id": "unobserved", "tone": "neutral",
            "text": f"{unobserved} repository(ies) under your roots are excluded from observation "
                    "by this machine's observe basket and are not checked at all."})
    remote_notice = (
        f"Remotes are fetched every {_duration(fetch_seconds)}, read-only: only remote-tracking "
        "refs move, never your branches or files. Behind counts reflect the last fetch; a failed "
        "fetch keeps the last known counts and is listed under issues."
        if fetch_seconds else
        "Scheduled fetching is off, so ahead/behind use cached Git refs. A clean report does not "
        "prove that machines are on the same commit or current with the remote.")
    folder, repo, tailnet = (transport_config.get("folder"), transport_config.get("repo"),
                             transport_config.get("tailnet"))
    return {
        "contract": {"name": CONTRACT_NAME, "version": CONTRACT_VERSION},
        "product": {"name": PRODUCT_NAME, "version": VERSION, "channel": "development"},
        "generated_at": now.isoformat(), "fleet_id": fleet_id,
        "fleet_name": settings.get("fleet_name") if transport_config else None,
        "this_machine": settings.get("machine_id"),  # which column is the machine showing this page
        "summary": {"repositories": len(rows), "attention": sum(r["needs_attention"] for r in rows),
                    "machines": len(machines),
                    "current_machines": sum(m["freshness"] == "current" for m in machines),
                    "stale_machines": sum(m["freshness"] != "current" for m in machines),
                    "organizations": len({row["namespace"] for row in rows}),
                    "libraries": len(library_list), "providers": len(provider_list),
                    "copies": sum(entry["repositories"] for entry in library_list)},
        "machines": machines, "groups": sorted(groups.values(), key=lambda g: g["id"].casefold()),
        "libraries": library_list, "providers": provider_list,
        # The same rows by where they live (library, then folder): the page's default grouping.
        "place_groups": sorted(place_groups.values(), key=lambda g: (g["id"] == "place/unknown",
                                                                      g["host"].casefold(), g["label"].casefold())),
        "rows": rows,
        "map": {"links": links},
        "mark": mark_state(rows, machines, reports, settings),
        "desktop_client": {"configured": bool(desktop.get("configured")),
                           "id": desktop.get("id", ""),
                           "label": desktop.get("label", "Desktop Git client"),
                           "choices": list(desktop.get("choices") or [])},
        "issues": [{"machine_id": r["manifest"]["machine_id"],
                    "machine": r["manifest"]["machine_label"], "items": list(r["issues"])}
                   for r in reports if r["issues"]],
        "filters": [{"id": "all", "label": "All repositories"},
                    {"id": "attention", "label": "Needs attention"},
                    {"id": "dirty", "label": "Uncommitted work"},
                    {"id": "ahead", "label": "Unpushed commits"},
                    {"id": "local_only", "label": "No remote (only copy)"},
                    {"id": "copies", "label": "Several copies on one machine"},
                    {"id": "stale", "label": "Stale reports"},
                    {"id": "missing", "label": "Not reported on a machine"}],
        "notices": [{"id": "cached-refs", "tone": "neutral", "text": remote_notice},
                    {"id": "security-scope", "tone": "neutral",
                     "text": "Fleet status is not security clearance. Check security on a local repository for masked advice; commit/push actions must recheck current material."},
                    {"id": "staleness", "tone": "warning" if transport_config else "neutral",
                     "text": staleness_text(stale_seconds, transport_config)},
                    *basket_notices],
        "baskets": {"configured": bool(scopes),
                    "scopes": {scope: dict(scopes[scope]) for scope in scopes},
                    "withheld": len(withheld_ids), "unobserved": unobserved},
        "capabilities": {"observe": {"available": True, "reason": "Status observation is running."},
                         "desktop_client": {"available": bool(desktop.get("available")),
                             "reason": desktop.get("reason") or "No desktop Git client configured."},
                         "repository_actions": {"available": True, "reason":
                             "The local dashboard can run the terminal-equivalent catch-up preview. "
                             "Applying fast-forward pulls is 'gitso machine catch-up', once its plan is approved."},
                         "baskets": {"available": bool(scopes), "reason":
                             "Observe and publish baskets are configured with 'fleet baskets'; "
                             "capture requires a separately confirmed recovery location."
                             if scopes else "Basket selection is not configured on this machine."},
                         "installation": {"available": False, "reason":
                             "This is a development preview. A supported desktop installer is not available yet."},
                         "self_update": {"available": False, "reason":
                             "Updates are developer-managed. Automatic updates are not enabled."}},
        "integrations": [
            {"id": "tailscale", "label": "Tailscale live monitoring", "available": True,
             "enabled": bool(tailnet),
             "description": "Near-live reports between connected fleet machines.",
             "detail": (f"Peers asked every {_duration(int(tailnet.get('seconds') or 300))} on port "
                        f"{tailnet.get('port')}."
                        if tailnet else "Tailscale is not configured on this machine.")},
            {"id": "synced_folder", "label": "Synchronized folder", "available": True,
             "enabled": bool(folder),
             "description": "Status written into a folder your own sync client replicates.",
             "detail": (f"Written on change and every {_duration(folder['seconds'])}."
                        if folder else "No synchronized folder configured.")},
            {"id": "github", "label": "Private GitHub state repository", "available": True,
             "enabled": bool(repo),
             "description": "Durable status through your existing gh login.",
             "detail": (f"{repo['name']}: written on change and every {_duration(repo['seconds'])}."
                        if repo else "No GitHub state repository configured.")},
        ],
        "features": [
            {"id": "continuous_scan", "label": "Event-driven repository observation",
             "available": True, "enabled": True,
             "description": "Native filesystem events trigger a read-only check of the changed repository.",
             "detail": (f"{settings.get('root_count', 'Unknown number of')} configured root(s); "
                        f"checks after {settings.get('debounce_seconds', 'unknown')} seconds quiet.")},
            {"id": "remote_fetch", "label": "Scheduled remote fetch",
             "available": True, "enabled": bool(fetch_seconds),
             "description": "Read-only git fetch, so behind counts are measured against the remote.",
             "detail": (f"Every {_duration(fetch_seconds)}." if fetch_seconds
                        else "Off. Behind counts use whatever was last fetched by hand.")},
            {"id": "remote_actions", "label": "Fleet catch-up actions",
             "available": True, "enabled": True,
             "description": "Dashboard preview and terminal application share one safe policy.",
             "detail": "Preview fresh-fetches; 'gitso machine catch-up' fast-forwards only clean, behind-only local checkouts, once its plan is approved."},
            {"id": "recovery_snapshots", "label": "Unfinished-work recovery snapshots",
             "available": bool(recovery.get("location") and recovery.get("confirmed")),
             "enabled": bool(recovery.get("location") and recovery.get("confirmed")
                             and (settings.get("baskets") or {}).get("capture", {}).get("mode") != "none"),
             "description": "Explicit local capture and verified cross-machine acknowledgement.",
             "detail": ("Captures after filesystem quiet periods; another peer must verify a bundle "
                        "before it is recoverable elsewhere."
                        if (settings.get("baskets") or {}).get("capture", {}).get("mode") != "none"
                        and recovery.get("location") and recovery.get("confirmed") else
                        "Configured, but capture basket is off." if recovery.get("location") else
                        "No separately confirmed recovery location is configured.")},
        ],
    }
