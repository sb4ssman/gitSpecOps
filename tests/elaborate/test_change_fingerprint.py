"""The peer republishes only on a semantic change: the fingerprint ignores time, sees facts.

The polling `watch` loop this file once also tested was dissolved (2026-10-19 ruling): the
peer's native file events replaced it, and only its fingerprint survives.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()


from Special._sync.manifest import (branch_id, build_manifest, fleet_id_for,  # noqa: E402
                      repository_id)
from Elaborate._fleet.watcher import semantic_fingerprint  # noqa: E402

failures = []
SECRET = "ab" * 32
FLEET_ID = fleet_id_for(SECRET)
REPO_ID = repository_id("example.test", "sample-team", "watched-repo", SECRET)


def check(condition, message):
    if not condition:
        failures.append(message)


def repo(**overrides):
    base = {
        "repo_id": REPO_ID, "branch_id": branch_id("main", SECRET),
        "has_upstream": True,
        "upstream_observed_at": None, "ahead": 0, "behind": 0, "staged": 0, "unstaged": 0,
        "untracked": 0, "stashes": 0, "operation": None,
    }
    base.update(overrides)
    return base


def manifest_at(second, **overrides):
    return build_manifest(FLEET_ID, "laptop", "LAPTOP", [repo(**overrides)],
                          observed_at=f"2026-09-03T12:00:{second:02d}Z")




# --- fingerprint: time moves, facts do not -------------------------------------------
check(semantic_fingerprint(manifest_at(0)) == semantic_fingerprint(manifest_at(59)),
      "a new observation time alone changed the semantic fingerprint")
check(semantic_fingerprint(manifest_at(0)) != semantic_fingerprint(manifest_at(0, unstaged=1)),
      "an actual working-tree change did not change the fingerprint")
check(semantic_fingerprint(manifest_at(0)) != semantic_fingerprint(manifest_at(0, ahead=1)),
      "an ahead-count change did not change the fingerprint")
unordered = build_manifest(FLEET_ID, "laptop", "LAPTOP", [],
                           observed_at="2026-09-03T12:00:00Z")
check(semantic_fingerprint(unordered) == semantic_fingerprint(unordered),
      "the fingerprint is not stable for the same input")

if failures:
    for failure in failures:
        print(" -", failure)
    raise SystemExit(1)

print("ALL-CHANGE-FINGERPRINT-TESTS-PASS")
