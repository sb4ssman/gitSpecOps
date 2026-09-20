# Detecting at-risk work across the fleet

**Status:** design, not built (written 2026-09-20).

The question no other Git client can answer: **which of my repositories exist in only one place?**
A user with many repositories across many machines accumulates work that is one disk failure from
gone, and nothing surfaces it — the repository looks perfectly healthy locally.

This is the natural next group operation because the fleet already gathers every fact it needs.
It is read-only and belongs with `fleet audit`.

## The risk classes, in severity order

Two different things can be at risk, and conflating them produces useless advice:

| Class | Condition | What is lost |
|---|---|---|
| **unremoted + dirty** | no remote configured, and uncommitted changes | everything, including work never committed |
| **unremoted** | no remote configured at all | the entire repository and its history |
| **unpushed, single machine** | ahead-only commits, and no peer reports the same commits | the local commits |
| **dirty, single machine, no snapshot** | uncommitted work, capture not enrolled or not yet run | the working-tree changes |
| **single copy** | exists on one machine, but fully pushed | nothing — the remote has it. Report as information, never as an alarm. |

The last row matters: a pushed repository on one machine is **not** at risk, and calling it at risk
is how a tool teaches users to ignore it. Silence is never good news, but neither is crying wolf.

## The identity problem (the hard part)

A published manifest identifies a repository by `HMAC(fleet_secret, host/owner/name)` — deliberately
no names, paths or URLs. **A repository with no remote has no such identity**, which is precisely
the class most at risk. It cannot currently be matched across machines at all.

**Proposed: a second, remote-free identity — `HMAC(fleet_secret, <root commit sha>)`.**

- The root commit is stable for the life of the repository and identical in every clone, so two
  machines holding the same unremoted repository produce the same id without exchanging a name.
- Hashed under the fleet secret it reveals nothing, consistent with the v3 privacy boundary.
- It also strengthens the remoted case: it can detect that two checkouts are the same repository
  even when their origins disagree (after an org rename, before reconcile has run).

Known limits, to be handled explicitly rather than discovered later:

- **No commits yet** — an initialized repository with an empty history has no root commit. It gets
  no id and is reported as local-only-unidentifiable, not silently dropped.
- **Multiple root commits** (merged histories, grafted repos) — pick the earliest by commit date
  among roots reachable from the default branch, and record that the choice was ambiguous.
- **Shared root commits** — repositories created from the same template, or forks, share a root
  and would collide. Treat a root-commit match as *evidence*, not proof: require the remote
  identity to agree when one exists, and label a root-only match as "probably the same".

This is a manifest schema change, and the brief is explicit that schema-affecting work goes first
before more machines publish. It would be **schema v4** for the manifest (distinct from the config
schema, already at v4 — a naming collision worth avoiding in the implementation).

## Command shape

```sh
python git-sync-suggester/sync_suggester.py fleet at-risk
```

Read-only; no flags required. Same non-mutating guarantees as `audit`. It reports, per risk class,
which repositories qualify and on which machine, using the local catalog to name what this machine
can name and leaving the rest as opaque ids (the existing `converge` behavior — do not add a
guessing fallback).

**Staleness interacts with this directly.** A peer that has not reported recently cannot be used as
evidence that a copy exists elsewhere. "Only one machine has this" must mean *among current
reports*, and a stale peer makes the answer `unknown`, never "at risk" and never "safe".

## Why it is not just `converge` inverted

`converge` answers "what do peers have that I lack?" and resolves names through the provider seam.
This asks "what does the fleet hold in only one place?", which is a property of the whole fleet
rather than of this machine, includes repositories no provider knows about, and is the direct input
to two things already built: the capture tier (what most deserves a snapshot) and `safe-to-wipe`
(what must never be reclaimed).

## Follow-on, once it reports

- Feed the risk class into the dashboard and tray as an attention reason, through `build_display` —
  never recomputed in a skin.
- Let it *suggest* the fix per class: `archive_sync --publish` for unpushed, a named remote and a
  first push for unremoted, capture enrollment for dirty-and-alone. Suggest; do not act.
