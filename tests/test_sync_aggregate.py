"""Synthetic, offline tests for cross-machine aggregation: freshness, advice, rendering.

The clock is injected, so every freshness boundary is exercised exactly rather than waited
for. All repositories are invented; no real names, paths, hosts, or network calls.
"""

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent.parent / "git-sync-suggester"
sys.path.insert(0, str(TOOL_DIR))

from aggregate import (  # noqa: E402
    CURRENT,
    EXPIRED,
    STALE,
    _effective_state,
    age_phrase,
    build_rows,
    cell_text,
    freshness,
    humanize_age,
    load_manifests,
    machine_views,
    render_dashboard,
)
from folder_transport import FolderTransport  # noqa: E402
from manifest import build_manifest, repository_id  # noqa: E402

failures = []
NOW = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)
STALE_HOURS, EXPIRED_DAYS = 24, 7

IDS = {name: repository_id("example.test", "sample-team", name)
       for name in ("clean", "dirty", "ahead", "behind", "diverged", "noupstream",
                    "collide", "stashed", "busy", "peeronly")}


def check(condition, message):
    if not condition:
        failures.append(message)


def stamp(delta):
    return (NOW - delta).isoformat().replace("+00:00", "Z")


def repo(name, **overrides):
    base = {
        "repo_id": IDS[name], "branch": "main", "head": "a" * 40, "upstream": "origin/main",
        "upstream_observed_at": None, "ahead": 0, "behind": 0, "staged": 0, "unstaged": 0,
        "untracked": 0, "stashes": 0, "operation": None,
    }
    base.update(overrides)
    return base


def views_for(machines, stale_hours=STALE_HOURS, expired_days=EXPIRED_DAYS):
    """machines: list of (machine_id, label, age_delta, [repo dicts])."""
    manifests = [build_manifest(mid, label, repos, observed_at=stamp(age))
                 for mid, label, age, repos in machines]
    return machine_views(manifests, NOW, stale_hours, expired_days)


def advice_for(machines, repo_name, catalog=None):
    views = views_for(machines)
    rows = {row.repo_id: row for row in build_rows(views, catalog or {})}
    return rows[IDS[repo_name]]


# --- freshness boundaries -----------------------------------------------------------
BOUNDARIES = [
    (timedelta(seconds=0), CURRENT, "a report from this instant"),
    (timedelta(hours=23, minutes=59), CURRENT, "a 23h59m report"),
    (timedelta(hours=24), CURRENT, "a report exactly at the stale threshold"),
    (timedelta(hours=24, seconds=1), STALE, "a report one second past the stale threshold"),
    (timedelta(days=6, hours=23), STALE, "a report just under the expiry threshold"),
    (timedelta(days=7), STALE, "a report exactly at the expiry threshold"),
    (timedelta(days=7, seconds=1), EXPIRED, "a report one second past expiry"),
    (timedelta(days=400), EXPIRED, "a very old report"),
]
for delta, expected, description in BOUNDARIES:
    actual = freshness(stamp(delta), NOW, STALE_HOURS, EXPIRED_DAYS)
    check(actual == expected, f"{description} classified {actual}, expected {expected}")

for bad in (None, "", "not-a-time", 12345, "2026-13-45"):
    check(freshness(bad, NOW, STALE_HOURS, EXPIRED_DAYS) == EXPIRED,
          f"unreadable timestamp {bad!r} must be treated as expired, never current")
check(freshness(stamp(timedelta(hours=-5)), NOW, STALE_HOURS, EXPIRED_DAYS) == CURRENT,
      "a clock-skewed future report must not read as stale")

check(humanize_age(30) == "now" and humanize_age(3600 * 5) == "5h" and humanize_age(86400 * 9) == "9d",
      "humanize_age formatting changed")
check(age_phrase(30) == "just now" and age_phrase(None) == "unknown" and age_phrase(7200) == "2h ago",
      "age_phrase formatting changed")

# --- the freshness rule: silence is never good news ---------------------------------
EFFECTIVE = [
    ("synced", CURRENT, "synced"), ("synced", STALE, "unknown"), ("synced", EXPIRED, "unknown"),
    ("behind", CURRENT, "behind"), ("behind", STALE, "unknown"),
    ("unknown", STALE, "unknown"),
    ("dirty", STALE, "dirty"), ("dirty", EXPIRED, "dirty"),
    ("ahead", STALE, "ahead"), ("diverged", STALE, "diverged"),
    ("operation", EXPIRED, "operation"), ("stashed", STALE, "stashed"),
]
for state, fresh, expected in EFFECTIVE:
    actual = _effective_state(state, fresh)
    check(actual == expected,
          f"a {fresh} '{state}' report became '{actual}', expected '{expected}'")

# --- the advice matrix from the design document -------------------------------------
FRESH = timedelta(minutes=5)
OLD = timedelta(days=3)

row = advice_for([("laptop", "LAPTOP", FRESH, [repo("clean")]),
                  ("desk", "DESK", FRESH, [repo("clean")])], "clean")
check(row.severity_key == "synced", f"clean everywhere gave {row.severity_key}")

row = advice_for([("laptop", "LAPTOP", FRESH, [repo("dirty", unstaged=3)]),
                  ("desk", "DESK", FRESH, [repo("dirty")])], "dirty")
check(row.severity_key == "dirty" and "LAPTOP" in row.advice,
      f"one dirty machine gave {row.severity_key}: {row.advice}")

row = advice_for([("laptop", "LAPTOP", FRESH, [repo("ahead", ahead=2)]),
                  ("desk", "DESK", FRESH, [repo("ahead")])], "ahead")
check(row.severity_key == "ahead" and "↑2" in row.advice,
      f"ahead-only gave {row.severity_key}: {row.advice}")

row = advice_for([("laptop", "LAPTOP", FRESH, [repo("behind", behind=4)]),
                  ("desk", "DESK", FRESH, [repo("behind")])], "behind")
check(row.severity_key == "behind" and "↓4" in row.advice,
      f"behind-only gave {row.severity_key}: {row.advice}")

row = advice_for([("laptop", "LAPTOP", FRESH, [repo("diverged", ahead=1, behind=2)])], "diverged")
check(row.severity_key == "diverged" and "human" in row.advice,
      f"diverged gave {row.severity_key}: {row.advice}")

row = advice_for([("laptop", "LAPTOP", FRESH, [repo("noupstream", upstream=None,
                                                    ahead=None, behind=None)])], "noupstream")
check(row.severity_key == "unknown" and "upstream" in row.advice,
      f"no upstream gave {row.severity_key}: {row.advice}")

row = advice_for([("laptop", "LAPTOP", FRESH, [repo("collide", unstaged=1)]),
                  ("desk", "DESK", FRESH, [repo("collide", staged=2)])], "collide")
check(row.severity_key == "collision" and "LAPTOP" in row.advice and "DESK" in row.advice,
      f"the same repo dirty on two machines gave {row.severity_key}: {row.advice}")
check(row.severity > advice_for([("laptop", "LAPTOP", FRESH, [repo("collide", unstaged=1)])],
                                "collide").severity,
      "a two-machine collision must outrank a single dirty machine")

row = advice_for([("laptop", "LAPTOP", FRESH, [repo("busy", operation="rebase")])], "busy")
check(row.severity_key == "operation" and "rebase" in row.advice,
      f"an in-progress operation gave {row.severity_key}: {row.advice}")

row = advice_for([("laptop", "LAPTOP", FRESH, [repo("stashed", stashes=2)])], "stashed")
check(row.severity_key == "stashed" and "2" in row.advice,
      f"a stash gave {row.severity_key}: {row.advice}")

# stale clean peer -> unknown, never "synchronized"
row = advice_for([("laptop", "LAPTOP", FRESH, [repo("clean")]),
                  ("oldpi", "OLDPI", OLD, [repo("clean")])], "clean")
check(row.severity_key == "stale_peer" and "OLDPI" in row.advice,
      f"a stale clean peer gave {row.severity_key}: {row.advice}")
check("synchronized" not in row.advice,
      "a row with a stale peer must not claim to be synchronized")

# stale dirty / ahead peer -> the warning survives
row = advice_for([("laptop", "LAPTOP", FRESH, [repo("dirty")]),
                  ("oldpi", "OLDPI", OLD, [repo("dirty", unstaged=7)])], "dirty")
check(row.severity_key == "stale_work" and "OLDPI" in row.advice and "3d" in row.advice,
      f"a stale dirty peer gave {row.severity_key}: {row.advice}")

row = advice_for([("laptop", "LAPTOP", FRESH, [repo("ahead")]),
                  ("oldpi", "OLDPI", OLD, [repo("ahead", ahead=1)])], "ahead")
check(row.severity_key == "stale_work" and "↑1" in row.advice,
      f"a stale ahead peer gave {row.severity_key}: {row.advice}")

# an expired peer is still not silently cleaned up
row = advice_for([("laptop", "LAPTOP", FRESH, [repo("dirty")]),
                  ("oldpi", "OLDPI", timedelta(days=90), [repo("dirty", untracked=2)])], "dirty")
check(row.severity_key == "stale_work",
      f"an expired dirty peer gave {row.severity_key}, expected a surviving warning")

# --- rows, cells, ordering ----------------------------------------------------------
views = views_for([
    ("laptop", "LAPTOP", FRESH, [repo("clean"), repo("dirty", unstaged=2)]),
    ("desk", "DESK", FRESH, [repo("clean"), repo("dirty"), repo("peeronly", unstaged=1)]),
])
rows = build_rows(views, {})
check([row.severity for row in rows] == sorted((row.severity for row in rows), reverse=True),
      "rows are not ordered most-severe first")
peer_row = next(row for row in rows if row.repo_id == IDS["peeronly"])
check(peer_row.name == f"repo:{IDS['peeronly'][:8]}",
      f"a repository only a peer has should show a short stable id, got {peer_row.name}")
check(cell_text(peer_row.cells["laptop"]) == "-",
      "a machine that does not have the repository should render as absent")
named = build_rows(views, {IDS["peeronly"]: {"display_name": "peer-repo"}})
check(any(row.name == "peer-repo" for row in named), "the catalog name was not applied")

cells = {row.repo_id: row.cells for row in rows}
check(cell_text(cells[IDS["clean"]]["laptop"]) == "✓", "a clean current cell is not ✓")
check("✎2" in cell_text(cells[IDS["dirty"]]["laptop"]), "a dirty cell does not show its count")
stale_views = views_for([("oldpi", "OLDPI", OLD, [repo("clean")])])
stale_cell = build_rows(stale_views, {})[0].cells["oldpi"]
check(cell_text(stale_cell) == "? (3d)",
      f"a stale clean cell should read as unknown with its age, got {cell_text(stale_cell)!r}")

check("↕1/2" in cell_text(build_rows(views_for(
    [("laptop", "LAPTOP", FRESH, [repo("diverged", ahead=1, behind=2)])]), {})[0].cells["laptop"]),
    "a diverged cell does not show both counts")

# --- rendering ----------------------------------------------------------------------
mixed = views_for([("laptop", "LAPTOP", FRESH, [repo("clean"), repo("dirty", unstaged=1)]),
                   ("oldpi", "OLDPI", OLD, [repo("clean"), repo("dirty")])])
NAMES = {IDS["clean"]: {"display_name": "quiet-repo"},
         IDS["dirty"]: {"display_name": "loud-repo"}}
mixed_rows = build_rows(mixed, NAMES)
default_text = render_dashboard(mixed, mixed_rows, NOW)
all_text = render_dashboard(mixed, mixed_rows, NOW, show_all=True)
check("need no action" in default_text, "the folded-row summary is missing")
check("OLDPI" in default_text.split("need no action")[1].split("\n")[0],
      "the folded-row summary does not name the machine whose silence made rows quiet")
check("loud-repo" in default_text, "the exceptions view dropped a row that needs action")
check("quiet-repo" not in default_text, "the exceptions view listed a row needing no action")
check("quiet-repo" in all_text and "loud-repo" in all_text,
      "--all did not list every repository")
check("Legend" in default_text and "Machines:" in default_text, "legend/machine footer missing")

ahead_views = views_for([("laptop", "LAPTOP", FRESH, [repo("ahead", ahead=1)])])
check("no fetch has been run" in render_dashboard(ahead_views, build_rows(ahead_views, {}), NOW),
      "a shown ahead/behind count must be labelled as cached remote-tracking knowledge")
clean_views = views_for([("laptop", "LAPTOP", FRESH, [repo("clean")])])
check("no fetch has been run" not in render_dashboard(clean_views, build_rows(clean_views, {}), NOW,
                                                      show_all=True),
      "the cached-refs note appeared with no ahead/behind row on screen")
check("No machine manifests" in render_dashboard([], [], NOW), "empty transport message missing")

# --- transport reading tolerates a bad file -----------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    transport = FolderTransport(tmp)
    good = build_manifest("laptop", "LAPTOP", [repo("clean")], observed_at=stamp(FRESH))
    transport.write_own_manifest("laptop", good)
    (Path(tmp) / "machines" / "broken.json").write_text("{not json", encoding="utf-8")
    (Path(tmp) / "machines" / "leaky.json").write_text(
        json.dumps({**good, "machine_id": "leaky", "local_path": "/home/someone/secret"}),
        encoding="utf-8")
    manifests, issues = load_manifests(transport)
    check([m["machine_id"] for m in manifests] == ["laptop"],
          "a corrupt or boundary-violating manifest was not skipped")
    check(len(issues) == 2, f"expected two reported manifest issues, got {issues}")

if failures:
    print("SYNC-AGGREGATE-TESTS FAILED:")
    for failure in failures:
        print(" -", failure)
    raise SystemExit(1)

print(f"ALL-SYNC-AGGREGATE-TESTS-PASS ({len(BOUNDARIES)} freshness boundaries, "
      f"{len(EFFECTIVE)} freshness rules)")
