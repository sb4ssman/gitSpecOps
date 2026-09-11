# The three tiers, and what each one can actually preserve

Recorded 2026-09-11 after the user corrected the model. The tiers are **complements**; the goal
is to have all three. What has been under-stated until now is that they should not differ only
in *latency* — they should differ in **what kind of work they can rescue**.

## Today: all three carry the same thing

Every tier publishes the same v3 status manifest (salted digests and small integers). So today
the tiers differ only in how quickly and how readably that status arrives. That is the gap.

## The intended ladder

| Tier | Latency | Preserves | Answers |
|---|---|---|---|
| **Durable** — private GitHub repo | minutes | committed history + status | "what is on that machine, ever, from anywhere" |
| **Medium** — synced folder | seconds–minutes | status + **saved but uncommitted content** | "I edited and saved, then walked away" |
| **Live** — tailnet | seconds | status + **unsaved editor buffers** | "I typed something and never hit save" |

Each rung preserves strictly more and requires strictly more trust. Nothing above the first
rung may be on by default.

### Durable: a repository the app deliberately owns

Setup should *guide* naming and creating it, not merely accept a name. It is a normal private
repo the user can inspect, containing one small JSON file per machine — never cloned, written
through the Contents API. Publication conditions: on semantic change, rate-limited to the
configured interval (default 1800s) so a busy machine cannot become an API storm. A **public**
state repository is refused outright.

### Medium: saved-but-uncommitted content

Status already reports *that* there are uncommitted changes; the medium tier is where their
**content** can ride along, because a synced folder is local-speed and already trusted with the
user's files. This is the "recovery snapshot" / user's *stealth-stash* idea, and it is what makes
"my laptop died with saved work on it" recoverable.

Shape: `git diff HEAD` (staged + unstaged) plus explicitly selected untracked files, as one
patch bundle per repository, encrypted, size-capped, expiring once the real commit is published.
It must be a **separate artifact from the manifest** — the manifest stays names-free — and must
have retention, size, ignore-file, and secret-scan controls. Not built.

### Live: unsaved editor buffers — probably without a plugin

**Finding (2026-09-11):** VS Code already persists dirty editor buffers to disk for crash
recovery, at `%APPDATA%\Code\Backups\<workspace-hash>\…` (confirmed the directory exists on a
Windows machine; it was empty at the time because no buffer was dirty). If those backups are
written eagerly rather than only at exit, unsaved work can be observed by **reading files the
editor already wrote** — no extension, no editor API, nothing to install per editor version.

This is unverified in one respect that matters: whether a backup exists *before* an abrupt power
loss. Test empirically — type into an unsaved editor buffer, do not save, and watch that folder.
If backups appear within seconds, the plugin question is settled for VS Code.

A plugin would still be the answer for editors that do not persist dirty buffers, and for
intent a file cannot express (which buffer is focused, cursor position). Start by reading what
exists; do not build a plugin first.

Reading buffer content is a large privacy step beyond salted digests, so: opt-in per basket,
encrypted, size-capped, excluded from the manifest, and never published to the durable tier.

## Watchdogs: there are none, and that is deliberate

There is **no scanning**. One acknowledged inventory at startup, then the OS reports changes —
inotify on Linux, `ReadDirectoryChangesW` on Windows — and only the changed repository is
inspected. The observer blocks in the kernel while the library is quiet.

The only periodic work in a running peer:

- peer poll every 30s (a tailnet round trip, no disk)
- folder transport publish, default 300s, and only when something changed
- repo transport publish, default 1800s, same condition

The 11.2% CPU figure in older notes belongs to a five-second polling preview that no longer
exists.

## New repositories appearing in the library

**Fixed 2026-09-11.** Cloning into the library always fired filesystem events, but
`affected_repositories` maps an event only to a *known* checkout, so those events were dropped
and the repository stayed invisible until someone remembered `fleet rescan`.
`detect_new_checkouts` now walks up from an unmatched event to the enclosing directory
containing `.git`, and the peer logs it and shows it as a dashboard issue.

It deliberately **detects without adding** — membership stays an explicit act, per
detect → alert → approve. The defect was the silence, not the confirmation.

For a user whose repositories are not in one tidy folder: roots are repeatable and recursive,
discovery prunes caches and build outputs, and `init --from-archives` imports roots the archive
tool already knows.

## Baskets: choosing what a machine syncs

Not built. The requirement: pick which orgs / repo-sets a given machine participates in, without
editing JSON. Three scopes must stay distinct or the feature becomes dangerous:

1. **Observe** — what this machine watches at all.
2. **Publish** — what it shares with the fleet.
3. **Capture** — what may have *content* preserved (medium/live tiers).

Capture must never default on, and must never be implied by the other two. A basket is a named
selection over discovered repositories (by namespace, path glob, or explicit list) that a
machine subscribes to, with those three flags per subscription. Namespace groups in the
dashboard today are observed inventory, not baskets — the display contract already says so.
