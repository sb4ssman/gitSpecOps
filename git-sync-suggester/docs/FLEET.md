# Live personal fleet

The foreground fleet app observes your repositories and serves a browser dashboard. Run it
as your normal user in a terminal or VS Code. Nothing installs a service or startup task.
Closing the app stops observation; the host's SQLite database survives restarts.

Prerequisites on **every machine**: Python 3.11+, Git, an already-authenticated `gh`, and
connected Tailscale. The app checks the existing `gh auth status`; it never logs in, changes
accounts, reads tokens, or sends a GitHub credential to another machine.

## Start the host

For an interactive walkthrough:

```sh
python3 git-sync-suggester/sync_suggester.py fleet setup
```

Or configure and start directly:

```sh
python3 git-sync-suggester/sync_suggester.py fleet host --root /path/to/Github --acknowledge-initial-scan
```

The app prints a numeric Tailscale dashboard URL, normally `http://100.x.y.z:8765/`.
It binds **only** that interface. HTTP travels inside Tailscale's encrypted connection.
Use the printed numeric URL: the pilot rejects other HTTP Host headers.

The server verifies the TCP peer with `tailscale whois`, allows only the configured host
Tailscale user's untagged devices, and binds each report to that peer's stable node ID.
Changing a hostname does not change the report identity. Removing and re-enrolling a
Tailscale device may change it and requires reviewing the saved app configuration.

This is personal-fleet authorization. It does not distinguish different OS users sharing
one Tailscale node, and it is not a public HTTP service or enterprise role system.

## Connect another development checkout

The current deployment is a developer preview, so another machine needs its own checkout of
this repository at the same revision. A source-download endpoint was briefly prototyped and
removed: an arbitrary ZIP plus a Python command is not acceptable product onboarding.

From the checkout in a terminal:

```powershell
python git-sync-suggester/sync_suggester.py fleet connect --server http://100.x.y.z:8765 --root "<library-root>" --acknowledge-initial-scan
```

Replace the URL and root with the actual values. `--root` can be repeated. The app validates
that the directories exist. It obtains the fleet identity over the authenticated Tailscale
connection; no copying secrets or configuring SSH is needed. Observe disjoint roots without
multiple checkouts of the same origin: duplicate identities currently stop a report rather
than silently discard one worktree.

`fleet setup` offers the tailnet peers that are actually serving on port 8765, so the URL
normally does not have to be typed. If nothing is serving it says so and names the machines it
can see, because "the host app is not running" is the usual reason enrolment fails — and the
old prompt reported that as a bare connection error.

## Keep it running: the tray and start-at-login

The app is a foreground process. If nothing keeps it alive, the fleet goes dark the moment a
terminal closes, every observer's report goes nowhere, and the dashboard is simply refused.

```sh
python git-sync-suggester/sync_suggester.py fleet tray        # run behind a tray icon
python git-sync-suggester/sync_suggester.py fleet autostart status
python git-sync-suggester/sync_suggester.py fleet autostart enable
python git-sync-suggester/sync_suggester.py fleet autostart disable
```

The tray icon shows one reported state — grey starting, green clear, amber attention, red
cannot read the dashboard — with the counts in its tooltip and menu. Every number comes from
the host's display document; the tray classifies nothing itself and refuses an unrecognized
contract version rather than guessing. Its menu opens the dashboard, requests a `rescan`,
toggles start-at-login, and quits. It offers **no** Git actions.

`tray` falls back to a plain foreground run wherever no stdlib tray exists (Linux, macOS), so
the same registered command works on every machine. On a headless Linux host use
`fleet autostart --systemd enable` instead; note that without `loginctl enable-linger` a user
unit still runs only while you are logged in.

Start-at-login is **per-user, never system-wide and never a service**: the app must run as the
interactive user so Git ownership, the `gh` login, the Tailscale identity and any synchronized
folder are the ones you actually use. It is reversible from the same command or the tray menu.

## Resume or diagnose

```sh
python3 git-sync-suggester/sync_suggester.py fleet run
python3 git-sync-suggester/sync_suggester.py fleet doctor
```

Use `python` on Windows. Configuration is separate from legacy `init`:
`fleet-app.json` under the usual Sync Suggester config directory. The host also keeps
`fleet.sqlite3`; every observer keeps `fleet-latest.json`. These files stay outside the repo.
`fleet --config-dir PATH ...` selects another directory. An OS file lock prevents two app
instances from using the same setup concurrently. Edit the saved config while stopped to
change roots, label, debounce time, or replica schedule. Do not copy another device's config.

Startup performs one recursive inventory. Afterward Linux inotify or Windows
`ReadDirectoryChangesW` blocks in the kernel while the library is quiet. A filesystem event is
debounced for 0.75 seconds and runs Git status commands only in the affected known repository.
There is no periodic inventory or repository-status scan. A 30-second authenticated heartbeat sends
only a timestamp so an online observer remains current without touching its repositories or
resending its report. The
browser refreshes every three seconds. Reports older than 120 seconds are stale; unresolved
dirty/ahead/stashed work stays visible. No last-second upload is promised on shutdown or power loss.

Setup names each recursively inventoried root and requires an explicit `SCAN` acknowledgement.
The equivalent direct command requires `--acknowledge-initial-scan`. Existing polling-preview
configuration migrates automatically on its next start. Adding or removing repositories requires
one deliberate local inventory request while the app is running:

```sh
python3 git-sync-suggester/sync_suggester.py fleet rescan
```

Use `python` on Windows. This request does not enable a schedule. The dashboard's App & setup view
reports event observation and integration status.
The standard dashboard starts in dark mode and remembers the light/dark choice. It also remembers
which organization groups are collapsed across live refreshes and browser reloads.

The desktop-preview PyInstaller recipe is documented in [BUILD-DESKTOP.md](../packaging/BUILD-DESKTOP.md).
It produces an OS-specific one-folder application with embedded Python and dashboard assets. It is
build input for the signed installer, not itself a public installer.

## Scheduled replicas

Optional flags at setup:

```sh
--replica-folder /path/to/already-synced-folder --folder-seconds 300
--replica-repo SomeOrganization/private-fleet-state --github-seconds 1800
```

Both may be configured as replicas of the same fleet. The live host remains authoritative.
Any accessible owner/org is accepted, independently of the owners of observed repositories.
The GitHub repo must be private and writable by the active `gh` login. Setup can create it only
after the explicit interactive choice or `--create-replica-repo`; otherwise it must already exist.
Afterward all state-repo reads and writes happen only on its
configured schedule; the first runtime slot is one full interval after app startup. Failed
slots wait another interval. Source-repository fetches are not part of this loop.

To add replicas to an existing setup, stop its running app and use:

```sh
python3 git-sync-suggester/sync_suggester.py fleet replicas \
  --folder /path/to/existing/synced-folder --folder-seconds 300 \
  --repo SomeOrganization/private-fleet-state --create-repo --github-seconds 1800
python3 git-sync-suggester/sync_suggester.py fleet run
```

Creation is private and occurs only when `--create-repo` is supplied. `--clear-folder` and
`--clear-repo` remove either optional level from the local configuration.

Each device replicates only its own **privacy-minimized v3 manifest**, not readable names,
local paths, source, or diffs. The live tailnet report separately includes host/owner/name
so the dashboard can display a readable tree. Do not place `fleet-app.json` or the SQLite
database in the replica folder. Obsidian or another sync client must already be configured
to replicate the folder and JSON/gzip files; the app does not install or operate that client.

Replicas currently provide saved manifests, **not automatic failover** or a second writable
authority. The legacy folder/GitHub tools can read these manifests when configured with the
same fleet key. A guided no-Tailscale mode, merged replica dashboard, commit-triggered-only
publication, and persisted scheduling across app restarts remain follow-up work.

## Interface boundary

The browser consumes the versioned `gitspecops.fleet.display` contract. Business logic emits
explicit status, attention, tone, tags, notices and capabilities. The standard UI only renders
and filters those fields. A future LCARS skin can replace the presentation without copying Git
classification or freshness rules. See [DISPLAY-CONTRACT.md](DISPLAY-CONTRACT.md).

## What this pilot does and does not establish

- Observes staged, unstaged and untracked counts, stashes, operations, and cached ahead/behind.
- Groups the inventory by namespace. These groups are not yet configurable basket subscriptions.
- Shares status and repo names within the authorized personal tailnet fleet.
- Never fetches, pulls, clones, commits, stashes, pushes, or transfers unfinished source files.
- Cached refs do not establish exact commit equality between machines. Different edits with
  unchanged counts remain "dirty" without producing a new content snapshot.
- Custom baskets, repository actions, remote jobs and recovery snapshots remain separate work.
  The dashboard shows their availability but offers no nonfunctional toggles.

## Validation

`python3 tests/run_all.py` includes a real native-event/targeted-Git check plus synthetic checks for device/fleet impersonation refusal,
stale dirty reports, old-report rejection, malformed report rejection, browser-origin/Host
checks, replica clocks/backoff, and archive privacy. A live host smoke check should verify the
HTML page, static assets and dashboard API. Testing actual Windows observation still requires
running an observer on Windows; a passing synthetic test does not substitute for it.
