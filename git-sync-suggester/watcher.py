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


def run_watch(observe, publish, interval: float = DEFAULT_INTERVAL_SECONDS,
              heartbeat: float = DEFAULT_HEARTBEAT_SECONDS, once: bool = False,
              max_cycles: int | None = None, should_stop=None, final_publish: bool = True,
              clock=time.monotonic, sleeper=time.sleep, log=print) -> WatchResult:
    """Observe on an interval; publish on semantic change or heartbeat; publish once on exit.

    `observe()` returns a manifest, `publish(manifest)` writes it. Both may raise; a failing
    cycle is reported and the loop continues, because a watch that dies on one bad cycle is
    worse than no watch at all.
    """
    result = WatchResult()
    fingerprint: str | None = None
    published_at: float | None = None

    while True:
        if should_stop is not None and should_stop():
            break
        try:
            manifest = observe()
            current = semantic_fingerprint(manifest)
            now = clock()
            if current != fingerprint:
                reason = "change"
            elif published_at is None or (now - published_at) >= heartbeat:
                reason = "heartbeat"
            else:
                reason = None
            if reason:
                publish(manifest)
                fingerprint, published_at = current, now
                result.publishes += 1
                result.reasons.append(reason)
                log(f"published ({reason}): {len(manifest.get('repositories', []))} repositor(ies)")
            else:
                log("no change")
        except Exception as exc:  # one bad cycle must not end the watch
            result.errors.append(str(exc))
            log(f"warning: observation cycle failed: {exc}")
        result.cycles += 1
        if once or (max_cycles is not None and result.cycles >= max_cycles):
            break
        if should_stop is not None and should_stop():
            break
        sleeper(interval)

    # Best effort: record the truth on the way out. This cannot guarantee an external sync
    # client uploads it before shutdown, which is exactly why an explicit `check` still matters.
    if final_publish and not once:
        try:
            manifest = observe()
            publish(manifest)
            result.publishes += 1
            result.reasons.append("final")
            log("published (final)")
        except Exception as exc:
            result.errors.append(f"final publish failed: {exc}")
            log(f"warning: final publish failed: {exc}")
    return result
