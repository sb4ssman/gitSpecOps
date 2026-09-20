# Architecture: the layer stack

**Status:** agreed direction 2026-09-20, migration not started. This describes the **target**;
[`../README.md`](../README.md) "Repo Shape" still describes what is on disk today.

## The model

Everything here is **git Special Operations**: careful, cross-platform, prior-auth-first tooling
for people with far too many repositories. It is organized as a strict stack, each layer built
from the one below.

```
platform/    cross-platform plumbing that is not git at all
basic/       one careful wrapper per git operation, and pure git logic
providers/   the only host-aware layer (GitHub today, others later)
special/     many repos, one machine    — archive updater, org duplicator
elaborate/   many machines, over time   — sync suggester, fleet, capture
app/         tray first, web second     — holds no policy
```

with `tests/`, `build/` and `docs/` running parallel to the stack rather than inside it.

**The one rule that makes it an architecture and not a filing cabinet:**

> A layer may import only layers strictly below it. Never sideways into a sibling tool, never
> upward. Enforced by a test that reads the imports, not by good intentions.

That rule is what makes every other property below achievable rather than aspirational.

## What each layer is

### `platform/` — not git

Console encoding, state directories, atomic writes, subprocess timeouts, path handling. Knows
nothing about git or any host. This is where *cross-platform first* is actually implemented: the
cp1252 glyph defect, the Windows `st_dev == 0` trap, and flush-the-log all live at this level, so
they are solved once rather than re-learned per tool.

### `basic/` — basic really means basic

One careful wrapper per git operation — fetch, pull `--ff-only`, push (non-force), status, clone,
rev-list — plus the pure logic over their results. "Intelligently wrapped" means each wrapper
carries the lessons this repository has already paid for:

- a timeout, always; nothing blocks unbounded
- forced non-interactive (`GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=never`) so an expired
  credential fails in under a second instead of hanging on an invisible prompt
- a structured result, never scraped text
- no invented flags: fast-forward-only is explicit, force is not available

**`basic/` is git-agnostic by construction — it never knows what host a remote is on.** That is
not a wish; it is the layer rule doing the work, since `basic/` cannot import `providers/`.

*This layer fixes real duplication.* There are currently two independent git subprocess wrappers —
`shared/git_facts.run_git` and `gh_common.run_command` — with separately-evolved timeout and
environment handling. They become one.

### `providers/` — where host-awareness is quarantined

The seam that knows GitHub exists: `gh` invocation, org enumeration, repo creation, node ids,
rename following, and later any other host. `basic/remote_identity` parses a URL into canonical
host/owner/name with no network and no auth; `providers/` maps that host to an implementation.

**Prior-auth-first lives here.** This layer shells out to CLIs the user has already logged into.
It stores no token, writes no credential file, configures no keyring, and never prompts. If `gh`
is not authenticated, host-aware features decline — they do not fall back to asking for a secret.

**This layer is how "git-agnostic ultimately" actually gets done**, and it is the main engineering
payoff of the migration. Today the org duplicator's GitHub-ness is smeared through its own
`gh_remote.py`; once host-aware calls can only live in `providers/`, whatever remains of the tool
is host-neutral *because the import test says so*. Multi-host support stops being a rewrite and
becomes a second provider.

### `special/` — many repos, one machine

Archive updater and org duplicator. They compose `basic/` operations over a set of repositories on
the machine they are running on. **A `special/` operation never knows another machine exists.**

### `elaborate/` — many machines, over time

Sync Suggester: observation, manifests, transports, the fleet protocol, capture and recovery. This
is the only layer that knows about peers, staleness, or history across time.

The split between `special/` and `elaborate/` is mechanical rather than a judgment call: *does
this operation need to know about another machine, or about the past?* If no, it is special. That
is also the only condition under which an operation legitimately moves between the two — growing
more complicated is not one.

### `app/` — tray first, web second

The tray is the primary surface: glance at it, see that repositories need attention. The dashboard
is second. Both are skins. The app **holds no policy** — it does not classify git state, does not
decide what is safe, and refuses a display contract version it does not recognize rather than
reinterpreting facts. Everything it offers is an operation declared by a lower layer.

## Operations declare themselves

The layer stack says where code lives. It does not, by itself, stop a mutating operation from
being documented as read-only — which is exactly the failure this repository just spent two
sessions correcting. So each operation in `special/` and `elaborate/` carries a descriptor:

```python
Operation(
    name="catchup",
    reads=("local git", "fleet reports"),
    mutates=("working tree: fast-forward only",),
    confirm="--apply --yes",
    schedulable=False,          # may a launcher or scheduled task emit it?
    beside_live_peer=False,     # may it run while the peer is observing?
)
```

Three things follow, and they are the point:

1. **The safety invariants become tests instead of prose.** "Nothing reachable from the
   observation path mutates" and "no scheduled or launcher-emitted command mutates" are currently
   asserted by one hand-written test per case, and by paragraphs everywhere else. They become one
   assertion over the descriptors.
2. **The app enumerates operations generically** instead of hardcoding a menu, which is what
   "the tray is a skin" requires to stay true as operations multiply.
3. **The family becomes inspectable** — `list operations` is a real command, and the catalogue in
   the docs can be generated rather than hand-maintained and drifting.

This is the Basic/Special/Elaborate intuition expressed as **data rather than directories**, for
the part of it that genuinely varies over time.

## Migration, in phases that each end green

Not one move. Each phase leaves a passing suite and a working tree.

1. **`platform/` + `basic/`.** Consolidate the two git subprocess wrappers into one; move console,
   state dirs, atomic writes. No tool folder moves yet — they import downward instead. Highest
   value, lowest risk, and it repays immediately by deleting duplication.
2. **`providers/`.** Move `gh_cli`, `remote_provider`, `provider_github`, and the org duplicator's
   `gh` calls. Add the import-direction test here, because this is the layer whose boundary is
   worth the most.
3. **`special/` and `elaborate/`.** Move the tool folders. Update `LAUNCHER_SPECS`, `_paths.py`,
   `tests/_bootstrap.py`, and every path in the brief and docs.
4. **`app/` and `build/` to the top level.**
5. **Operation descriptors and the invariant tests.**

## Sequencing: this precedes enrolling machines

`fleet_autostart.py` writes an **absolute resolved path** to `fleet_app.py` into the Windows
registry Run key, the XDG `.desktop` file, and the LaunchAgent plist. Moving that file breaks
start-at-login on every enrolled machine — and it breaks it *silently*: the app simply stops
coming back after a reboot, which is the hardest class of failure to notice in a tool whose job is
to notice things.

So the migration goes **before** the three-machine bring-up, not after. Enrolling first would mean
re-running autostart on every machine afterward, on the exact schedule where a missed one looks
like a fleet bug rather than a stale path.

## Open naming question

The repository is *git Special Operations*, and a middle layer named `special/` collides with
that. Options: keep the names and rely on context; or name the layer folders `ops-basic/`,
`ops-special/`, `ops-elaborate/`; or rename the middle layer to something like `suites/`. Worth
deciding before phase 3, since it is the phase that creates the directory.
