# Change detection without a daemon

_Decided with the user 2026-09-03. The ask was "a watchdog or series of watchdogs that can detect
changes and report to gitSpecOps so we don't need any running junk at all."_

## The honest position

"Detect changes with nothing running" is achievable for **committed** state and impossible for
**uncommitted** state. Both halves matter.

- **Committed state: git already ships the watchdog.** Hooks cost nothing when idle and fire
  exactly when semantic state changes. `post-commit`, `post-checkout`, `post-merge` and
  `post-rewrite` cover essentially every committed-state transition. (`reference-transaction`
  catches every ref change but is far too chatty — do not use it.) Note there is a `pre-push` hook
  but **no `post-push`**, so "I pushed" is observed just before it happens.
- **Uncommitted state: nothing can do this without a process.** Editing a file runs no git, so no
  hook fires. inotify, FSEvents and ReadDirectoryChangesW all require a live process holding the
  watch; there is no OS primitive for "wake me when this directory changes" that survives without
  one. Any claim otherwise is wrong.

## Why the gap is acceptable

The freshness model already makes an event-only setup *honest rather than wrong*. A machine that
has not reported degrades to **unknown**, never to **clean** — that rule is built and tested
(`_effective_state`, `WORK_STATES`). So a hook-only deployment says "desktop has not reported
since its last commit", which is true and useful. A timer improves the *resolution* of dirty-state
reporting; it is not required for correctness.

## The design

Tiers that fall back, not parallel watchers that can disagree. Several overlapping watchdogs add
failure modes and give two sources of truth; one mechanism with clear degradation is better.

| Tier | Mechanism | Idle cost |
|---|---|---|
| 0 | every gitSpecOps command republishes | free; already true |
| 1 | git hooks via a chained global `core.hooksPath` | **zero** |
| 2 | *optional* OS timer (systemd user timer / launchd / Task Scheduler) | the OS scheduler runs anyway |
| 3 | `watch`, while actively working at that machine | only while chosen |

Tiers 0+1 alone give a correct system.

## Hazards any hook implementation must handle

- **`core.hooksPath` overrides per-repo hooks.** Setting it globally silently breaks husky,
  pre-commit, lefthook, and any repository's own hooks. The dispatcher **must** look for the
  repository's own `.git/hooks/<name>` and run it.
- **Never fail the user's git command.** Always exit 0. A status tool that blocks a commit is
  worse than no status tool.
- **Never do network I/O in a hook.** This is the hard constraint on the repo transport: a Contents
  API round trip inside `git commit` is unacceptable. The hook writes local state (milliseconds);
  upload happens on the next gitSpecOps run, from a detached one-shot, or on the optional timer.
  A short-lived spawned process is not a daemon.
- Hooks fire inside the user's git process, so keep the work bounded and local.

## Status

Not implemented. Tier 0 exists today. Tier 1 is the next piece of work and is what makes the
"no running junk" goal real; Tier 3 (`watch`) already exists for the live case.
