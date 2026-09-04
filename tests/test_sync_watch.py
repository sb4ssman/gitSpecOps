"""Synthetic, offline tests for the watch loop.

The clock, sleep, observation, and publication are all injected, so these tests never wait
and never touch a real repository. What is being proven: the loop publishes on a real
change, stays quiet when nothing moved, still proves liveness on a heartbeat, survives a
failing cycle, and records a final observation on the way out.
"""

import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent.parent / "git-sync-suggester"
sys.path.insert(0, str(TOOL_DIR))

from manifest import build_manifest, repository_id  # noqa: E402
from watcher import run_watch, semantic_fingerprint  # noqa: E402

failures = []
REPO_ID = repository_id("example.test", "sample-team", "watched-repo")


def check(condition, message):
    if not condition:
        failures.append(message)


def repo(**overrides):
    base = {
        "repo_id": REPO_ID, "branch": "main", "head": "a" * 40, "upstream": "origin/main",
        "upstream_observed_at": None, "ahead": 0, "behind": 0, "staged": 0, "unstaged": 0,
        "untracked": 0, "stashes": 0, "operation": None,
    }
    base.update(overrides)
    return base


def manifest_at(second, **overrides):
    return build_manifest("laptop", "LAPTOP", [repo(**overrides)],
                          observed_at=f"2026-09-03T12:00:{second:02d}Z")


class Clock:
    """A monotonic clock the test advances by hand, one step per sleep."""

    def __init__(self, step=60.0):
        self.now, self.step = 0.0, step

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds if seconds else self.step


def drive(observations, **kwargs):
    """Run the loop over a scripted list of observations (callables or manifests)."""
    published = []
    remaining = list(observations)

    def observe():
        item = remaining.pop(0) if remaining else observations[-1]
        if callable(item):
            return item()
        return item
    clock = Clock()
    result = run_watch(observe, published.append, clock=clock, sleeper=clock.sleep,
                       log=lambda *_a, **_k: None, **kwargs)
    return result, published


# --- fingerprint: time moves, facts do not -------------------------------------------
check(semantic_fingerprint(manifest_at(0)) == semantic_fingerprint(manifest_at(59)),
      "a new observation time alone changed the semantic fingerprint")
check(semantic_fingerprint(manifest_at(0)) != semantic_fingerprint(manifest_at(0, unstaged=1)),
      "an actual working-tree change did not change the fingerprint")
check(semantic_fingerprint(manifest_at(0)) != semantic_fingerprint(manifest_at(0, ahead=1)),
      "an ahead-count change did not change the fingerprint")
unordered = build_manifest("laptop", "LAPTOP", [], observed_at="2026-09-03T12:00:00Z")
check(semantic_fingerprint(unordered) == semantic_fingerprint(unordered),
      "the fingerprint is not stable for the same input")

# --- quiet by default ----------------------------------------------------------------
result, published = drive([manifest_at(0)], max_cycles=5,
                          interval=60, heartbeat=100000, final_publish=False)
check(result.cycles == 5, f"expected 5 cycles, got {result.cycles}")
check(result.publishes == 1, f"unchanged facts published {result.publishes} times, expected 1")
check(result.reasons == ["change"], f"unexpected publish reasons: {result.reasons}")

# --- publishes on a real change ------------------------------------------------------
result, published = drive([manifest_at(0), manifest_at(1), manifest_at(2, unstaged=3),
                           manifest_at(3, unstaged=3)],
                          max_cycles=4, interval=60, heartbeat=100000, final_publish=False)
check(result.reasons == ["change", "change"],
      f"expected one initial publish and one on change, got {result.reasons}")
check(published[-1]["repositories"][0]["unstaged"] == 3,
      "the published manifest was not the changed observation")

# --- heartbeat proves liveness while nothing moves -----------------------------------
# 10 cycles at 60s covers 540s, so a 180s heartbeat must fire at 180, 360, and 540.
result, _ = drive([manifest_at(0)], max_cycles=10, interval=60, heartbeat=180,
                  final_publish=False)
check(result.reasons.count("heartbeat") == 3,
      f"a 180s heartbeat over 540s produced {result.reasons}")
check(result.reasons[0] == "change", "the first cycle should publish as a change")

result, _ = drive([manifest_at(0)], max_cycles=6, interval=60, heartbeat=0,
                  final_publish=False)
check(result.publishes == 6, f"a zero heartbeat should publish every cycle, got {result.publishes}")

# --- a failing cycle must not end the watch ------------------------------------------
def explode():
    raise RuntimeError("root vanished")

result, published = drive([manifest_at(0), explode, explode, manifest_at(3, ahead=2)],
                          max_cycles=4, interval=60, heartbeat=100000, final_publish=False)
check(result.cycles == 4, f"the loop stopped early on errors: {result.cycles} cycles")
check(len(result.errors) == 2, f"expected 2 recorded errors, got {result.errors}")
check(published[-1]["repositories"][0]["ahead"] == 2,
      "the loop did not recover and publish after transient failures")

# --- best-effort final publish -------------------------------------------------------
result, published = drive([manifest_at(0)], max_cycles=2, interval=60, heartbeat=100000)
check(result.reasons[-1] == "final", f"no final publication recorded: {result.reasons}")
check(len(published) == 2, f"expected an initial and a final publication, got {len(published)}")

result, published = drive([manifest_at(0)], once=True, interval=60, heartbeat=100000)
check(result.cycles == 1 and result.reasons == ["change"],
      f"--once should run exactly one cycle with no final republish: {result.reasons}")

published = []
calls = {"n": 0}


def observe_then_fail():
    calls["n"] += 1
    if calls["n"] > 2:
        raise RuntimeError("state dir went away")
    return manifest_at(0)


clock = Clock()
result = run_watch(observe_then_fail, published.append, clock=clock, sleeper=clock.sleep,
                   log=lambda *_a, **_k: None, max_cycles=2, interval=60, heartbeat=100000)
check(any("final publish failed" in error for error in result.errors),
      f"a failing final publish was not reported: {result.errors}")

# --- stop signal is honoured between cycles ------------------------------------------
stopping = {"now": False}


def observe_and_request_stop():
    stopping["now"] = True
    return manifest_at(0)


published = []
clock = Clock()
result = run_watch(observe_and_request_stop, published.append, clock=clock, sleeper=clock.sleep,
                   log=lambda *_a, **_k: None, max_cycles=50, interval=60, heartbeat=100000,
                   should_stop=lambda: stopping["now"])
check(result.cycles == 1, f"the stop request was not honoured promptly: {result.cycles} cycles")
check(result.reasons[-1] == "final",
      "stopping should still record a final observation before exiting")

if failures:
    print("SYNC-WATCH-TESTS FAILED:")
    for failure in failures:
        print(" -", failure)
    raise SystemExit(1)

print("ALL-SYNC-WATCH-TESTS-PASS")
