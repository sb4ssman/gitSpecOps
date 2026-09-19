# Personal fleet: every machine is a peer

Every peer observes its own repositories, serves a dashboard on loopback, and publishes status
through its configured transports. It can also pull from other peers over Tailscale. There is
no central host. Closing a peer stops that machine's observation; other peers keep working and
retain its last published state. Stale unfinished work remains visible.

## Set up a machine

Run as your normal user with Python 3.11+ and Git. Use the repository's virtual environment
when available. GitHub CLI with an existing login is required only for the GitHub transport;
connected Tailscale is required only for direct peer access. The app never manages credentials.

Before setup, inspect exactly which optional tiers are ready:

```sh
python git-sync-suggester/sync_suggester.py fleet preflight
```

This is read-only. It checks Git, the existing `gh` login, Tailscale connectivity, the loopback
dashboard port, and common existing sync-folder locations. Missing Git is a blocker; the other
tiers are simply reported as unavailable and can be added later.

```sh
python git-sync-suggester/sync_suggester.py fleet setup
```

Or configure directly, with no Tailscale:

```sh
python git-sync-suggester/sync_suggester.py fleet peer --root /path/to/library --acknowledge-initial-scan --no-tailnet
```

`--root` is repeatable. Setup names the library and requires `SCAN` before its initial recursive
inventory. `--configure-only` saves setup without starting the runtime. Another machine uses
the same fleet key, entered in setup or supplied through `--fleet-secret`; keep the key local
and carry it privately. When Tailscale is connected, setup can instead offer an explicit,
authenticated hand-off from a running peer. Starting another peer does not require any other
machine to be online.
Avoid overlapping roots or multiple checkouts with the same remote identity in this pilot.

The dashboard is normally `http://127.0.0.1:8760/` on each machine. It combines local status,
cached peer reports, and readable manifests from configured transports, newest per machine.
`dashboard --serve` is also available for legacy `init`/`check` configurations, independently
of the fleet runtime. Legacy commands use `config.json`; the peer app uses `fleet-app.json`.

## Choose complementary transports

Durable and live transports carry status. The separately confirmed medium folder also carries
opt-in saved-work snapshots; it never shares them through the GitHub state repository.
`fleet live-buffers` can explicitly inspect local VS Code backup metadata, but unsaved buffer
content is never published by this release.

- **Durable:** a private, writable GitHub state repository accessed through your `gh` login.
  The app writes one names-free v3 manifest per machine through the Contents API; it never
  clones that state repository. Creating it requires an explicit setup choice or `--create-repo`.
- **Medium:** an existing folder managed by your own sync client. No particular client is
  required; gitSpecOps does not install or configure one.
- **Live:** optional Tailscale peer discovery and pulls every 30 seconds. Peers expose GET-only
  reports and an authenticated session endpoint. Nothing is pushed to another peer. The live
  report includes readable repository identities within the authorized personal fleet.

To add or remove transports, stop the local peer and run:

```sh
python git-sync-suggester/sync_suggester.py fleet transports --folder /path/to/synced-folder --folder-seconds 300 --repo example/private-fleet-state --create-repo --repo-seconds 1800
python git-sync-suggester/sync_suggester.py fleet run
```

`--clear-folder`, `--clear-repo`, and `--clear-tailnet` remove individual integrations;
`--tailnet` enables direct peers. No transport is authoritative. Keep configuration, fleet
keys, catalogs, and SQLite databases outside synchronized state folders.

Guided setup offers durable status first. After you opt in, it uses the current `gh` login to
suggest `owner/gitspecops-fleet-state`. Enter another accessible owner/name to override it.
The walkthrough explains the app-managed `machines/` files and publication conditions.
Type `CREATE owner/name` to request creation or `USE owner/name` to approve an existing private,
writable repository. Enter skips that choice. Merely accepting a suggested name creates nothing.

Publication sends initial status and then semantic changes at each transport's minimum interval
(folder 300 seconds, GitHub 1800 seconds by default). Each transport keeps its latest pending
status during cooldown and retries failures after the interval. Pending delivery runs without
another filesystem event or Git scan. The queue is in memory; startup inventories again and
publishes current status. Do not infer remote delivery from a successful local observation.
No last-second upload is promised on shutdown or power loss.

## Observe and resume

```sh
python git-sync-suggester/sync_suggester.py fleet run
python git-sync-suggester/sync_suggester.py fleet doctor
python git-sync-suggester/sync_suggester.py fleet rescan
```

Startup performs one inventory. Linux inotify or Windows `ReadDirectoryChangesW` then triggers
targeted Git status checks only for changed repositories. There is no periodic repository scan.
New checkouts raise a notice; `fleet rescan` explicitly refreshes membership. The current peer
runtime does not implement the retired host/client timestamp-heartbeat protocol; a quiet
report's observation time can age even while its process remains reachable.

Local configuration is stored under the usual Sync Suggester config directory. Each peer has
`fleet-app.json`, `fleet.sqlite3`, and `fleet-latest.json`. `fleet --config-dir PATH ...` selects
another configuration. An OS lock prevents concurrent peers using the same configuration.
Old v1/v2/v3/v4 configurations migrate to peer v5 on resume, preserving the fleet key and taking
the default baskets (observe and publish everything, capture nothing). `host`,
`connect`, and `replicas` are retired; use `setup`/`peer` and `transports`.

## Catch up a machine safely

```sh
python git-sync-suggester/sync_suggester.py fleet catchup
python git-sync-suggester/sync_suggester.py fleet catchup --apply --yes
```

`catchup` is terminal-first: it performs a fresh, non-interactive `git fetch origin` for every
locally observed checkout, then reports exactly what it found. The default is a plan only and
does not alter a branch, index, or working file. `--apply --yes` applies only the plan entries
that are both clean and behind-only, using `git pull --ff-only`, and rechecks success against
the freshly fetched remote.

Every other state is a human decision: dirty/untracked work, ahead-only commits, divergence,
detached HEAD, no upstream, unreadable status, and a failed fetch are all reported and skipped.
Catch up never commits, pushes, stashes, resets, merges, rebases, prunes, or recurses into
submodules. It runs only while the peer is stopped; the per-configuration lock refuses a
concurrent run. Resume the peer afterward to publish the changed local status.

## Audit a large local working set

```sh
python git-sync-suggester/sync_suggester.py fleet audit
python git-sync-suggester/sync_suggester.py fleet audit --json
```

This report finds missing origins or upstreams, plain-HTTP origins, detached heads, local-only
commits, behind state, and tracked changes across every observed checkout. It changes no remote,
branch, index, or working file. Fleet-wide materialization and branch cleanup remain separate
future operations; this audit deliberately does not invent repairs for ambiguous repositories.

To seed a new library from this machine's approved working set:

```sh
python git-sync-suggester/sync_suggester.py fleet materialize --destination /new/library
python git-sync-suggester/sync_suggester.py fleet materialize --destination /new/library --apply --yes
```

The first command maps recognizable origins to `host/owner/repository` folders and reports
collisions or local-only checkouts. The second clones only destinations that were absent when
rechecked; it never replaces or updates an existing checkout. This is a local working-set
materializer, not a promise that names-free status manifests alone can discover an institution's
entire organization inventory.

## Inspect VS Code's existing unsaved buffers

```sh
python git-sync-suggester/sync_suggester.py fleet live-buffers
```

This is an explicit local inspection, not a watcher. On Windows it reads the existing VS Code
backup directory; on another platform or profile, pass `--backup-root PATH`. It reports only
metadata for backups whose URI maps beneath a configured repository root and whose buffer differs
from the saved file. It neither prints nor stores buffer content, and it sends nothing to another
machine. Publishing opt-in live buffers is a separate privacy and transport decision.

## Baskets: what this machine takes part in

```sh
python git-sync-suggester/sync_suggester.py fleet baskets
python git-sync-suggester/sync_suggester.py fleet baskets --scope observe --mode except --namespace github.com/some-owner
python git-sync-suggester/sync_suggester.py fleet baskets --scope publish --mode only --namespace github.com/some-owner
```

Roots are the filesystem boundary; baskets narrow what happens inside it, per scope:

| Scope | Effect |
|---|---|
| `observe` | whether this machine inspects the repository at all |
| `publish` | whether its status is written where other machines can read it |
| `capture` | whether its uncommitted content may be snapshotted to a separately confirmed recovery folder |

The scopes are independent and never imply one another. Widening `observe` does not widen
`publish`, and nothing widens `capture` implicitly. A non-empty capture basket is refused until
an existing, separately confirmed recovery folder is present.

Selection is by namespace (`host/owner`), with modes `all`, `none`, `only` and `except`.
Matching happens locally, from repository names that never leave the machine: a manifest carries
salted digests, so no peer can see, apply, or infer another machine's baskets.

Narrowing is never silent. A withheld repository stays on this machine's own dashboard, marked
*not published*, and the dashboard states how many repositories are withheld or unobserved.
`observe` changes apply at the next `fleet rescan` or restart; `publish` changes apply at the
next observation.

## Recover saved work and audit replacement safety

```sh
python git-sync-suggester/sync_suggester.py fleet recovery configure --location /private/sync-folder --confirm-private-location
python git-sync-suggester/sync_suggester.py fleet baskets --scope capture --mode only --namespace github.com/some-owner
python git-sync-suggester/sync_suggester.py fleet recovery status
python git-sync-suggester/sync_suggester.py fleet safe-to-wipe
```

The recovery folder is deliberately separate from the status folder and must already exist.
The peer captures selected repositories after filesystem quiet periods. A second peer that can
read the same folder verifies each checksum and writes an acknowledgement; only then does the
source call it *recoverable elsewhere*. `recovery preview` reads a named bundle without writing;
`recovery restore --yes` creates a disposable checkout, never overlays an existing working tree.
`recovery retire --yes` freshly fetches `origin` and removes a local bundle only when the fetched
upstream's tree exactly matches the bundle's staged, unstaged, and carried-file content.

`safe-to-wipe` fresh-fetches every observed repository but never changes a working tree. It
accepts a dirty checkout only when its exact current snapshot has been checksum-verified by
another peer and it has no unpushed commits. All other ambiguous states remain blockers.

## Tray and start-at-login

```sh
python git-sync-suggester/sync_suggester.py fleet tray
python git-sync-suggester/sync_suggester.py fleet autostart status
python git-sync-suggester/sync_suggester.py fleet autostart enable
python git-sync-suggester/sync_suggester.py fleet autostart disable
```

The Windows tray reads the local display contract, opens the dashboard, requests a rescan,
controls per-user start-at-login, and can run the same read-only catch-up preview as the
dashboard on a worker thread. It offers no Git mutations. Off Windows, `tray` falls
back to a foreground run. Linux also supports `fleet autostart --systemd enable` as a user
unit. Run as the interactive user so Git ownership, credentials, and sync-folder access match.
Use a durable installation location before enabling startup for a packaged build.
See [BUILD-DESKTOP.md](../packaging/BUILD-DESKTOP.md).

## Boundaries

The peer observes staged, unstaged, untracked, stashed, operation, and cached ahead/behind
facts. Its scheduled fetch is read-only toward branches and files. The explicit, stopped-peer
`fleet catchup --apply --yes` command may fast-forward clean, behind-only checkouts after a
fresh fetch; it never clones, commits, stashes, pushes, transfers unfinished files, or makes an
ambiguous Git decision.
Namespace groups in the dashboard are a display grouping, not a basket; baskets are configured
with `fleet baskets` and shown in App & setup. The dashboard can run the same fresh-fetch
catch-up preview as the terminal; applying a pull remains the explicit stopped-peer terminal
command. Cached refs do not prove exact equality between machines.

Tailscale authorization allows the configured login's untagged devices. This is a personal
fleet, not enterprise roles or isolation between OS users sharing a device. The loopback
dashboard is local to the machine, not an authentication boundary between its OS users.

All skins consume `gitspecops.fleet.display`; they must not reclassify Git facts. See
[DISPLAY-CONTRACT.md](DISPLAY-CONTRACT.md). Validate with `python tests/run_all.py` using a
supported interpreter on the claimed platform; synthetic tests do not prove actual deployment.
