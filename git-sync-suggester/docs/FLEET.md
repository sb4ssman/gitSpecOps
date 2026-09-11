# Personal fleet: every machine is a peer

Every peer observes its own repositories, serves a dashboard on loopback, and publishes status
through its configured transports. It can also pull from other peers over Tailscale. There is
no central host. Closing a peer stops that machine's observation; other peers keep working and
retain its last published state. Stale unfinished work remains visible.

## Set up a machine

Run as your normal user with Python 3.11+ and Git. Use the repository's virtual environment
when available. GitHub CLI with an existing login is required only for the GitHub transport;
connected Tailscale is required only for direct peer access. The app never manages credentials.

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
and carry it privately. Starting another peer does not require any other machine to be online.
Avoid overlapping roots or multiple checkouts with the same remote identity in this pilot.

The dashboard is normally `http://127.0.0.1:8760/` on each machine. It combines local status,
cached peer reports, and readable manifests from configured transports, newest per machine.
`dashboard --serve` is also available for legacy `init`/`check` configurations, independently
of the fleet runtime. Legacy commands use `config.json`; the peer app uses `fleet-app.json`.

## Choose complementary transports

All transports currently carry status. They do not back up repository history or unfinished
file content. Saved-work capture and unsaved editor buffers are planned separate features.

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
Old v1/v2/v3 configurations migrate to peer v4 on resume, preserving the fleet key and taking
the default baskets (observe and publish everything, capture nothing). `host`,
`connect`, and `replicas` are retired; use `setup`/`peer` and `transports`.

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
| `capture` | whether its uncommitted content is snapshotted — **not implemented**, stays `none` |

The scopes are independent and never imply one another. Widening `observe` does not widen
`publish`, and nothing widens `capture` implicitly; `fleet baskets` cannot set it, and a
configuration that tries is refused rather than silently accepted as a toggle that protects
nothing.

Selection is by namespace (`host/owner`), with modes `all`, `none`, `only` and `except`.
Matching happens locally, from repository names that never leave the machine: a manifest carries
salted digests, so no peer can see, apply, or infer another machine's baskets.

Narrowing is never silent. A withheld repository stays on this machine's own dashboard, marked
*not published*, and the dashboard states how many repositories are withheld or unobserved.
`observe` changes apply at the next `fleet rescan` or restart; `publish` changes apply at the
next observation.

## Tray and start-at-login

```sh
python git-sync-suggester/sync_suggester.py fleet tray
python git-sync-suggester/sync_suggester.py fleet autostart status
python git-sync-suggester/sync_suggester.py fleet autostart enable
python git-sync-suggester/sync_suggester.py fleet autostart disable
```

The Windows tray reads the local display contract, opens the dashboard, requests a rescan,
and controls per-user start-at-login. It offers no Git mutations. Off Windows, `tray` falls
back to a foreground run. Linux also supports `fleet autostart --systemd enable` as a user
unit. Run as the interactive user so Git ownership, credentials, and sync-folder access match.
Use a durable installation location before enabling startup for a packaged build.
See [BUILD-DESKTOP.md](../packaging/BUILD-DESKTOP.md).

## Boundaries

The peer observes staged, unstaged, untracked, stashed, operation, and cached ahead/behind
facts. It never fetches, pulls, clones, commits, stashes, pushes, or transfers unfinished files.
Namespace groups in the dashboard are a display grouping, not a basket; baskets are configured
with `fleet baskets` and shown in App & setup. Recovery snapshots and remote jobs remain
unavailable until implemented. Cached refs do not prove exact equality between machines.

Tailscale authorization allows the configured login's untagged devices. This is a personal
fleet, not enterprise roles or isolation between OS users sharing a device. The loopback
dashboard is local to the machine, not an authentication boundary between its OS users.

All skins consume `gitspecops.fleet.display`; they must not reclassify Git facts. See
[DISPLAY-CONTRACT.md](DISPLAY-CONTRACT.md). Validate with `python tests/run_all.py` using a
supported interpreter on the claimed platform; synthetic tests do not prove actual deployment.
