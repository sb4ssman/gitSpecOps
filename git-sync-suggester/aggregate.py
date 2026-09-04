"""Cross-machine aggregation: freshness, per-machine cells, and the control-tower table.

Everything here except `load_manifests` is pure: it takes already-decoded manifests plus a
`now` and returns data or text. That is what makes the freshness and collision rules
testable offline with a fixed clock.

The rule that shapes this module: **a report that is not current can never produce an
"all clear".** A stale clean report becomes `unknown`, because nothing proves the machine
is still clean. A stale *dirty* or *ahead* report keeps its warning, because the last thing
we know is that unresolved work existed there. Silence is never good news.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from advice import classify_repository
from config import display_name_for
from manifest import decode_manifest

CURRENT = "current"
STALE = "stale"
EXPIRED = "expired"

# Higher wins when one row has several things to say.
SEVERITY = {
    "collision": 90,
    "operation": 80,
    "dirty": 70,
    "stale_work": 65,
    "diverged": 60,
    "ahead": 50,
    "behind": 40,
    "stashed": 30,
    "unknown": 20,
    "stale_peer": 15,
    "synced": 10,
}
# Rows at or below this need no action; the dashboard folds them away unless asked for all.
QUIET_SEVERITY = SEVERITY["stale_peer"]
# States that mean "someone left unfinished work here" — these survive going stale.
WORK_STATES = frozenset({"dirty", "operation", "diverged", "ahead", "stashed"})


def parse_timestamp(text: object) -> datetime | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def age_seconds(observed_at: object, now: datetime) -> float | None:
    moment = parse_timestamp(observed_at)
    if moment is None:
        return None
    return max(0.0, (now - moment).total_seconds())


def freshness(observed_at: object, now: datetime, stale_hours: int, expired_days: int) -> str:
    """current <= stale_hours < stale <= expired_days < expired. Unreadable time = expired."""
    age = age_seconds(observed_at, now)
    if age is None:
        return EXPIRED
    if age <= stale_hours * 3600:
        return CURRENT
    if age <= expired_days * 86400:
        return STALE
    return EXPIRED


def age_phrase(seconds: float | None) -> str:
    """Readable elapsed time for prose: 'just now', '3h ago', 'unknown'."""
    text = humanize_age(seconds)
    return {"now": "just now", "unknown": "unknown"}.get(text, f"{text} ago")


def humanize_age(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    if seconds < 60:
        return "now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // 86400)}d"


@dataclass(frozen=True)
class MachineView:
    machine_id: str
    label: str
    observed_at: str | None
    freshness: str
    age: float | None
    repositories: dict[str, dict]

    @property
    def age_text(self) -> str:
        return humanize_age(self.age)


@dataclass
class Cell:
    """One repository as seen by one machine."""
    present: bool = False
    state: str = "absent"
    effective_state: str = "absent"
    action: str = ""
    freshness: str = CURRENT
    age: float | None = None
    repo: dict = field(default_factory=dict)

    @property
    def trusted(self) -> bool:
        return self.present and self.freshness == CURRENT


@dataclass
class Row:
    repo_id: str
    name: str
    cells: dict[str, Cell]
    severity_key: str
    advice: str

    @property
    def severity(self) -> int:
        return SEVERITY.get(self.severity_key, 0)


def load_manifests(transport, skip_invalid: bool = True) -> tuple[list[dict], list[str]]:
    """Read every machine manifest from a FolderTransport. One bad file never blocks the rest."""
    manifests, issues = [], []
    for name in transport.list_manifests():
        try:
            manifests.append(transport.read_manifest(name))
        except (OSError, ValueError) as exc:
            issues.append(f"unreadable manifest {name}: {exc}")
            if not skip_invalid:
                raise
    return _newest_per_machine(manifests, issues), issues


def _newest_per_machine(manifests: list[dict], issues: list[str]) -> list[dict]:
    """One manifest per machine, keeping the most recent.

    A machine that toggles compression changes its filename, and a stale counterpart that
    failed to delete would otherwise be counted as a second machine reporting older state.
    The writers clean up after themselves; this makes that cleanup non-critical.
    """
    newest: dict[str, dict] = {}
    for manifest in manifests:
        machine = manifest.get("machine_id")
        current = newest.get(machine)
        if current is None:
            newest[machine] = manifest
            continue
        keep, drop = ((manifest, current)
                      if str(manifest.get("observed_at")) > str(current.get("observed_at"))
                      else (current, manifest))
        newest[machine] = keep
        issues.append(f"ignored an older duplicate manifest for {machine} "
                      f"(observed {drop.get('observed_at')})")
    return list(newest.values())


def split_by_fleet(manifests: list[dict], fleet_id: str | None) -> tuple[list[dict], list[dict]]:
    """Separate manifests belonging to this fleet from ones written under a different secret.

    A machine that joined with the wrong fleet secret produces valid manifests whose every
    `repo_id` differs, so it would silently appear to share no repositories with anyone. That
    reads as a data problem when it is a configuration problem, so it is called out by name.
    """
    if fleet_id is None:
        return list(manifests), []
    ours = [m for m in manifests if m.get("fleet_id") == fleet_id]
    theirs = [m for m in manifests if m.get("fleet_id") != fleet_id]
    return ours, theirs


def machine_views(manifests: list[dict], now: datetime, stale_hours: int,
                  expired_days: int) -> list[MachineView]:
    views = []
    for manifest in manifests:
        observed_at = manifest.get("observed_at")
        views.append(MachineView(
            machine_id=manifest["machine_id"],
            label=manifest.get("machine_label") or manifest["machine_id"],
            observed_at=observed_at,
            freshness=freshness(observed_at, now, stale_hours, expired_days),
            age=age_seconds(observed_at, now),
            repositories={repo["repo_id"]: repo for repo in manifest.get("repositories", [])},
        ))
    return views


def _effective_state(state: str, machine_freshness: str) -> str:
    """Apply the freshness rule to one machine's local classification."""
    if machine_freshness == CURRENT:
        return state
    return state if state in WORK_STATES else "unknown"


def _row_advice(name: str, cells: dict[str, Cell], views: list[MachineView]) -> tuple[str, str]:
    """Cross-machine advice for one repository. Returns (severity_key, text)."""
    label = {view.machine_id: view.label for view in views}
    present = [(mid, cell) for mid, cell in cells.items() if cell.present]
    if not present:
        return "unknown", "no machine reports this repository"

    def machines_with(*states: str) -> list[tuple[str, Cell]]:
        return [(mid, cell) for mid, cell in present if cell.effective_state in states]

    dirty = machines_with("dirty", "operation")
    if len(dirty) > 1:
        names = ", ".join(label[mid] for mid, _ in dirty)
        return "collision", f"⚠ COLLISION: uncommitted work on {names}"
    if dirty:
        mid, cell = dirty[0]
        if cell.state == "operation":
            where = f"finish {cell.repo.get('operation')} on {label[mid]}"
            return ("operation" if cell.trusted else "stale_work",
                    where if cell.trusted else f"last known {where} ({age_phrase(cell.age)})")
        if cell.trusted:
            return "dirty", f"STOP: uncommitted work on {label[mid]}"
        return "stale_work", (f"last known uncommitted work on {label[mid]} "
                              f"({age_phrase(cell.age)})")

    diverged = machines_with("diverged")
    if diverged:
        mid, cell = diverged[0]
        return "diverged", f"↕ diverged on {label[mid]} — human decision"

    ahead = machines_with("ahead")
    if ahead:
        mid, cell = ahead[0]
        count = cell.repo.get("ahead") or 0
        suffix = "" if cell.trusted else f" (last seen {age_phrase(cell.age)})"
        return ("ahead" if cell.trusted else "stale_work",
                f"PUSH {label[mid]} ↑{count}{suffix}")

    behind = machines_with("behind")
    if behind:
        mid, cell = behind[0]
        return "behind", f"PULL {label[mid]} ↓{cell.repo.get('behind') or 0}"

    stashed = machines_with("stashed")
    if stashed:
        mid, cell = stashed[0]
        return "stashed", f"review {cell.repo.get('stashes')} stash(es) on {label[mid]}"

    unknown = machines_with("unknown")
    current_unknown = [(mid, cell) for mid, cell in unknown if cell.freshness == CURRENT]
    if current_unknown:
        # A machine that reported just now and still cannot name an upstream is a real gap.
        if len(current_unknown) == len([1 for _, cell in present if cell.trusted]):
            return "unknown", "no upstream configured"
        return "unknown", "upstream unknown on " + ", ".join(
            label[mid] for mid, _ in current_unknown)
    if unknown:
        # Everything anyone reported recently is clean; some machine simply has not checked in.
        names = ", ".join(sorted({label[mid] for mid, _ in unknown}))
        return "stale_peer", f"✓ current; {names} unknown"
    return "synced", "✓ synchronized"


def build_rows(views: list[MachineView], catalog: dict[str, dict]) -> list[Row]:
    repo_ids = sorted({repo_id for view in views for repo_id in view.repositories})
    rows = []
    for repo_id in repo_ids:
        cells: dict[str, Cell] = {}
        for view in views:
            repo = view.repositories.get(repo_id)
            if repo is None:
                cells[view.machine_id] = Cell()
                continue
            state, action = classify_repository(repo)
            cells[view.machine_id] = Cell(
                present=True,
                state=state,
                effective_state=_effective_state(state, view.freshness),
                action=action,
                freshness=view.freshness,
                age=view.age,
                repo=repo,
            )
        name = display_name_for(repo_id, catalog)
        severity_key, advice = _row_advice(name, cells, views)
        rows.append(Row(repo_id=repo_id, name=name, cells=cells,
                        severity_key=severity_key, advice=advice))
    rows.sort(key=lambda row: (-row.severity, row.name.lower()))
    return rows


def cell_text(cell: Cell) -> str:
    """Compact per-machine cell: what that machine last reported, with its age when not current."""
    if not cell.present:
        return "-"
    repo = cell.repo
    dirty = sum(int(repo.get(key) or 0) for key in ("staged", "unstaged", "untracked"))
    ahead, behind = repo.get("ahead") or 0, repo.get("behind") or 0
    parts = []
    if repo.get("operation"):
        parts.append(f"⚠{repo['operation']}")
    if dirty:
        parts.append(f"✎{dirty}")
    if ahead and behind:
        parts.append(f"↕{ahead}/{behind}")
    elif ahead:
        parts.append(f"↑{ahead}")
    elif behind:
        parts.append(f"↓{behind}")
    if int(repo.get("stashes") or 0):
        parts.append(f"⚑{repo['stashes']}")
    if not parts:
        parts.append("?" if cell.effective_state == "unknown" else "✓")
    if cell.freshness != CURRENT:
        parts.append(f"({humanize_age(cell.age)})")
    return " ".join(parts)


def render_dashboard(views: list[MachineView], rows: list[Row], now: datetime,
                     show_all: bool = False, foreign: list[dict] | None = None,
                     stale_hours: int = 24, expired_days: int = 7) -> str:
    """The control-tower table: one column per machine, one advice column.

    By default this is an exceptions view — rows nothing can be done about are folded into
    a counted summary line. The summary still names any machine whose silence is the reason
    a row is quiet, so a folded row is never mistaken for a proven all-clear.
    """
    if not views:
        return "No machine manifests found. Run 'check' with a state directory first."
    shown = rows if show_all else [row for row in rows if row.severity > QUIET_SEVERITY]
    hidden = [row for row in rows if row not in shown]
    headers = ["Repository"] + [view.label for view in views] + ["Advice"]
    body = [
        [row.name] + [cell_text(row.cells[view.machine_id]) for view in views] + [row.advice]
        for row in shown
    ]
    widths = [len(header) for header in headers]
    for line in body:
        widths = [max(width, len(value)) for width, value in zip(widths, line)]
    render = lambda values: "  ".join(v.ljust(w) for v, w in zip(values, widths)).rstrip()
    lines = [render(headers), "  ".join("-" * w for w in widths)]
    lines.extend(render(line) for line in body)
    if not body:
        lines.append("(nothing needs attention)" if rows else "(no repositories reported)")
    lines.append("")
    if hidden:
        quiet_machines = sorted({view.label for view in views if view.freshness != CURRENT})
        summary = f"{len(hidden)} repositor(ies) need no action (use --all to list them)"
        if quiet_machines:
            summary += (f" — clean on every current machine, but "
                        f"{', '.join(quiet_machines)} has not reported, so their state there "
                        f"is unknown, not proven clean")
        lines.append(summary)
    lines.append("Machines: " + ", ".join(
        f"{view.label} {view.freshness} ({age_phrase(view.age)})" for view in views))
    # Machine freshness and remote freshness are different things: a manifest written a
    # second ago says nothing about how old its remote-tracking refs are. Only warn about the
    # counts that are actually cached, and say how stale they are when it is known.
    unfetched = [
        cell for row in shown for cell in row.cells.values()
        if cell.present and (cell.repo.get("ahead") or cell.repo.get("behind"))
        and freshness(cell.repo.get("upstream_observed_at"), now,
                      stale_hours, expired_days) != CURRENT
    ]
    if unfetched:
        never = sum(1 for cell in unfetched if not cell.repo.get("upstream_observed_at"))
        detail = ("no fetch has been run" if never == len(unfetched)
                  else f"{never} never fetched, the rest last fetched over {stale_hours}h ago")
        lines.append(f"Note: {len(unfetched)} ↑/↓ count(s) come from cached remote-tracking "
                     f"refs ({detail}), so they may be out of date. Run check --fetch to "
                     "refresh them.")
    for manifest in foreign or []:
        lines.append(
            f"⚠ {manifest.get('machine_label') or manifest.get('machine_id')} published under a "
            f"different fleet secret (fleet {manifest.get('fleet_id')}) and is excluded — "
            "re-run init on that machine with this fleet's secret.")
    lines.append("Legend: ✓ clean  ✎ uncommitted  ↑ ahead  ↓ behind  ↕ diverged  "
                 "⚑ stash  ⚠ attention  ? unknown  - not present")
    return "\n".join(lines)
