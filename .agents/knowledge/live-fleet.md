# Fleet architecture: current peer model and historical pilot

## Current guidance — 2026-09-11

Every machine is an independent peer. `app/fleet_app.py` supplies `setup`, `peer`, `run`,
`transports`, `doctor`, `rescan`, `tray`, and `autostart`. The v3 configuration preserves old
fleet identities on migration. No machine is an authority; peers pull reports and reject POST.
Each peer serves its own loopback dashboard from local state, its SQLite peer cache, and any
configured transports. `gh` is needed only for GitHub; Tailscale is optional.

Native filesystem events follow one acknowledged inventory. There is no periodic Git scan.
Tailnet discovery/pulls run every 30 seconds. Folder/GitHub transports carry the same names-free
v3 status manifest. Recovery content is still planned, separately from that manifest.
Use [FLEET.md](../../git-sync-suggester/docs/FLEET.md) for current commands and
[tiers-and-capture.md](tiers-and-capture.md) for the agreed next work.

## Historical pilot record — superseded, not deployment instructions

The following records explain the original host/client design and why it was replaced.
Its prerequisite, enrollment, heartbeat, and authority statements are historical only.
Machine reachability and deployment counts are dated observations, not current facts.

# Live personal fleet — 2026-09-05

User authorized the first deployment on machine-a (Linux host), machine-b and
machine-c (Windows; user calls this machine-c). Existing gh authentication is a hard
prerequisite for the new fleet app, and remains user-owned. No gh tokens are read or sent.

## Implemented boundary

`sync_suggester.py fleet` delegates to flat `fleet_app.py`. `fleet setup` is the interactive
front door; host/connect configure and run; run resumes; doctor hides the fleet secret.
The host runs in the foreground with an observer and private Tailscale HTTP listener. No
OS service or scheduled task. It owns a local SQLite database through `fleet_store.py`;
clients never open that database across a share. `fleet_net.py` identifies TCP peers using
Tailscale whois and permits only untagged nodes owned by the host's configured Tailscale
user. The stable node id fixes each writer's identity. This is personal-fleet trust, not
multi-user workstation or enterprise RBAC. Browser Host checks and no CORS prevent reading
session data through rebinding; POST requires an application header and rejects Origin.

Live reports separately carry repo host/owner/name for a readable tree, but no paths, source,
branch names or diffs. This is an explicit extension of the metadata policy for the private
live app; the legacy v3 manifest schema and cloud privacy boundary remain unchanged.
The fleet secret is transmitted only to an authenticated allowed peer during enrollment.

One acknowledged recursive inventory runs at startup. Linux inotify and Windows
ReadDirectoryChangesW then block while idle and trigger debounced Git checks only for affected
known repositories. There is no periodic inventory or status scan. Semantic-change publication
plus a tiny timestamp-only 30-second network heartbeat keeps live reports current; the full report
is neither resent nor rewritten for liveness. The browser refreshes every
three seconds and reports are stale after 120 seconds.
Last-known work persists through staleness. Failed host contact retains latest local status.
Multiple checkouts sharing an origin are refused rather than silently merged in a report.

Optional folder and GitHub replicas publish each device's own v3 manifest on independent
intervals. Github owner can be any org/account the active gh login can access. Repository
must exist, be private and writable. Setup validates explicitly; runtime reads/writes happen
only at configured slots (default 1800 seconds). Failed slots wait the full interval too.
No automatic cloud failover, source fetching, commit hooks, remote jobs or content capture.

Setup requires explicit acknowledgement after naming every recursive inventory root. The first
machine-a preview ran at five seconds and measured about 11.2% average CPU and 34 MiB RSS across 105
repos. A temporary 30-second cadence was also rejected by the user. Configuration v2 removes the
scan interval entirely, migrates the preview automatically, and adds the deliberate `fleet rescan`
request for newly added or removed repositories.

## Deployment state

Prime configuration is under the normal user config directory, in fleet-app.json, separate
from legacy config.json. Host database: fleet.sqlite3. Latest observation: fleet-latest.json.
Dashboard URL: http://<machine-a-tailscale-ip>:8765/ . Host started from the agent's foreground terminal;
resume independently in VS Code with `python3 git-sync-suggester/sync_suggester.py fleet run`.
Only machine-a is verified publishing (105 repos). Windows endpoints were pingable; observer
installation awaits a matching development checkout and local command because SSH was
unavailable. The prototype source-download endpoint was removed on the user's feedback; an
installed app is the required public onboarding path.

## Lifecycle shell (2026-09-11)

The pilot's real gap was not a feature but a lifecycle: a foreground-only app meant the host
was usually not running, and a fleet whose host is down accepts no reports and serves no
dashboard. `fleet_tray.py` (stdlib ctypes, Windows) and `fleet_autostart.py` (per-user
start-at-login) close that. The tray consumes the display contract and classifies nothing; it
exposes no Git mutations. Start-at-login is per-user and never a service, so the app keeps the
interactive user's gh login, Git ownership and Tailscale identity — the correctness trap
recorded in the outside review. `fleet tray` degrades to a foreground run off Windows.

Building it surfaced that **Windows observation had never actually worked**: the native watcher
filtered events against the absolute path, so any root beneath a name in the ignore list
(`AppData`, `Library`, `env`, `venv`) silently discarded everything. The Linux suite could not
see it. Treat "the test suite passes on machine-a" as evidence about Linux only.

The Windows executable now exists (PyInstaller 6.22.2, 25 MiB, built on machine-c). Neither
Windows machine is enrolled yet, because no host is running — that is a deployment decision,
and starting a host on a second machine would mint a second fleet secret and fork the fleet.

## Follow-up

User wants baskets/subscriptions as core (single user and enterprise), then mutations, remote
commit/push requests and opt-in recovery snapshots. None are implemented by this pilot.
Namespace groups are observed inventory, not baskets. No-Tailscale guided fallback,
replica reconciliation and commit-triggered publication are also unfinished. Replicas should
never become competing authorities. Native tray, deployment packaging and enterprise auth
remain separate work. The display contract is now versioned and independent of the standard
skin; see DISPLAY-CONTRACT.md. User instructions supersede older notes that no observer may run.

See git-sync-suggester/docs/FLEET.md for the user guide and tests/test_fleet_app.py for boundaries.
