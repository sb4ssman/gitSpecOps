# Live personal fleet — 2026-09-05

User authorized the first deployment on moonbase-prime (Linux host), moonbase-node1-w and
xenmorph2b (Windows; user calls this xenomorph2b). Existing gh authentication is a hard
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
prime preview ran at five seconds and measured about 11.2% average CPU and 34 MiB RSS across 105
repos. A temporary 30-second cadence was also rejected by the user. Configuration v2 removes the
scan interval entirely, migrates the preview automatically, and adds the deliberate `fleet rescan`
request for newly added or removed repositories.

## Deployment state

Prime configuration is under the normal user config directory, in fleet-app.json, separate
from legacy config.json. Host database: fleet.sqlite3. Latest observation: fleet-latest.json.
Dashboard URL: http://100.85.195.87:8765/ . Host started from the agent's foreground terminal;
resume independently in VS Code with `python3 git-sync-suggester/sync_suggester.py fleet run`.
Only prime is verified publishing (105 repos). Windows endpoints were pingable; observer
installation awaits a matching development checkout and local command because SSH was
unavailable. The prototype source-download endpoint was removed on the user's feedback; an
installed app is the required public onboarding path.

## Follow-up

User wants baskets/subscriptions as core (single user and enterprise), then mutations, remote
commit/push requests and opt-in recovery snapshots. None are implemented by this pilot.
Namespace groups are observed inventory, not baskets. No-Tailscale guided fallback,
replica reconciliation and commit-triggered publication are also unfinished. Replicas should
never become competing authorities. Native tray, deployment packaging and enterprise auth
remain separate work. The display contract is now versioned and independent of the standard
skin; see DISPLAY-CONTRACT.md. User instructions supersede older notes that no observer may run.

See git-sync-suggester/FLEET.md for the user guide and tests/test_fleet_app.py for boundaries.
