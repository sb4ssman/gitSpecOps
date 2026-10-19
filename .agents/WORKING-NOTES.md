# Working notes

Living todo / scratch pad. Add items freely; **prune regularly**. When something is done, move it
into [`WORK-LOG.md`](WORK-LOG.md) (appended at the bottom, `YYYY-MM-DD HH:MM`) and delete it here.
Dates are always absolute.

_Last tended: 2026-10-19 (new top section only; everything below it is as of 2026-09-22/10-05)_

## Open

### 2026-10-19 — product direction: the vision, what was decided, what is owed (HANDOFF)

A long design discussion (2026-10-17 to 10-19) re-anchored the product. **Nothing in the code
changed.** Read this section first; [`HANDOFF.md`](HANDOFF.md) points here.

**The user's vision, in their words, and the one that must stick:** relegate Sourcetree, GitHub
Desktop, GitKraken and the git CLI to *surgical tools*. Sync Suggester takes over day-to-day use.
The result is that every repository is more up to date on every machine, and **at a glance the
user can SEE what is out of sync on any given machine** — "go back to machine-A and push x, y, z;
machine-B push some more; machine-C pull and push a mess; machine-D hasn't been online in a while
and has even more." On boot or wake, pull-ff everything (including folders of public repos kept
only to stay current). A tray app with notifications, a menu and a popup, or a dashboard of
connected machines and repo states across them.

**A caution carried from the start of the discussion:** an earlier session in this conversation
repeated "44/44 green" from these notes as fact without opening a test or running the suite. The
user was rightly alarmed. Test counts in these notes are counts of *scripts that exited 0*, written
by the same sessions that wrote the code. **No one has audited what the tests assert.** Treat
every pass count here as a claim until the suite has been read and run.

#### Decided by the user

- **A tray app, on Windows, Linux and macOS. All three are critical.** The tray is a must, not an
  extra. Debian 13 with a desktop tray and macOS's menu bar both already show third-party icons
  (the user sees another product's icon in both).
- **Dependencies are acceptable for the App, and so is a native helper.** The operations stay
  stdlib-only; the optional App may carry a dependency or ship a small native shell. Preference:
  something that **looks the same everywhere**.
- **The icon should carry information:** this machine out of sync / syncing / in sync, plus a dot
  or coloured symbol per other enrolled machine, and some sign of whether each is online.
  Dense at 16 px; **experiments are required**, viewed on all three OSes.
- **One front door for setup** (agreed): one re-runnable flow asks base preferences — checks
  (git, host login), roots, transports, baskets, triggers, notifications, tray and
  start-at-login — and **every answer stays changeable** later (re-run setup or a settings page).
  Today `run_setup` asks nothing and `fleet setup` is a separate second setup.
- **Transports to try for real:** the private GitHub state repo (valued: "a special git repo
  just for gitSpecOps to control"), **Dropbox** and **Syncthing**. **Obsidian is out** — the user
  does not use it, and its sync is paid. Drop the "vault note" idea; the private repo can carry
  human-readable per-machine notes instead (GitHub renders them, readable from a phone).
- **Broadcast on sleep / shutdown** is wanted: not a scan (the peer already knows its state from
  file events) but an immediate publish that bypasses the 1800 s repo-transport rate limit, ideally
  saying "going to sleep" so peers show "asleep since 22:10" rather than "not seen".
- **A second household user gets their own fleet on their own two Macs** — the first
  stranger's-first-run test of the front door, when the time comes.
- **State repo name:** any of `gitSpecOps-SYNC`, `gitSpecOps-sync`, `gitspecops-fleet-state` is
  acceptable to the user. Today's default is `<login>/gitspecops-fleet-state`
  (`git-sync-suggester/app/fleet_app.py`, the `candidate =` line in the state-repo prompt).
  Recommended: `gitspecops-sync`. Not yet changed.

#### Recommended, awaiting the user's yes

1. **One app, named gitSpecOps, whose home screen is Sync Suggester.** Tray = glance, route lines,
   notifications. Dashboard/popup = the route, the repo×machine grid, and daily git operations.
   Operations = a runner for archive update, org duplication, inventory, each planned, shown and
   confirmed. The terminal stays a first-class entry point. Sync Suggester's engine stays in
   `Elaborate/` (it *is* "across machines and across time"); `App/` is the prominent part.
2. **Rewrite the effect rule — it contradicts the vision.** The diagram footer says "the peer, tray
   and dashboard only observe", and `architecture-layers.md` plans a test that everything reachable
   from them or the scheduler is `EFFECT = "none"`. Committing/pushing from the app and ff-on-wake
   both violate it, and the archive scheduled task (`--update`) already does. Proposed:
   **background** (peer, scheduler, wake/sleep triggers) observes only, except a **standing
   consent the user configured** (an auto-update basket: ff-only, clean, behind-only — as the
   archive launchers already do); **foreground** (a tray item, a dashboard button) runs the same
   command as the terminal with the same plan/show/confirm. Then update the diagram and phase 5.
3. **Manifest schema v4 before any enrollment:** the private repo transport and the live tier
   carry repository names, branch names and the head commit; the folder transport stays
   names-free unless opted in. Rationale is already in `knowledge/manifest-privacy.md`: on a
   private GitHub repo the salt "is no longer load-bearing" because GitHub hosts the repos being
   described. Names are needed for the route ("push x, y, z"); the head commit lets the tool say
   "C is on the commit A pushed" instead of inferring. The user asked "why can't we record
   names?" — leaning yes, not formally confirmed.
4. **A fourth basket scope, auto-update:** which namespaces may fast-forward unattended.
5. **Triggers:** publish on sleep, shutdown and screen lock; the "before you leave" warning on lock.

#### Still to ask

- Which Debian desktop (KDE / GNOME / Xfce / Cinnamon) — GNOME shows tray icons only via an
  extension.
- Is the 2012 iMac (macOS Catalina 10.15 is its ceiling) a full peer, or acceptable headless if
  the chosen tray toolkit will not support Catalina?

#### New concepts from the discussion

- **The route (itinerary).** The display contract is repo rows × machine cells; the missing view
  is the same data per machine, **in an order you can follow**: "C: pull R, after A pushes" when A
  is ahead on R and C has R. Computed by the peer and shipped in the contract (skins never
  classify). Repos only a peer holds render `repo:abcd1234` until names arrive (v4) or `converge`
  resolves them. Last-known state survives staleness, so an offline machine reads "last seen 12
  days ago; then held unpushed work in 5 repositories".
- **Notification texts (draft),** each a route line, announced only on transitions (the tray
  already suppresses the first paint): caught up N, 2 need you here (names); machine-B pushed 4,
  3 are clean fast-forwards here; unfinished work on this machine (before you leave);
  machine-D not seen for 12 days, held unpushed work; diverged on A and C, needs a decision;
  fleet clear; publishing paused (host login expired).
- **Tray menu** shows the top route lines, Preview catch-up, Open dashboard. No separate tkinter
  popup: a popup window, if any, renders our own HTML so it is identical on every OS.

#### Verified in the code this session (read, not run)

- **The tray is Windows-only** (`app/fleet_tray.py`, ctypes; `supported()` is `win32`). Its icon
  is a 16×16 dot drawn in code (`_make_icon`, hardcoded 16 px — should draw at the real
  `SM_CXSMICON` size). It handles neither power events (`WM_POWERBROADCAST`), session end
  (`WM_QUERYENDSESSION`), lock, nor balloon clicks (`NIN_BALLOONUSERCLICK`). Notify texts today:
  "Fleet needs attention", "Fleet problem", "Fleet clear".
- **macOS has no tray, no file-event backend and no scheduler** (`_os/macos/` reports
  unsupported); start-at-login (LaunchAgent) exists. Nothing records gitSpecOps ever running on a
  Mac. **Linux has no tray**; file events and XDG/systemd autostart exist.
- **No by-machine view** in the dashboard JS.
- **`run_setup` asks no questions** (launchers, `.venv`, prerequisite report only).
- **Basic has no diff, commit, log, branch/switch or stash** — the gap between this and "Sourcetree
  becomes surgical". The architecture diagram never listed them either.
- **AI-friendliness:** strong for an AI *developing* gitSpecOps; weak for an AI helping a user
  *use* it — it would read these notes as its own instructions. Needed: a fork at the top of
  `AGENTS.md` ("helping someone use this? read the usage guide; leave `.agents/` alone"), a usage
  guide (commands, `--answers`, `--no-prompt`, `--json` where it exists), and a line that plans and
  confirmations belong to the human even when an AI holds `--yes`.

#### Tray toolkit: run a spike before choosing

What can look identical everywhere is **our icon** (we draw it) and **a popup that renders our
HTML**; the right-click menu is native per OS and should be. Candidates for a thin shell:

- **A — Python:** pystray + pywebview. Stays in one language; Linux leans on system
  GTK/AppIndicator packages (the usual breakage).
- **B — Tauri:** small Rust shell, OS webview, talks to the engine over the loopback HTTP API the
  tray already uses in connect mode. Adds a Rust build toolchain.
- (A Go helper like Tailscale's tray was considered; Go ≥ 1.23 does not run on macOS 10.15.)

Spike: the same tiny tray (icon cycling states, three menu items, a popup showing the route, one
notification) in A and B, on Windows 11, Debian 13 and the Catalina iMac; keep the one that broke
least. First icon experiment: a stdlib script rendering candidates to PNG at 16/20/24/32 px.
Design idea: the Git logo's branch graph (CC BY 3.0, attribution required) with **each node a
machine** — main node = this machine, branch nodes = peers, filled = online, ring = offline;
shape as well as colour, for colour-blind users. On macOS the menu-bar item can show text beside
a monochrome template icon ("↑3 ↓2 ●●○").

#### Transport facts that matter for testing

- **Dropbox** has a server, so an offline machine's last report waits there. Its free plan allows
  3 devices.
- **Syncthing** is free but peer-to-peer: a report moves only while two devices are online at once,
  so a rarely-online machine can publish and sleep unseen unless one node stays up.
- **GitHub state repo** has a server and needs nothing new installed. Every Contents API write is
  a commit, so the repo's history is a free log of every machine's state over time.
- **Sleep/shutdown hooks:** use the tray (runs as the user, has the host login). Windows gives about
  2 s on `PBT_APMSUSPEND`; `WM_QUERYENDSESSION` + `ShutdownBlockReasonCreate` can hold shutdown
  until a publish finishes; lock notifications have no deadline. Modern Standby laptops report
  sleep differently — test on real hardware. Avoid Task Scheduler event triggers (late) and Group
  Policy shutdown scripts (run as SYSTEM). Linux: systemd-logind delay inhibitors.
- **Self-update for a source checkout:** gitSpecOps is a Git repo, so it can sit in the
  auto-update basket and fast-forward like anything else; missing are a restart offer after
  self-update and regenerating launchers. The installed-app updater (signed manifest, rollback)
  is designed in `knowledge/distribution.md`, unbuilt.

#### Test machines available (generic descriptions)

Windows 11 (primary); one box dual-booting Windows and Debian 13 (two identities on one hardware,
never online together — a curious case if a shared data partition is visible to both); an old
Windows 10 laptop; a 2012 iMac (Catalina ceiling — the compatibility canary); an old Windows 10
desktop at a remote site (the real rarely-online "machine-D"); a second user's two MacBooks (their
own fleet).

#### Proposed path (the user agreed the earlier order; this re-sequencing is not yet confirmed)

Each step ends in something visible:

1. **Trust.** Read the tests (what each asserts, fakes, never touches) and run the suite on
   Windows 11, Debian and the iMac — the Mac's first run ever.
2. **Throwaway fleet.** Foreground `fleet run` peers, no start-at-login (so the migration need not
   come first), on a disposable fleet key, trying the GitHub repo, Dropbox and Syncthing. A Mac
   peer needs a file-event backend first (FSEvents via ctypes is plausible); until then `check`.
3. **Tray spike + icon experiments.** Choose the toolkit.
4. **Make it real.** Phase 3c, `App/` with the chosen tray, schema v4, the rewritten effect rule,
   the diagram updated.
5. **Seeing.** Real enrollment with start-at-login; the route; notifications; sleep/wake/lock
   triggers; the auto-update basket. Delivers "at a glance, what's out of sync on any machine".
6. **Doing.** diff, commit with review, branch/switch, stash in `Basic/`, exposed in the app.
   Delivers "Sourcetree becomes surgical". Remote device jobs (ask an online peer to push) after.
7. **The second user's fleet.** The one front door plus portable builds for their Macs.

Also still owed by the user, unchanged: the scheduled-task replacement and three archive
launchers (below), the history-rewrite decision before public promotion, and cutting v0.2.0.

### 2026-10-19 — side quest: a self-doxxing scan across the user's own fleet

Idea from the user: with everything gitSpecOps already knows about a user's fleet, a script could
**take what is known about the user and work backwards**, scanning their repositories for
personal information they leaked themselves. Not built; recorded for design.

- **Seeds it can gather without asking:** `git config` name and email, the host CLI's login,
  machine labels and hostnames, home-directory paths, tailnet addresses the fleet has seen, and
  the namespaces/orgs in the inventory. Plus anything the user adds (real name, phone, street,
  other emails).
- **Known credentials** (tokens, keys) may be supplied **at run time only**: held in memory or
  compared by hash, **never written to disk or to the report** — the report names the location
  and a redacted fingerprint. This keeps the prior-auth rule: gitSpecOps never stores a credential.
- **Scope:** working trees, **full history** (every blob, as the 2026-09-11 audit of this repo
  did — see `knowledge/repo-privacy-and-history.md`), and **commit metadata** (author/committer
  emails are themselves a self-dox), across every repository the fleet knows, on this machine or
  as a plan for others.
- **Report-only, `EFFECT = "none"`.** Any fix (rewrite, rotate) is a separate decision with its
  own warnings; a history rewrite breaks every clone. The report itself names private
  repositories and personal data, so it goes to the gitignored `.agents/output/` like the
  inventory, and never into the fleet manifest.
- **Reuse:** `tests/repo/test_repo_hygiene.py` patterns and the seven secret shapes from the
  history audit. Layer: a Special operation (one repo scan repeated with judgment), with an
  Elaborate wrapper if it plans across machines.

### 2026-10-05 — library inventory shipped (uncommitted); follow-ups

Built `Special/inventory_export.py` / `inventory_restore.py` (see work log). Not yet done:

- [x] Committed 2026-10-05 (`a7c339e`). The one suite failure then, `basic/test_run.py`, predated
  it: a Python child writing `✓` to a pipe on Windows emits cp1252 unless UTF-8 mode is set.
  Fixed 2026-10-05 at the cause: `Basic/_run.run` now sets `PYTHONUTF8=1` and
  `PYTHONIOENCODING=utf-8` for every child (a caller's own value wins), pinned in
  `tests/basic/test_run.py`. Full suite alone on Windows with neither variable set: 44/44.
- [ ] **Not yet run on a second machine / Linux**: the real round trip (export here, restore there)
  is unproven. Path handling is POSIX-relative by design but only Windows has run it.
- [ ] **Phase 3c: rebuild `materialize` on `_inventory.plan_restore`**, one clone planner not two.
- [ ] **A diff mode** (`inventory_check`: inventory vs disk — missing, extra, origin mismatch) is the
  natural "converge, with names" and is not built.
- [ ] **Restore ignores the recorded branch** (it records it; clone checks out the remote default).
  Decide whether to offer checking it out. Submodules are skipped, not cloned recursively.
- [ ] **The real GUI dialogs are unverified.** Tests drive the terminal/scripted path only; open
  the three dialogs once by hand on Windows (and on a Linux desktop, where tkinter may be absent
  and should fall back to the terminal prompt).
- [ ] No per-repository pick yet (restore takes everything, or `--only LABEL`). `parse_selection`
  in `Basic/_confirm.py` is the grammar to reuse if wanted.
- [ ] Mention the commands in the README Repo Shape / launcher list when 3c settles the layout.

### 2026-09-22 — migration: phases 1, 2, 3a–3b done; 3c next

The target tree (revised 2026-09-21), the phases and the decisions are in
[`knowledge/architecture-layers.md`](knowledge/architecture-layers.md) and
[`HANDOFF.md`](HANDOFF.md). Carried forward:

- [ ] **Direct `subprocess` calls outside `_run`** remain (re-measured 2026-09-22):
  `fleet_autostart` (3), `capture`, `retirement`, `snapshot_restore`, `fleet_net`,
  `release_check`, `setup_gitspecops` (1 each). `schtasks` now lives in `_os/windows/schedule.py`. Each moves onto
  `_run` or into `_os/` as its owner moves in phases 2–4; none should survive phase 4.
- [ ] **`gh` calls are all in the provider now, but two callers still speak raw `gh`**:
  `repo_transport` (Contents API) and `fleet_app` (auth status, login) call `run_gh` with their
  own arguments. Move the Contents API into `github.py` when the transport moves (phase 3);
  `fleet_app` dissolves in phase 3 anyway.
- [ ] **Scheduled task — waiting on the user.** New launcher written 2026-09-22 into the
  per-user state folder; the user replaces the task and reinstalls three archive launchers; then
  delete `gitArchiveUpdater/`.
- [ ] **Two registered archives predate the `mode` field and use custom prefixes.** Reinstalling
  must pass each entry's own `approved_remote_prefixes`; a missing mode means `update`.

Two framings from the design discussion were wrong and are recorded as
such so they are not revived: **"plugins"** (the provider seam already existed; no plugin folders,
loaders or hyphen tricks) and **"legacy vs fleet" Sync Suggester runtimes** (not two products:
`check` runs the observation job once, `peer` runs it continuously, over one config and one code
path).

### 2026-09-20 — the goal outranks the rules; do not re-derive "read-only"

The brief now opens with **What this is for**. If anything further down contradicts it, the goal
wins and the rule is the defect. This is not hypothetical — a scaffold-era "never writes" claim
outranked the product goal for 17 days and had to be removed; see the work log.

**These tools perform Git operations.** The boundary is *observation never mutates; mutation is
always a command the user invoked*. Do not restate that as "Sync Suggester is read-only", and do
not bolt exceptions onto a rule that is wrong — fix the rule.

- [x] **"Sync Suggester" is not a vestigial name — resolved 2026-09-20.** An earlier note here
  claimed it was left over from the read-only era and should be reconsidered before release. The
  user settled it: *the best thing it does is suggest sync.* Suggesting is the headline value, not
  the old limitation — the tool now suggests **and** can act, and the suggestion is still the part
  that earns its place in the tray. Do not reopen this as a rename.

### 2026-09-19 — Product direction confirmed; implementation is ready to resume

The user confirmed one repository, one family, with two shapes: careful terminal
operations and an optional fleet service that coordinates them. The archive updater,
org duplicator, and Sync Suggester remain peers in that family; do not turn the
service into an authority or degrade the clone-and-run command path.

**Headline outcome:** from any enrolled machine, the user can see the state of all
their repositories everywhere and receive a safe, specific suggestion for unsynced
work. The dashboard and tray are skins over terminal-first operations, not separate
policy engines.

**Implemented 2026-09-19:** the medium-tier recovery slice is now end to end: an explicit
private location, local per-repository policy, capture-basket selection, event-quiet capture,
peer checksum acknowledgement, preview/disposable restore, and exact freshly-fetched remote
retirement proof. `safe-to-wipe` now accepts only exact current snapshots verified by another
peer, and never unpushed commits. Setup preflight has honest tier offers; setup can explicitly
request an authenticated Tailscale session hand-off from a running peer. The dashboard has the
same fresh-fetch catch-up preview as the terminal (applying stays terminal-confirmed).

**Also implemented 2026-09-19:** `fleet audit` reports remote/upstream/unfinished-work issues
without mutation, and `fleet materialize` provides a reviewed clone-only plan for the locally
observed working set. The materializer rejects unsafe remote-derived filesystem paths and
symlink escapes. `fleet live-buffers` supplies explicit, local-only VS Code backup evidence;
publishing unsaved content remains deliberately unbuilt. `catchup` fresh-fetches
and previews every observed checkout;
`--apply --yes` fast-forwards only clean behind-only checkouts and lists every other
state for a human. Remote actions retain the existing safety ladder: fetch, safe pull,
ahead-only non-force push, reviewed commit; never guess through divergence or conflict.

Preparation and implementation completed 2026-09-19: mapped the tree, added catch-up, recovery
activation, authenticated session join, dashboard preview, and replacement evidence. Targeted
Windows validation passed, including new recovery runtime and retirement tests. No live
deployment, commit, or push was performed.

**Packaging readiness update:** the desktop PyInstaller recipe had incorrect relative source
paths and omitted dynamic modules; both are repaired and a read-only release gate checks them.
The release remains deliberately uncut: the current working tree is uncommitted, no matching tag
exists, and PyInstaller is not installed in a disposable build environment.

### Current continuation — 2026-09-11

Stale active host/client guidance has been reconciled. Guided durable setup, pending transport
delivery, the desktop Git client shortcut and **baskets** are implemented; details are in the
work log.

- **Medium-tier recovery: encryption question is CLOSED (2026-09-12) — snapshots are not
  encrypted.** Reasoning and the verified per-tier authority table are in
  [RECOVERY-DESIGN.md](../git-sync-suggester/docs/RECOVERY-DESIGN.md) under "Trust boundary".
  No `age`, no new dependency, stdlib-only runtime rule intact. Do not reopen this without a
  concrete threat the three tiers do not already cover.
- **Capture is enabled only through an explicit medium-tier enrollment.** `core/capture.py` and
  `core/secret_scan.py` remain protected by default. The capture basket may select namespaces
  only after a separate confirmed location passes overlap checks; running peers capture after
  filesystem quiet periods, and a second peer must verify the checksum before the source calls
  it recoverable elsewhere.
- **Done 2026-09-12:** snapshot store, preview, restore (`core/snapshot_restore.py`), and the
  per-repository capture policy (`CapturePolicy`: obey `.gitignore`, secret protection,
  `allow_paths`), all tested against real repositories. See the work log.
- **Recovery proof is exact.** `core/retirement.py` recreates a bundle's resulting tree in a
  temporary index, freshly fetches origin, and permits retirement only if the upstream tree is
  identical. Clean state or counts never suffice. The follow-up is cross-machine snapshot
  discovery/restore UX, not a weaker proof.
- **Run test suites alone before claiming a result.** On 2026-09-12 `fleet/test_git_client.py`
  failed only while five test processes ran concurrently; alone it passed. The full suite alone
  passed **26/26 on Windows** on 2026-09-19.
- **Manual probes are versioned under `tests/probes/`.** Code, synthetic fixtures and
  instructions belong there; profiles, raw logs and results remain temporary/local. The
  automated runner explicitly excludes this directory. The VS Code hot-exit probe **has now
  run against a real unsaved edit** and found a backup differing from the saved file: dirty
  buffers are persisted before exit (VS Code 1.137.0, this machine). Existence only — the
  probe says nothing about how quickly a backup appears.
- **Desktop Git client shortcut is implemented and verified** (`app/git_client.py`,
  `tests/fleet/test_git_client.py`, `tests/probes/desktop_client_ui.py`). Selection is
  per-machine; the action only opens a locally observed checkout in Sourcetree or GitHub
  Desktop. It performs no Git operations and is not a step on the tier ladder.
- **Validation environment:** use the existing virtual environment (Python 3.14.2 on this
  Windows checkout). Bare `python` is below the declared >=3.11 minimum.

- [x] **The tier ladder's local slices are built (updated 2026-09-19).** See
  [knowledge/tiers-and-capture.md](knowledge/tiers-and-capture.md). Today all three tiers carry
  the *same* v3 status manifest, so they differ only in latency. They are supposed to differ in
  what they can rescue: durable = committed + status; medium = **saved but uncommitted content**;
  live = **unsaved editor buffers**. Ordered next steps:
  1. **Guided durable setup — implemented 2026-09-11.** Suggested private repo name,
     app ownership/publication explanation, and named CREATE/USE confirmations.
  2. **Content capture on the medium tier** (the user's *stealth-stash*): a separate,
     size-capped bundle per repository that expires only after retirement proof. It is not
     encrypted by design; policy, retirement proof and peer wiring are active after explicit
     recovery-location and capture-basket enrollment. See `docs/RECOVERY-DESIGN.md`.
  3. **Unsaved buffers on the live tier — local reader built.** VS Code does write
     dirty buffers to its backup store before exit (measured 2026-09-11 via
     `tests/probes/vscode_hot_exit/probe.py --run`). So no editor plugin is needed for VS Code:
     read what the editor already wrote. `fleet live-buffers` maps existing backup records to
     configured roots and returns metadata only. Still undecided: backup latency, other editors,
     and whether unsaved content may leave the machine at all.
  4. **Baskets — implemented 2026-09-11**, ahead of capture at the user's direction. Three
     independent scopes; capture is refused rather than offered. See the work log and
     `docs/FLEET.md`. Config is schema v4.

- [x] ~~**Selecting which repositories a machine syncs is all-or-nothing.**~~ **Done
  2026-09-11.** `fleet baskets` selects by namespace per scope. Still open on top of it: a
  basket cannot yet name an individual repository (namespace granularity only), and there is no
  UI to change baskets — App & setup displays them read-only and points at the CLI.

- [ ] **History holds personal data but no secrets — verified (2026-09-11).** Every blob in
  history was scanned (566 objects, 355 blobs, seven secret shapes): **no secrets**. Personal
  data is there: 3 Tailscale addresses, 4 machine names, 5 private namespaces, 1 Windows path.
  A rewrite is the only complete fix and breaks every clone and fork; not done deliberately,
  since there is nothing to rotate. **Decision still owed by the user.** Method and the
  if-a-secret-is-found procedure:
  [knowledge/repo-privacy-and-history.md](knowledge/repo-privacy-and-history.md).

- [ ] **First release is not cut.** `shared/version.py` says 0.2.0 and the update check works,
  but there are **no tags and no GitHub release**, so `version --check` correctly reports
  "unknown" for everyone. Tag `v0.2.0`, publish a release, then confirm the check flips to
  "current". Until that exists, the update path is untested against reality. The new read-only
  `git-sync-suggester/packaging/release_check.py` makes the local prerequisites explicit; it
  currently correctly reports the dirty implementation worktree, absent tag, and absent
  disposable PyInstaller environment.

- [ ] **Distribution beyond a hand-built bundle.** Decided direction: one installable app per OS
  acting as a *launcher* for the operations, with the heavy fleet tier opt-in behind first run;
  the clone-and-run-scripts path must never degrade, since it is also the development path.
  Self-replacing update is deliberately NOT built — report-and-tell first, and an opt-in
  "download and replace" only after the version contract has proven itself in the field.

- [ ] **Enroll the remaining machines as peers.** Use `fleet setup` with the existing fleet
  key and chosen transports. No central host is needed. Reuse the fleet key rather than minting
  a separate fleet. Historical machine inventories and reachability are in the work log; check
  actual deployment state before acting. Keep any installed bundle in a durable location before
  enabling per-user start-at-login. Do not infer enrollment from a successful build.
- [ ] **Live deployment validation.** Verify saved-work status across two actual peers, including
  one being offline. The Windows/Linux event mechanisms and independent dashboard ship; actual
  fleet membership and configured transports still need operational verification.
- [ ] **Product onboarding and fleet actions.** Keep the source-checkout path working while
  developing a self-contained installed app. Baskets, unencrypted recovery wiring and narrow
  remote Git jobs remain future work in the agreed tier order. Integration choices are independent;
  nothing requires a particular sync client. Do not expose cosmetic enable switches.

- [ ] **Outside fleet review (2026-09-04) — status.** Recorded by the user; two items were acted
  on the same day, the rest are still open.
  - ~~**Windows discovery returned an empty fleet.**~~ **Fixed 2026-09-04.** The diagnosis in the
    review was exactly right: `os.DirEntry.stat()` on Windows serves data cached from the directory
    scan and that record carries `st_dev == 0`, while the root statted directly reports a real
    device number, so every direct child was rejected as cross-filesystem. `repo_discovery.py` now
    excludes only on **positive evidence** of a different device — unknown never means skip — via
    `device_id()` / `entry_device_id()`, which pay for a real stat only when the cached value is
    absent. `tests/test_repo_discovery_devices.py` reproduces the Windows symptom on any platform
    by faking the cached-zero device; verified it fails ("found 0 of 3") against the old code.
    **Confirmed on the real Windows T: drive:** direct-child scans found all 5 <namespace-a>
    agent repos, all 8 <namespace-b> repos, and all 3 <namespace-c> repos.
  - ~~**Compound facts hidden by precedence.**~~ **Fixed 2026-09-04.** `classify_repository` is now
    documented as a headline for severity *ordering only*; anything that renders or advises uses
    `repository_flags` / `describe_repository` / `secondary_facts`, so a repository that is dirty
    AND ahead now reads `STOP: uncommitted work on cbox (also ahead 9)`. Tests pin dirty+ahead,
    behind+stash, diverged+dirty, missing-upstream+dirty, and that a clean repository invents no
    extras.
  - **Integrations stay optional.** gitSpecOps, the org admin/agent repositories, Digital
    Cartography and <namespace-c> are independent systems that interoperate through small contracts;
    none may become a required runtime dependency of Sync Suggester. Sync Suggester owns its local
    stable machine id (it already does — `config.py`, derived from the hostname and overridable)
    and may *optionally* accept a human label or metadata exported by another tool. Nothing to
    build until a concrete contract is proposed; the constraint is what matters.
  - **Intentionally-dirty trees (patch ledgers).** Org/agent policy may locally annotate such a
    tree as "recorded" or "drifted", but **raw dirtiness must still be published and must never
    become an all-clear**. Not built. The natural home is a local-only annotation in the catalog
    (beside `alias`), displayed alongside the state and explicitly excluded from classification —
    the manifest must keep carrying the raw counts.
  - **Run background operation as the interactive user.** This is implemented for the fleet
    tray and per-user autostart; preserve it for future scheduled legacy commands too.
  - **Note on sequencing:** the review's "watchdog path remains" list was written against
    `9989dc0`, before the 2026-09-03 work. Persistent per-root config and machine identity,
    peer-manifest aggregation with stale/expired rules, optional bounded fetch with honest
    `upstream_observed_at`, and visible polling/watch with semantic-change writes plus heartbeat
    are all **already built** (see [`WORK-LOG.md`](WORK-LOG.md)). What genuinely remains from that
    list is **notifications**, then **explicit handoff**.

- [ ] **`.venv` stays package-free — watch for regressions.** `[tool.uv] package = false` makes
  `uv sync` a virtual project (`uv.lock` shows `source = { virtual = "." }`, no `.pth`). If a stray
  `pip install -e .` or a pyproject edit ever re-adds an `__editable__*.pth` / `git_spec_ops*.egg-info`,
  remove it. See [`knowledge/venv-and-editors.md`](knowledge/venv-and-editors.md).
- [ ] **Duplicator modes 1-3 (download-one / upload / migrate): no CLI flags.** Only
  `--batch`/`--single` have them; `--answers FILE` is the stopgap. Low priority — mode 4 is the hot
  path — and the same `parse_args()` pattern applies if it is ever wanted. (The `CommandTimeout`
  retry half of this item was fixed 2026-09-03.)
- [ ] **Sync Suggester roadmap toward the three-machine fleet.** The product goal is recorded in
  [`new-tool-sync-suggester.md`](new-tool-sync-suggester.md#product-goal-stated-by-the-user-2026-09-03):
  three machines point at their GitHub folder, converge on the same orgs/repos, and stay in sync
  with each other and the cloud, making GitKraken's grouping obsolete for many-org sync
  management. Ordered so schema-affecting work lands before any fleet exists:
  1. ~~Manifest schema v2~~ — **done 2026-09-03** (salted `repo_id`, `head` dropped, `fleet_id`
     mismatch detection). Any further schema change still belongs before a real fleet exists.
  2. ~~Fleet convergence~~ — **done 2026-09-03** (`converge`; names peer hashes by enumerating
     candidates through the provider seam and matching the deterministic HMAC). Still open on top
     of it: convergence currently compares against *peers*, not against the org itself — "the org
     has repos nobody in the fleet has" needs `list_repos` over configured namespaces compared to
     the fleet union, which is a small addition to the same module. Also worth adding: the reverse
     direction (repositories this machine has that no peer does — possibly unpushed local-only
     work).
  3. ~~Source-remote fetching~~ — **done 2026-09-03** as opt-in `--fetch` on `check`/`watch`
     (bounded pool, per-repo stamping, separate remote-freshness accounting). The *scheduled*
     variant is still open: whether a periodic `watch --fetch` is wanted, and at what interval,
     is a policy call now rather than a design one.
  4. **Earlier hook proposal is superseded for the peer app.** Native filesystem event
     observation ships and includes saved edits that Git hooks cannot see. Do not install a
     global hooks dispatcher as part of the current roadmap. Legacy command automation remains
     separate. Joining with a shared fleet key works; automatic key exchange remains follow-up.
  5. `handoff` — **design pass written 2026-09-03** ([`handoff-design.md`](handoff-design.md));
     still unbuilt, on purpose. Its recommendation is to not build it yet: most of "I left work on
     the other machine" is unpushed commits, which `--publish` now covers. Three open questions
     there need the user's answer before any code.
  6. Long-lived stashes: information, or do they block an "all clear"? Currently `stashed` ranks
     above `unknown` but below `ahead`, so it surfaces without shouting.
  7. The **advice → apply** step (clean + behind-only + fresh fetch -> `git pull --ff-only`) stays
     purely advisory until fetching is settled.

- [ ] **Actionable Fleet dashboard, in safety order.** The user wants dashboard-wide and per-repo
  fetch, fast-forward pull, commit and push, plus conflict help and remote execution on an online
  source machine. Build a narrow device job protocol rather than a generic remote shell. Start with
  fetch; allow pull only after a fresh fetch and only for a clean behind-only checkout using
  `--ff-only`; allow push only for a clean ahead-only checkout after revalidation and never force;
  require diff/file review and an entered message for commits. Diverged or conflicted work needs an
  explicit merge/rebase workflow or launch into an installed Git client, not a one-click guess.
- [x] **Recovery snapshots (user names: stealth-stash / stealth-sync) — local chain complete
  2026-09-19.** An opt-in, unencrypted snapshot of staged, unstaged and selected untracked work
  that survives the source machine going offline, can be previewed/applied elsewhere, and expires
  only after retirement proof. Capture, storage, preview, restore, the
  retention/size/ignore/secret-scan/deletion controls, peer checksum acknowledgement and exact
  retirement proof are all built and tested. Availability is still gated on explicit
  recovery-location and capture-basket enrollment, so an unenrolled dashboard correctly shows it
  unavailable — do not present a cosmetic toggle. **Remaining: cross-machine verification on real
  peers**, and the separate open decision on whether unsaved buffer *content* may ever leave a
  machine.

- [ ] **Legacy transports: `state_dir` and `state_repo` both ship; folder auto-detection is not built.**
  The user chose "both, gh-backed first" — the gh Contents API transport landed 2026-09-03. Still
  to do: probe the known OneDrive/Dropbox/Drive/Syncthing/iCloud locations per OS at `init` so a
  machine with a sync client needs no path typed. Detect availability at setup time;
  historical machine observations are not current evidence. `rclone` remains a possible
  advanced escape hatch — 70+ backends, auth configured once — but its own setup is real tedium.

- [ ] **Scale work for mega/enterprise users.** Measured 2026-09-03: a v3 record is ~321 B/repo,
  so ~3,200 repositories fit the Contents API's 1 MB inline read. Open items, in order of value:
  1. ~~Compress the manifest~~ — **done 2026-09-03** as the opt-in `compress_manifests` setting,
     off by default (8:1 measured on real data).
  2. **Selective `--fetch`.** 20 repositories take ~4s at 4 workers, so 10,000 would take ~30
     minutes. Needs to fetch only what is stale or recently touched, not everything.
  3. **Discovery** over very large trees.
  4. Beyond ~20k repositories, shard a manifest per namespace.
  The dashboard already scales — the exceptions view shows only what needs action.

- [ ] **Zero-friction join for the repo transport.** Because a private repo's access control is
  already the boundary (see [`knowledge/manifest-privacy.md`](knowledge/manifest-privacy.md)), the
  fleet key can live inside the state repo, making a second machine's setup just
  `init --state-repo owner/name` with no secret to carry. Explicitly does NOT apply to the folder
  transport. This is the piece that delivers "everything just works as long as gh is authed".

## Someday / deferred

- `--yes` shipped for the duplicator (2026-08-31, batch + single); no `--dry-run` yet.
  `_legacy_sources/` still left untouched.
- Push/"publish" direction: **first slice shipped 2026-09-03** (`archive_sync.py --publish`,
  ahead-only non-force). Not built: per-agent branches + `open_pr()` on the provider seam,
  auto-commit behind a flag, protected-branch awareness, secret/size pre-flight checks. Ship those
  only if the ahead-only slice proves insufficient.
- Multi-host support is a stated goal: archive tools first via `Basic/_providers/` (one
  `<host>.py` that calls `register_provider(...)`, plus its import line in `_registry.py`; fix `remote_identity` URL-port
  parsing first). `github-org-duplicator` stays GitHub-specific by design. Auth stays
  user-owned (host CLI logins); no credential management anywhere.
