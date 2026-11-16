# Personal fleet: every machine is a peer

Every peer observes its own repositories, serves a dashboard on loopback, and publishes status
through its configured transports. It can also pull from other peers over Tailscale. There is
no central host. Closing a peer stops that machine's observation; other peers keep working and
retain its last published state. Stale unfinished work remains visible.

## The tray and the map

One tray icon, one colour, one meaning:

| Colour | Means |
|---|---|
| Green | This machine and the fleet are in order. |
| Amber | Something waits for one decision from you. |
| Red | Something is wrong; the tooltip says what. |

Double-click opens the map in your browser, served only on this computer. Right-click to rescan,
preview a catch-up, start at sign-in, or quit.

The map shows your machines and the copies they hold. Copies of the same repository line up
across machines, so "ahead here, behind there, missing on that one" is visible at a glance.
Switch views: a zoomable map of clouds and machines; machines together; libraries; one
organization across machines; one repository across machines. Choose any machine as the point
of view. The **Security** tab scans the repositories you tick, and shows each scanner you could
add with the command that installs it on your system.

## How the fleet shares

Every machine observes itself and writes **one file that it alone owns**; no machine is in charge
of another. That single-writer rule is why there is no conflict-resolution code anywhere here.

| Way to share | What carries the status | Needs | Gives you |
|---|---|---|---|
| **Tailscale** | your machines, directly | Tailscale | near-real-time; readable machine names |
| **A synced folder** | a folder your sync client already replicates | any sync client | fast; no account |
| **A managed repository** (experimental, untested) | a private GitHub repository, never cloned | your `gh` sign-in | status kept while every machine is off |

Use as many as you can: each is another place a machine leaves its last report.

```sh
gitso machine          # this machine's library folders
gitso fleet             # join or start a fleet; choose how to share
gitso fleet suggest      # every machine, as text
gitso tray                    # the peer behind a tray icon, with the map
gitso serve-web               # the map without a tray
```

**The map is local and needs nothing else running.** It is served on this computer only, from
whatever status files it can read. A laptop shut for a week still appears, with its last known
state and an honest "three days old". With your consent, the map can also be opened from your own
Tailscale devices, and only those.

**What crosses the wire.** Repositories are identified by `HMAC-SHA256(fleet key,
host/owner/name)`, or for one with no usable remote, an HMAC of its root commit, so the only copy
of something is still on the map. A record can also name the repository, its branch and its
commit, so every machine can show what the others hold, and that is chosen **per connection**:
setup asks for each one, with Tailscale named by default (only your own devices) and a synced
folder and the state repository carrying unnamed ids by default (their provider could read
names). A fleet set up before this keeps its one fleet-wide setting (`--withhold-names` turns it
off) until a connection is given its own. Never shared, either way: local paths, URLs, file names,
diffs, commit messages or contents. A synced folder's provider can read whatever the status
carries; setup says so beside the question. Details:
[`.agents/knowledge/manifest-privacy.md`](../.agents/knowledge/manifest-privacy.md).

- **Silence is never good news.** A report too old to trust never produces an "all clear"; stale
  unfinished work keeps its warning.
- **Machine freshness and remote freshness are separate clocks**, and the map says which is which.

The fleet key is shown only when you ask: `gitso fleet key --show`. Anyone, or any
program, that reads it can join your fleet.

## Local security advice

`gitso fleet publish` includes current working-file and cached-outgoing security advice using
the saved policy and selected optional engines. No fetch occurs unless `--fetch` was selected.
Alerts and incomplete checking do not discard sync facts or authorize an action.

Without a terminal (or with `--json`), `check` prints one record holding `manifest` and
`local_security`. Only that manifest is published, with no findings, private paths or policy
added. Each local checkout retains its own security result, even when identities match.

The local peer dashboard offers **Check local security** on locally observed repositories.
Its loopback-only action requires the current Origin/token and accepts a known repository id,
never a browser-supplied path. The same headless operation checks all matching local copies.
Masked records, timestamps and gaps are presented in session memory; they are not saved to
browser storage, logged, published or served by the peer report. The check uses cached refs
and remains advisory. Watch mode and manifest-only dashboards do not run these checks.

## Fleet keys and operational logs

Setup saves a newly generated fleet key locally and hides it in output. Inspect metadata with
`gitso fleet publish key` or `gitso fleet key`, selecting the same settings/state context as
the configured component. Add `--show` only to deliberately print the raw key in that local
channel for joining another machine. An agent capturing that output receives the key too.
These commands save no report/log and change no settings. Keep keys out of shared status.

The native Windows tray now uses common `app.logging` preferences and the shared event/counter
logger, not a console tee. The default file is `<user-data>/logs/app_tray.log`; a configured
logging directory overrides it. Disabled logging writes nothing; an unavailable required sink
stops startup instead of silently choosing another file. Before enrollment the tray uses
logging defaults in the selected user-data home; malformed settings fail.
Console diagnostics and deliberately shown keys never enter this log or notification text.
Full foreground/app logging adoption and native lifecycle acceptance remain unfinished.

## Set up a machine

Run as your normal user with Python 3.11+ and Git. Use the repository's virtual environment
when available. GitHub CLI with an existing login is required only for the GitHub transport;
connected Tailscale is required only for direct peer access. The app never manages credentials.

Before setup, inspect exactly which optional tiers are ready:

```sh
gitso fleet preflight
```

This is read-only. It checks Git, the existing `gh` login, Tailscale connectivity, the loopback
dashboard port, and common existing sync-folder locations. Missing Git is a blocker; the other
tiers are simply reported as unavailable and can be added later.

**The easiest way is the app itself.** Start the tray (`gitso tray`) or the web view
(`gitso serve-web`). On a machine that is not enrolled, double-clicking the tray (or opening
`http://127.0.0.1:8760/`) shows the setup page: what each step unlocks, then *find libraries*,
*add libraries*, how the app shows itself, and joining a fleet; each asks before it acts. The map
starts by itself as soon as a library is added, and the page stays reachable from the map's
Setup link. `gitso fleet status` (or `--json`) shows the same picture.

Setup is two steps, kept apart on purpose: **enroll the machine** (its libraries; this is
enough for the tray, the web view and every local command), then, whenever you like, **join it
to a fleet** (a key and how it shares status).

```sh
gitso machine find /path/to/look/in     # or --whole-machine; shows where it will look, then asks
gitso machine add /path/to/library [/another/library]   # shows what it will look through, then asks
gitso machine presentation --face web --web loopback
gitso fleet                              # join: key, transports, name sharing
```

`find` only suggests: it reads folder names where you point it, lists folders that hold
repositories, and enrolls nothing. `add` says exactly which folders will be inventoried and
waits for your approval; a machine may hold several libraries, and they may not overlap. The
presentation choice says what double-clicking the tray opens (`web` or `window`) and whether
the web view is served at all (`off`, `loopback`, or `tailnet` for your own devices).
`gitso fleet leave` deselects every transport; the machine keeps its libraries. A fleet key
can be replaced (joining another fleet) only while this machine shares nothing.

Scripted, with no Tailscale: the first run prints the plan (which folders it looks through
once, what it shares) and its id; the second carries out exactly that plan.

```sh
gitso fleet peer --root /path/to/library --no-tailnet
gitso fleet peer --root /path/to/library --no-tailnet --apply PLAN_ID
```

`--root` is repeatable. Another machine uses the same fleet key, entered in setup or supplied
through `--fleet-secret`; keep the key local and carry it privately. When Tailscale is
connected, setup can instead offer an explicit, authenticated hand-off from a running peer.
Starting another peer does not require any other machine to be online.

The dashboard is normally `http://127.0.0.1:8760/` on each machine. It combines local status,
cached peer reports, and readable manifests from configured transports, newest per machine.
`dashboard --serve` is also available for `init`/`check` configurations, independently of the
fleet runtime. The settings profile owns each component's enrollment; there is no other place.

## Choose complementary transports

Durable and live transports carry status. The separately confirmed medium folder also carries
opt-in saved-work snapshots; it never shares them through the GitHub state repository.
`Special/machine_buffers.py` can explicitly inspect local VS Code backup metadata, but unsaved buffer
content is never published by this release.

- **Durable:** a private, writable GitHub state repository accessed through your `gh` login.
  The app writes one v5 manifest per machine through the Contents API; it never clones that
  state repository. By default the manifest names your repositories, branches and current
  commits; `--withhold-names` (or "no" at setup) publishes salted ids only. Creating it requires an explicit setup choice or `--create-repo`.
- **Medium:** an existing folder managed by your own sync client. No particular client is
  required; gitSpecOps does not install or configure one.
- **Live:** optional Tailscale peer discovery and pulls, every 5 minutes by default (setup asks: 1, 5 or 30 minutes; stored as `transports.tailnet.seconds`). Peers expose GET-only
  reports and an authenticated session endpoint. Nothing is pushed to another peer. The live
  report includes readable repository identities within the authorized personal fleet.

To add or remove transports, stop the local peer and run:

```sh
gitso fleet transports --folder /path/to/synced-folder --folder-seconds 300 --repo example/private-fleet-state --create-repo --repo-seconds 1800
gitso peer run
```

`--clear-folder`, `--clear-repo`, and `--clear-tailnet` remove individual integrations;
`--tailnet` enables direct peers. No transport is authoritative. Keep configuration, fleet
keys, catalogs, and SQLite databases outside synchronized state folders.

Setup's Fleet step describes all three connections and asks about each. The state repository
is offered last, marked experimental and untested, and its answer defaults to no. After you opt
in, it suggests `owner/gitspecops-state` from the current `gh` login; type another owner/name to
override it. An existing repository is used only if it is private and writable; a missing one
is created, private, when you apply the review. Nothing is created before then. A synced folder
gets a folder of its own (`gitSpecOps fleet`) inside the folder your sync service copies, or any
existing folder you name, such as one in an Obsidian Sync vault.

Publication sends initial status and then semantic changes at each transport's minimum interval
(folder 300 seconds, GitHub 1800 seconds by default). Each transport keeps its latest pending
status during cooldown and retries failures after the interval. Pending delivery runs without
another filesystem event or Git scan. The queue is in memory; startup inventories again and
publishes current status. Do not infer remote delivery from a successful local observation.
No last-second upload is promised on shutdown or power loss.

## Observe and resume

```sh
gitso peer run
gitso fleet doctor
gitso peer rescan
```

Startup performs one inventory. Linux inotify or Windows `ReadDirectoryChangesW` then triggers
targeted Git status checks only for changed repositories. There is no periodic repository scan.
On Linux only the repositories and the folders leading to them are watched, since Linux allows a
fixed number of watches (often about 120,000) and a large drive has more folders than that. If
even that runs out, the app keeps running, rereads the library every 10 minutes, and says so on
the page with the command that raises the limit.
New checkouts raise a notice; `Elaborate/peer.py rescan` explicitly refreshes membership. The current peer
runtime does not implement the retired host/client timestamp-heartbeat protocol; a quiet
report's observation time can age even while its process remains reachable.

Common configuration lives in the selected user-data home's `settings.json`. Use
`fleet --settings-home /path/to/profile ...` to select it. `fleet --config-dir /path/to/state ...`
selects local state independently: the database, latest report, locks and catalog
remain there. The default state directory is that profile's `sync-suggester` child;
`GITSPECOPS_SYNC_HOME` can override it without selecting another common profile. The app's
multiple transports and the CLI's single transport remain separately selected. Shared machine
identity cannot be changed by per-component setup, and a transport selected by both components
needs a coordinated change. Clearing a selection retains its shared definition.

Invalid settings fail; a machine without enrollment is simply not enrolled. Explicit edits use
the shared revision-checked writer and preserve unrelated settings. Setting up the fleet on a
machine with no settings file starts an empty profile first. An OS lock prevents concurrent
peers using the same state directory.

## Catch up a machine safely

```sh
gitso machine catch-up                    # the plan; at a terminal, it asks
gitso machine catch-up --apply PLAN_ID    # exactly that plan, for scripts and agents
```

`catchup` is terminal-first: it performs a fresh, non-interactive `git fetch origin` for every
locally observed checkout, then reports exactly what it found. The default is a plan only and
does not alter a branch, index, or working file. An approved plan applies only the entries
that are both clean and behind-only, using `git pull --ff-only`, and rechecks success against
the freshly fetched remote.

Every other state is a human decision: dirty/untracked work, ahead-only commits, divergence,
detached HEAD, no upstream, unreadable status, and a failed fetch are all reported and skipped.
Catch up never commits, pushes, stashes, resets, merges, rebases, prunes, or recurses into
submodules. It runs only while the peer is stopped; the per-configuration lock refuses a
concurrent run. Resume the peer afterward to publish the changed local status.

## Audit a large local working set

```sh
gitso machine audit
gitso machine audit --json
```

This report finds missing origins or upstreams, plain-HTTP origins, detached heads, commits on
no remote (any branch or tag), stashes, behind state, and tracked changes across every
repository under the configured roots — found by its own walk, so a repository the live view
cannot name (no origin) is still audited, and bare repositories are listed. It changes no remote,
branch, index, or working file. Fleet-wide materialization and branch cleanup remain separate
future operations; this audit deliberately does not invent repairs for ambiguous repositories.

To seed a new library from this machine's approved working set:

```sh
gitso machine materialize --destination /new/library
gitso machine materialize --destination /new/library --apply PLAN_ID
```

The first command maps recognizable origins to `host/owner/repository` folders and reports
collisions or local-only checkouts. The second clones only destinations that were absent when
rechecked; it never replaces or updates an existing checkout. This is a local working-set
materializer, not a promise that names-free status manifests alone can discover an institution's
entire organization inventory.

## Inspect VS Code's existing unsaved buffers

```sh
gitso machine buffers
```

This is an explicit local inspection, not a watcher. On Windows it reads the existing VS Code
backup directory; on another platform or profile, pass `--backup-root PATH`. It reports only
metadata for backups whose URI maps beneath a configured repository root and whose buffer differs
from the saved file. It neither prints nor stores buffer content, and it sends nothing to another
machine. Publishing opt-in live buffers is a separate privacy and transport decision.

## Baskets: what this machine takes part in

```sh
gitso fleet baskets
gitso fleet baskets --scope observe --mode except --namespace github.com/some-owner
gitso fleet baskets --scope publish --mode only --namespace github.com/some-owner
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
Matching happens locally, on this machine's own repository names: a withheld repository sends
nothing at all -- no record, no id, no name -- so no peer can see, apply, or infer another
machine's baskets.

Narrowing is never silent. A withheld repository stays on this machine's own dashboard, marked
*not published*, and the dashboard states how many repositories are withheld or unobserved.
`observe` changes apply at the next `Elaborate/peer.py rescan` or restart; `publish` changes apply at the
next observation.

## Recover saved work and audit replacement safety

```sh
gitso recovery configure --location /private/sync-folder    # shows any warning, then asks
gitso fleet baskets --scope capture --mode only --namespace github.com/some-owner
gitso recovery status
gitso machine safe-to-wipe
```

The recovery folder is deliberately separate from the status folder and must already exist.
The peer captures selected repositories after filesystem quiet periods. A second peer that can
read the same folder verifies each checksum and writes an acknowledgement; only then does the
source call it *recoverable elsewhere*. `recovery preview` reads a named bundle without writing;
`recovery restore` creates a disposable checkout, never overlays an existing working tree.
`recovery retire` freshly fetches `origin` and removes a local bundle only when the fetched
upstream's tree exactly matches the bundle's staged, unstaged, and carried-file content.

`safe-to-wipe` walks the configured roots itself — hidden folders included, and each root
itself — so it does not depend on what the live view observes. It fetches every remote of every
repository but never changes a working tree. A repository blocks the verdict if it has no
remote, cannot be fetched, holds a commit on any local branch, tag or HEAD that no remote has,
holds a stash, is mid-merge/rebase, or is bare. A dirty checkout passes only when its exact
current snapshot has been checksum-verified by another peer. The verdict names what it does not
check: ignored files such as `.env`, files outside repositories, other filesystems mounted
under a root, and remote branches deleted since the last fetch.

## Tray and start-at-sign-in

```sh
gitso tray            # start it on its own; while it runs: what it is doing and did last
gitso tray --follow   # keep showing what it does (Ctrl+C stops following, not the app)
gitso tray --open     # open the web view at the map
gitso tray --stop     # quit it
gitso start-at-sign-in status
gitso start-at-sign-in enable
gitso start-at-sign-in disable
```

`gitso tray` starts the app on its own: on Windows, Windows itself starts it (WMI), hidden, so
no terminal, setup window or Windows Terminal tab is its parent, and it lets go of any console it
was given. `gitso tray` also says how the running app runs, and warns if a window is tied to it.

The Windows tray reads the local display contract, opens the dashboard, requests a rescan,
controls per-user start-at-sign-in, and can run the same read-only catch-up preview as the
dashboard on a worker thread. It offers no Git mutations. Off Windows, `tray` falls
back to a foreground run. Linux also supports `Elaborate/start_at_sign_in.py --systemd enable` as a user
unit. Run as the interactive user so Git ownership, credentials, and sync-folder access match.
Use a durable installation location before enabling startup for a packaged build.
See [BUILD-DESKTOP.md](../_build/BUILD-DESKTOP.md).

## Boundaries

The peer observes staged, unstaged, untracked, stashed, operation, and cached ahead/behind
facts. Its scheduled fetch is read-only toward branches and files. The explicit, stopped-peer
`gitso machine catch-up` command, once its plan is approved, may fast-forward clean, behind-only checkouts after a
fresh fetch; it never clones, commits, stashes, pushes, transfers unfinished files, or makes an
ambiguous Git decision.
Namespace groups in the dashboard are a display grouping, not a basket; baskets are configured
with `Elaborate/fleet.py baskets` and shown in App & setup. The dashboard can run the same fresh-fetch
catch-up preview as the terminal; applying a pull remains the explicit stopped-peer terminal
command. Cached refs do not prove exact equality between machines.

Tailscale authorization allows the configured login's untagged devices. This is a personal
fleet, not enterprise roles or isolation between OS users sharing a device. The loopback
dashboard is local to the machine, not an authentication boundary between its OS users.

All skins consume `gitspecops.fleet.display`; they must not reclassify Git facts. See
[DISPLAY-CONTRACT.md](DISPLAY-CONTRACT.md). Validate with `python tests/run_all.py` using a
supported interpreter on the claimed platform; synthetic tests do not prove actual deployment.

[Back to the README](../README.md)
