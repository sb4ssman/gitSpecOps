"""Visible polling watch: republish this machine's manifest only when the facts change.

Two properties matter more than cleverness here.

**It must not churn.** A manifest rewritten every few seconds would make a cloud-sync
client upload constantly and would bury the one write that mattered. So a cycle publishes
only when the *semantic* fingerprint of the observation changes, plus a periodic heartbeat
that proves this machine is alive even while nothing moves.

**It must be testable without waiting.** The loop takes its observation, publication,
clock, and sleep as parameters, so the tests drive years of behavior in milliseconds and
this file has no hidden dependency on real time.

The loop never mutates an observed repository — it only re-runs the same read-only
observation `check` performs.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

DEFAULT_INTERVAL_SECONDS = 60
DEFAULT_HEARTBEAT_SECONDS = 3600


@dataclass
class WatchResult:
    cycles: int = 0
    publishes: int = 0
    reasons: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def semantic_fingerprint(manifest: dict) -> str:
    """A stable digest of everything except when the observation happened.

    `observed_at` moves every cycle; if it counted, every cycle would look like a change
    and the heartbeat rule would be meaningless.
    """
    repositories = sorted(manifest.get("repositories", []), key=lambda repo: repo["repo_id"])
    return json.dumps(
        {"machine_id": manifest.get("machine_id"),
         "machine_label": manifest.get("machine_label"),
         "repositories": repositories},
        sort_keys=True,
    )


