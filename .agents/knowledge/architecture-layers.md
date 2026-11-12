# Architecture: the layer stack

**Status:** target agreed 2026-09-20, revised 2026-09-21 (root `_os/`, flat `Basic/`, flat
`App/tray.py`, `_providers/`; see "Revisions" at the end). **Latest revision 2026-11-11:** Special
is this machine, once; Elaborate is other machines or over time; Sync Suggester splits;
`git-sync-suggester/` is emptied and gone; the tree below is current. Migration phase 1 landed 2026-09-21. How to get there is in
[`../HANDOFF.md`](../HANDOFF.md). The picture is [`architecture-diagram.md`](architecture-diagram.md).
[`../README.md`](../README.md) "Repo Shape" describes what is on disk *today* until the migration lands.

## The model

The [product contract](product-contract.md) adds the 2026-10-26 requirements for independent
component use, setup/enrollment, output, integrated security and consistent presentation.
It leaves this layer stack intact; the physical migration below remains unfinished.

`git` is the raw material, and authentication is assumed: the user's own `git` and `gh` are
already set up, and nothing here stores, configures or asks for a credential. Everything is built
downward from there, becoming more elaborate as it builds on the basic operations.

| Layer | What it *is* | What it adds |
|---|---|---|
| **Basic** | one git or host operation | **care**: always a timeout, never interactive, structured results, no `--force` available |
| **Special** | a Basic operation repeated, with the logic of the repetition | **judgment**: which qualify, what to skip, what to collect and report |
| **Elaborate** | wider scale, built on Basic and Special | **reach**: across machines, and across time |
| **App** | all of it, assembled for a human | **presence**: it lives in the tray, if the user lets it |

Clarifications that took several passes to get right, recorded so they are not re-derived:

- **Basic is one operation.** It touches one repository only because that is what a single git
  command touches. The definition is the operation count, not the scope.
- **Special is not "many repos."** A loop running `pull` fifty times is not a Special operation.
  What makes `archive_update` special is the logic of the repetition. That judgment is the layer.
- **Elaborate reaches across machines and across time.** Revised 2026-10-27: plain local archive
  management belongs in Special/archive_manager.py, including selecting archives and invoking
  update or sync once per selected archive. Registry persistence alone does not make it Elaborate.
  Scheduling and fleet coordination remain Elaborate and call that same manager. Scheduled runs
  must not acquire reconciliation/rename/publication authority merely because code moved.
- **App is optional, and it is mostly the tray.** Every operation runs from the terminal on its
  own, forever. The App adds presence, not capability, and nothing may come to depend on it. The
  best thing it does is **suggest sync**.

## The rules

### 2026-10-27 ruling: operations visible, plumbing in private folders

Keep public operation scripts directly in their layer and hide supporting implementation in
cohesive private folders. Name an operation as an action: `update_archive.py`, `duplicate_org.py`.
A role name such as `updater.py` describes its implementation. Prefix the private folder once
(for example `_archive/`); every file inside need not repeat the underscore or folder name.
Apply that principle across layers, with exact grouping reviewed before moves. This supersedes
older trees that mix public operations and private helper files at the layer root, and the
intervening suggestion to hide public commands inside capability folders. Basic/Special/
Elaborate/App responsibilities and dependency direction remain unchanged.

The user also chose the role-oriented public entry point `Special/archive_manager.py` for local
archive management. Operation names must describe their actual job; the verb-first preference
does not prohibit an explicitly chosen manager name.

The user specifically chose `Special/update_archive.py` and a layer-root
`Special/duplicate_org.py`. A complete current Special entry-point mapping follows; additional
verb-first names below remain proposals; the three selected public operations are now in place.

| Previous/current entry point | Destination | Status |
|---|---|---|
| Archive updater | Special/update_archive.py | Canonical entry point; no alias |
| Special/duplicate_org/duplicate_org.py | Special/duplicate_org.py | Implemented; earlier script path is a compatibility wrapper |
| Special/sync_archive.py | Special/sync_archive.py | Naming proposal |
| Special/export_inventory.py | Special/export_inventory.py | Naming proposal |
| Special/restore_inventory.py | Special/restore_inventory.py | Naming proposal |
| Special/scan_tree.py | Special/scan_tree.py | Layer-root placement follows the rule; review the complete map |
| Special/scan_history.py | Special/scan_history.py | Layer-root placement follows the rule; review the complete map |
| Local archive management | Special/archive_manager.py | Shared headless operation; Elaborate handles scheduling only |

### 2026-10-27 archive responsibility split

Special/archive_manager.py is the real synchronous operation entry point. CLI/menu/GUI pass a
request to its callable function; it selects/configures archives, invokes the explicitly
selected update or sync operation once per archive and returns structured results. It does
not need the fleet or a resident process. Keep private manager/updater/sync/plan/registry
helpers in Special/_archive/. Both direct operations and the manager use those helpers; the
manager need not import sibling public command modules. Preserve configured per-archive mode
and explicit invocation choices, show the effective operation, and retain each operation's
review/approval boundaries. Choosing sync does not implicitly authorize unrelated repair or
publication classes.

| Current archive_manage responsibility | Destination responsibility |
|---|---|
| Folder selection, pointed discovery, archive recognition/validation | Special local manager and private helpers |
| Register/list/forget archives, preferences and installation receipts | Special local manager/registry helpers; external user data remains in place |
| Update or sync selected/all archives and collect per-archive results | Special local manager, invoking the selected operation once per archive |
| Per-archive launcher creation, when explicitly requested | Local setup action over the same manager and existing OS launcher seam |
| Scheduled refresh registration/status/removal and scheduled wrapper | Elaborate scheduling, invoking the same Special manager |
| Cross-machine observation, sync suggestions, peer transport and coordinated actions | Elaborate fleet operations; App presents them |

An archive is a selected collection containing at least one actual Git checkout, not merely a
directory with an arbitrary file named .git. Recognition must support valid .git directory/file
forms; operation eligibility (dirty state, origin policy, etc.) is checked separately. A known
repository that cannot currently update does not stop being part of the archive. Default or
pointed discovery and explicitly requested system discovery produce candidates for selection;
discovery never enrolls collections or overrides excluded paths. Specify nesting/depth during
the mapping: the current implementation checks direct children and requires an eligible origin.

Visibility/ownership is not the technical distinction between updater and sync. The updater's
common use is refreshing public/reference collections, but it also works on private repositories.
Existing archive_sync can clone public namespaces not owned by the user as well as reconcile
owned collections. Personal cross-machine synchronization is an Elaborate workflow, distinct
from that archive-reconciliation code. `sync_self.py` is a naming idea, not an agreed rename or
an instruction to turn suggestions into automatic push/pull. Preserve all existing archive-sync
capabilities until their explicit destination/entry-point mapping is reviewed.

Moving the manager requires moving its registry plumbing below Elaborate, updating imports,
launchers/tests/docs and preserving saved identifiers/data paths. Do not introduce a forbidden
Special -> Elaborate import or silently rename persisted settings component identifiers. This
is the implemented source split; no actual user-data relocation has occurred. The current
manager functions retain their exit-code interfaces and existing report/registration behavior.
The standalone updater now has run_update/UpdateRequest/UpdateResult, backed by update_operation.py,
update_cli.py and the shared Special/_runtime/ sinks. It consumes resolved settings without profile
rediscovery and does not print. Other consumers and guided setup remain integration work.
Manager update mode still uses the existing shared sync engine's --update
path; changing that orchestration or its reporting defaults needs explicit functional work.

Implementation grouping proposal: `_archive/` holds updater/sync/plan helpers;
`_org_duplicator/` holds batch/local/remote/tracking/worker helpers; `_inventory/` holds inventory
logic; `_security/` holds scanner/material/check/report helpers; `_settings/` holds schema,
resolution, migration and storage. Settings, archive planning and duplicator helpers are
grouped as of 2026-10-27, with updater/sync/manager/registry and duplicator command implementations
also behind the public facades. The remaining groups still await their bounded moves. This is not
a request for one folder per tiny function or one merged module per entire capability.

Completed settings source mapping (behavior preserved, user data unchanged):

| Previous module | Current module |
|---|---|
| `Special/_settings.py` | `Special/_settings/__init__.py` (same resolver/schema import API) |
| `Special/_settings_records.py` | `Special/_settings/records.py` |
| `Special/_settings_migration.py` | `Special/_settings/migration.py` |
| `Special/_settings_store.py` | `Special/_settings/store.py` |

Completed archive/duplicator helper mapping (public command paths unchanged):

| Previous module | Current module |
|---|---|
| `Special/_archive_plan.py` | `Special/_archive/plan.py` |
| `Special/duplicate_org/_batch.py` | `Special/_org_duplicator/batch.py` |
| `Special/duplicate_org/_local_repos.py` | `Special/_org_duplicator/local_repos.py` |
| `Special/duplicate_org/_operations.py` | `Special/_org_duplicator/operations.py` |
| `Special/duplicate_org/_remote.py` | `Special/_org_duplicator/remote.py` |
| `Special/duplicate_org/_tracking.py` | `Special/_org_duplicator/tracking.py` |

The duplicator retains its existing ignored `Special/duplicate_org/runs/` location. Tracking
anchors that path explicitly from the Special layer; moving helpers or the later command
facade must not select a new empty run directory. Actual user-data relocation remains separate.

The public operation exposes an importable function and a CLI adapter. CLI/menu and GUI invoke
that same function; it delegates to private helpers, which use Basic primitives. For example,
the archive updater selects eligible repositories and repeatedly calls Basic's fast-forward
operation; argument parsing/presentation stay at the entry boundary. The private updater is
not a second independently configured tool.

Before moving code, map imports, tests, documentation, generated launchers, installed entry
points and all paths derived from `__file__`. In particular, the duplicator's resume state is
retained at its original location: moving more code must not select a new empty runs folder.
Keep functional changes and runtime-data relocation separate from source organization.
The frozen `_archive/Security/` remains untouched. Settings, the archive planner and duplicator
helpers have moved under this ruling, and the three selected public operations/local-manager
source split are implemented. Older script paths remain thin compatibility wrappers so installed
launchers are not silently broken. Setup targets the new public paths; it was not run on real
user launchers. Presentation diagrams and the remaining operation families still need review.

- **A file without an underscore is a command. A file or folder with one is plumbing.** `ls` on
  any layer lists exactly what it can do.
- **Every command is also an ordinary importable module**, runnable by its path from anywhere.
  Higher layers call lower ones with a normal `import`. The only subprocesses are calls out to
  `git` and the host CLIs themselves. Imports behave identically on every operating system;
  interpreter discovery, argument quoting and stdout encoding across a subprocess boundary do not.
- **A layer builds only on the layers above it** in the diagram (Basic → Special → Elaborate → App):
  never sideways, never on what comes after. Enforced by a test that reads the imports.
  `_os/` sits beneath all four: every layer may import it, and it imports only the stdlib.
- **Plain names: lowercase words joined by underscores.** No hyphens anywhere.
- **Plain scripts, not a package.** No installation step and no console-script entry points.

## The shape on disk

*Rewritten 2026-11-11 from the tree as it stands after the clean-tree pass. `git-sync-suggester/`
and `_archive/` are gone. A file without an underscore is a command; the rest is plumbing.*

```
gitSpecOps/
├── .agents/          brief, notes, work log, knowledge, diagrams
├── _build/           PyInstaller recipe (GitSpecOpsSync.spec), release_check.py, build notes
├── _docs/            FLEET, DISPLAY-CONTRACT, RECOVERY-DESIGN
├── _os/              beneath every layer: per-OS components, stdlib only (current.py decides)
├── Basic/            one Git or host operation, done carefully
│   ├── clone commit discover fetch pull push reset_keep status
│   └── _confirm _console _discovery _facts _files _history_* _identity _objects _paths
│       _pick _providers/ _run _version
├── Special/          this machine, once
│   ├── suggest_sync name_repo catch_up audit_repos materialize list_live_buffers
│   ├── update_archive sync_archive archive_manager duplicate_org export_inventory
│   │   restore_inventory
│   ├── scan_tree scan_history review_finding clean_history follow_rewrite
│   │   commit_repo push_repo
│   └── _sync/ (observation, advice, manifest, local config and catalog, selection, lock,
│       inventory, actions, git client, VS Code buffers, command adapters)
│       _archive/ _history/ _inventory.py _org_duplicator/ _runtime/ _security/ _settings/
├── Elaborate/        other machines, or over time
│   ├── setup_fleet peer publish_status suggest_fleet_sync converge check_safe_to_wipe
│   │   recovery doctor preflight start_at_login schedule_archives
│   ├── follow_rewrite_fleet request          (placeholders: header and a refusal)
│   └── _fleet/ (fleet CLI and status CLI, routing, config, peer runtime, display contract
│       builder, aggregate, convergence, events, tailnet protocol, store, local view,
│       change fingerprint, start-at-login)  _recovery/  _transport/ (folder, repo)
├── App/              presence and presentation; PySide6 is its only dependency
│   ├── tray serve_web desktop window          (window: placeholder)
│   └── _launch  _tray/ (model, qt)  _web/ (server, remote, _assets, skins/standard,
│       skins/_common)
├── tests/            basic special elaborate app security archive duplicator os repo probes
├── gitso.py          the front door: lists and dispatches every command
└── setup_gitspecops.py  run_setup.*  pyproject.toml (optional extra: app = PySide6)
```

The local-versus-fleet split of the old Sync Suggester: `Special/suggest_sync.py` observes,
classifies and recommends for this machine and publishes nothing; `Elaborate/publish_status.py`
publishes this machine's status; `Elaborate/suggest_fleet_sync.py` reads every machine's;
`Elaborate/peer.py` keeps doing both over time. The peer never imports App: App hands it a
`serve` function (`run_peer(serve=...)`), which is how the tray and `serve_web` attach the web
view, and `--remote` adds the tailnet listener for the user's own devices.

## Providers: the one seam

Host-awareness lives in exactly one place: `Basic/_providers/`. This is the seam the repository
already had (`shared/providers.py`: a `RemoteProvider` Protocol with `list_repos` and `resolve`,
a host → provider registry, and graceful degradation to host-agnostic behavior when no provider
matches). The migration moves it into the stack. It does not redesign it.

- **Adding a host is one module and one `register_provider()` line.** GitLab is `gitlab.py`.
- **Providers register where they live.** The old facade (`remote_provider.py`) and the
  tool-side registration dance (`_register_providers()`) existed only because `shared/` could not
  import tool folders. In the stack that constraint is gone, and so are they.
- **Providers, not "plugins" and not "APIs."** Nothing is discovered or loaded dynamically, so
  they are not plugins. `plain-git` has no API at all and GitHub is reached through the `gh` CLI as
  much as through HTTP, so "API" is too narrow. *Earlier drafts of this document proposed
  `plugins-remote/` and `plugins-local/` folders with contract files, loaders and hyphenated
  un-importable names. Dropped on 2026-09-20: the provider seam already existed and did the job,
  and the hyphen "protection" was bypassable by `importlib` anyway. Do not reintroduce it.*

Use the same Protocol-and-registry pattern for anything else that genuinely gains a second
implementation, such as a second editor alongside VS Code. Until then it is one module.

## Operating systems

Windows, Linux and macOS are peers, **out of the box**. Every per-OS mechanism lives in
`_os/<os>/<component>.py`, and all three OS folders carry the same component files with the same
functions: `_tests/_os/test_os_parity.py` fails if one drifts. Where an OS has no mechanism yet
(the tray on Linux, file events on macOS), its file still exists and reports "unsupported"
rather than being absent, so the gap is visible instead of forgotten.

- **No caller ever branches on OS.** Callers write `from _os.current import paths` and get this
  machine's implementation. `_os/current.py` is the one place `sys.platform` is read.
- **`_os/` sits beneath the layers.** The file-event backend (Elaborate), the state folder and
  process control (Basic) and the tray (App) all need per-OS code, and a lower layer may not import
  a higher one, so the OS folder cannot live inside any layer. It imports only the stdlib, and
  every file in it must import cleanly on every OS (OS-only calls happen inside functions).
- **Only real OS differences go here.** `Basic/_console.py` stays whole: the cp1252 problem is a
  Windows symptom, but the fix is the same code everywhere.

*Revised 2026-09-21.* The 2026-09-20 text said "a per-OS mechanism lives inside the module that
needs it … there is no global per-OS folder." The user overrode that: the OS split must be
visible and complete from the start, not discovered module by module.

## Skins

Three ship: **lcars, modern, retro.** `modern` is today's dashboard; `retro` and `lcars` start as
placeholders. Every skin consumes the versioned display contract
(`_docs/DISPLAY-CONTRACT.md`) and refuses a version it does not recognize. None reimplements Git
or freshness policy. The contract's builder lives in `Elaborate/_fleet/`, not in `App/`, because
deciding what needs attention is policy and the App holds none.

## Sync Suggester: one job, run two ways

*Superseded in part 2026-11-11: the local suggestion moves to Special; see the last revision.*

`check` observes this machine's repositories, publishes its status, and shows the fleet: once.
`peer` does the same job continuously. **One configuration and one observation code path serve
both.** The earlier second runtime is dissolved rather than carried: `watch` (polling) is gone
because the peer's file events replace it; `init` folds into `setup_fleet`; the terminal
`dashboard` becomes `check` without observing; the reserved `handoff` stub is removed.

## Every operation declares its effect

The layer says what an operation is built from. It does not say what the operation *does to your
repositories*, and leaving that to prose is how a Git tool once came to be documented as never
touching Git. So each operation declares one module-level field:

**`EFFECT = "none" | "local" | "remote"`**, where **`none` means nothing you would have to undo.**

`git fetch` writes into `.git/`, yet no branch of yours moves and no file you authored changes.
It is `none`, which is exactly why the background peer may run it. The peer writing its own
manifests and logs is `none` too: that is the tool's bookkeeping, not your repository.

*Rewritten 2026-10-19 with the user.* The rule this section used to assert — "everything
reachable from the peer, tray, dashboard or scheduler is `EFFECT = "none"`" — contradicted the
product: catching up on wake, and committing or pushing from the app, are what it is for, and
the archive scheduled task (`--update`) already broke it. The rule is now about **who started
the change**, not which process runs it:

- **Background entry points** — the peer, the scheduler, wake / sleep / login triggers, and a
  request arriving in this machine's mailbox from another machine. Everything they reach is
  `EFFECT = "none"`, **or** is a consent-gated operation: it declares
  `CONSENT = "<name>"` beside its `EFFECT` and checks, at run time, that the user configured
  that consent for that repository. Without the consent it does nothing and reports a suggestion.
- **Standing consents** are named, narrow, visible in the app, revocable and logged. Only the
  safe class may ever be one: fast-forward of a clean, behind-only checkout after a fresh fetch
  (the auto-update basket; the archive launchers' `--update`). A push of a clean, ahead-only
  checkout is a candidate the user may enable later, explicitly; nothing is on by default.
  **Never** a consent: commit, merge, rebase, reset, rename, delete, origin rewrite, anything
  forced — the operations already kept out of every launcher.
- **Foreground entry points** — the terminal, a tray menu item, a dashboard button — run the
  *same command* with the same plan → show → confirm. A button is not a back door and not a
  second policy.
- **Remotely attended requests** (amended 2026-10-22 with the user) are foreground too: the
  plan is produced by the machine that will act, shown and approved by a person at the machine
  that asks, and bound to that plan; the acting machine re-checks its state and acts or
  refuses. This is how "B, commit this and push" works from A. Forced, reset, rebase, merge and
  delete are not verbs of the protocol at all.

A test collects every declaration by scanning the layer folders and asserts:

> Everything reachable from a background entry point is `EFFECT = "none"`, or declares a
> `CONSENT` and checks it before acting; and no operation whose `EFFECT` is `"remote"` or that
> commits, merges, rebases, resets, renames or deletes declares a `CONSENT` at all.

## Sequencing: this precedes enrolling machines

`autostart` writes an **absolute resolved path** to the peer into the registry Run key, the XDG
`.desktop` file and the LaunchAgent. Moving files after enrollment breaks start-at-login on every
machine, silently. Migrate first, then enroll onto the final layout.

## Revisions, 2026-09-21

Decided by the user while reviewing the folder map, before phase 1 began:

- **`_os/` at the root**, beneath every layer (see "Operating systems").
- **`Basic/` is flat.** `clone`, `fetch`, `pull`, `push`, `status` sit beside the underscored
  plumbing; there is no `Basic/git/` folder. `ls Basic` lists what Basic can do.
- **`App/tray.py`, not `App/tray/tray.py`.** Its per-OS pieces live in `_os/*/tray.py`, so a
  folder would hold one file.
- **`providers/` became `_providers/`**, by the underscore rule: nothing in it is a command.
- **The archive registry moves to the per-user state folder** (`Basic/_paths.config_home()`) and
  is renamed `gitspecops_managed_archives.json` so it is recognizable on its own. It never lives
  in the checkout again.
- **Merges:** one subprocess wrapper for git *and* host CLIs (`_run.py`); one approve step
  (`_confirm.py`); one launcher writer (`_os/*/launcher.py`); `gh_common.py` dissolves entirely.
- **Splits:** terminal renderers leave the policy modules for `check.py`/`converge.py`;
  `archive_manager.py` splits into `archive_manage.py` + `_archive_registry.py` + `_os/*/schedule.py`;
  the version check's GitHub query moves into the provider; `atomic_write_bytes` into `_files.py`.
- **`git_inspect.inspect_candidate` is archive policy, not a fact.** It decides fast-forward
  eligibility against approved remotes, now grouped in `Special/_archive/plan.py`, not
  `Basic/_facts.py` as the first map said.


## Revisions, 2026-10-19

Decided by the user after the test audit:

- **The effect rule is rewritten** — see "Every operation declares its effect" above, and the
  brief's three rules. Background observes, or acts only under a standing consent; foreground
  runs the same confirmed command.
- **The dashboard stays with Sync Suggester, not in `App/`.** Whether `check` / `peer` prints to
  the terminal or opens the dashboard and keeps it refreshed is a setting (and a flag), so the
  dashboard is useful with no tray at all. Its server, the display contract and the skin it
  serves live beside the Sync Suggester engine in `Elaborate/` (exact file names settle in
  phase 3c). The tray *opens* it; it does not own it.
- **`App/` is the tray / menu-bar app** — the live presence: the glance, notifications, the
  menu, and live updates between peers that are online together on the tailnet.
- **Scheduling and start-at-login are owned below `App/`.** `archive_manage` and the per-OS
  `_os/*/schedule.py` / `launcher.py` already own the archive refresh; the peer's start-at-login
  joins them on the same footing. The App only gives controls that call those commands, so
  every schedule can be set, inspected and removed from the terminal too.
- **Skins: `modern` only, for now.** `lcars` and `retro` are deferred, not dropped; the display
  contract keeps them possible.
- **Command surface for people and agents.** Every command can be fully specified by flags —
  a complete set of flags never prompts — so an agent (or a script) drives it with a string of
  flags. Higher-level operations read saved settings, so they run with no flags at all and the
  same flags override a setting for one run. Machine-readable output is added where something
  consumes it, deliberately, not to every command. A usage guide instructs agents; plans and
  confirmations belong to the human even when an agent holds the flags.
- **Mailboxes:** each machine has an inbox in the private state repository (delivered at once
  over the tailnet when both are online). Requests are a small fixed set of verbs, never a
  shell; they run unattended only under a standing consent, otherwise they wait as suggestions.
- **KDE Plasma on the Debian box** (Wayland): StatusNotifierItem tray icons work natively.

## Revisions, 2026-10-19 (later): `Security/`

At the user's request, the scanning and history-cleanup tools live in their own folder,
**`Security/`**, ranked in the import rule between `Special/` and `Elaborate/`
(`_os -> Basic -> Special -> Security -> Elaborate -> App`): it builds on Basic and Special,
and the fleet (Elaborate) or the App may call it — for example a fleet-wide audit later.

- `_patterns.py` — the one set of detection rules, shared with the repository's own hygiene test.
- `_seeds.py` — the runner's identity, read at run time and held in memory only.
- `_history.py` — reads everything a history publishes, commit identities included.
- `scan_tree.py`, `scan_history.py` — read-only commands (`EFFECT = "none"`). Masked on screen;
  each writes a full, unmasked report.
- `scan_secrets.py` — runs **gitleaks** when it is installed. gitleaks is optional, like the
  tray: the front-door setup offers it, nothing requires it.
- **Output lives in this checkout's git-ignored `.agents/output/security/<repo>/`**, whatever
  repository was scanned, so the person and their agents read it in place (user's decision,
  2026-10-19); the per-user folder is the fallback when that folder is not ignored. A plan may
  sit inside the scanned repository only where git ignores it.
- The never-publish list stays in the per-user folder: it serves every repository.
- `rewrite_history.py` — `plan` (private plan folder outside the repository + a bare clone),
  `apply` (git filter-repo in that clone only, after a typed confirmation), `verify`. Its
  `EFFECT` is `local`. **The forced push that publishes a rewrite is never performed by
  gitSpecOps**: the tool prints it, the person runs it.

## Revisions, 2026-10-20: security inside the layers; `shared/` gone

Decided by the user:

- **There will be no Security layer.** Security lives inside each layer it occupies:
  components and single-repository commands in `Special/_security/`, the top-level
  `clean_history` in `Elaborate/security/`, and the general history-rewriting machinery in
  plain `Special/`. The 2026-10-19 rank (`Special -> Security -> Elaborate`) stays in the import
  test only until the old `Security/` folder is deleted at the cut-over. Full design and plan:
  [`security-design.md`](security-design.md).
- **`Basic/reset_keep.py`** joins the Basic operations: moves the checked-out branch with
  `git reset --keep`, never overwrites an edit, has no other reset mode.
- **`shared/` is deleted.** The version number is written once, in `pyproject.toml`, and read by
  `Basic/_version.py`. `App/version.py` in the tree above was wrong: the
  display contract (Elaborate) needs the number, and Elaborate cannot import App.

## Revisions, 2026-10-22: the App is Qt; remote requests

Decided by the user:

- **The App uses Qt through PySide6** (the official Qt for Python, LGPLv3: free to use and to
  ship as a dependency). One codebase gives a native tray on Windows and KDE Plasma (KDE is Qt;
  StatusNotifierItem on Wayland), the macOS menu bar (no Swift needed), and a real application
  window that can replace the web dashboard as the main view. It is the App's dependency only:
  every operation below `App/` stays standard-library Python. The Qt window is one more skin
  over the versioned display contract; the web dashboard may stay for viewing from another
  device or retire later. A small trial (tray + window over the contract) runs here and on the
  Debian 13 KDE box before the tray work proper; the hand-written Win32 tray is then retired.
- **Remote requests between the user's own machines** -- see "Remotely attended requests"
  above. Over the fleet's peer protocol on the tailnet, not SSH: SSH would hand gitSpecOps a
  whole shell (with per-OS quoting) where a few fixed verbs are enough, and turning SSH on is a
  system and credential change gitSpecOps must not make for the user.

## Revisions, 2026-11-11: this machine, or machines and time

Decided by the user:

- **The rule between Special and Elaborate.** Special is this machine, once. Elaborate is other
  machines, or over time. It restates the model table (judgment versus reach) as the test every
  operation is sorted by.
- **Sync suggestion splits by that rule.** Suggesting sync for this machine's repositories
  (observe, classify, recommend) is a Special operation that runs with no fleet. Publishing this
  machine's status, combining other machines' reports into a fleet suggestion, and the
  continuous peer are Elaborate. `check` as "observe, publish, show: once" is no longer one unit.
- **Follows from the rule:** scanning many repositories on one machine (for example every public
  repository) is Special and does not wait for fleet work.
- **Clean tree before install.** Every file the target tree expects exists, at minimum with a
  header saying what it is for. `git-sync-suggester/` is emptied and removed; whatever can be
  built from its contents is built and complete. A file-by-file mapping is reviewed with the
  user before anything moves.
- **Both GUIs, set by the user.** The usual setup is the Qt app: tray plus window. A web server
  is optional: run it headless to watch the fleet from a phone or tablet over the tailnet, or
  use the web dashboard all the time, with or without the tray. The tray can open either the
  Qt window or the web view. Every combination is a setting and all of them must work. Both
  read the same display contract. The 2026-10-19 ruling that the dashboard stays with Sync Suggester in `Elaborate/`
  is reopened; the file-by-file mapping places it.
- **Presentation lives in `App/`:** the web server and skins in `App/_web/`, the tray, the Qt
  window. The display contract builder stays in `Elaborate/_fleet/` (deciding attention is
  policy). The web side runs without Qt installed.
- **First the Qt tray opens the web view;** the Qt window comes later. The hand-written
  Windows tray is deleted after its useful parts are extracted.
- **Remote watch and act from a phone or tablet is built,** off by default, tailnet only.
- **The network map:** machines as nodes by report freshness, repos needing attention on each,
  matching repos across machines lined up visually. Views switch between machines together,
  the whole library, one library folder across machines, one org across machines and one
  repo across machines; a chosen machine sets the perspective.
- **`_archive/` (version 1) is ported where still needed, then deleted.** `tests/` keeps its
  name. Execution plan: `../HANDOFF-CLEAN-TREE.md`.

## Revisions, 2026-11-11 (later): machine enrollment apart from fleet enrollment

Decided by the user:

- **Machine to app, app to fleet.** Enrolling the machine (`Special/enroll_machine.py`: its
  library folders and its presentation choice) is this machine, once, and is enough for the
  tray, the web view and every local command. Joining a fleet (`Elaborate/setup_fleet.py`: a
  key, then any combination of the synced folder, the private GitHub state repository and
  Tailscale) is the separate, later step; `leave` undoes it and keeps the machine.
- **Several libraries per machine,** added one or more at a time, never overlapping. Nothing is
  inventoried before the person names the folders and types SCAN; `find` suggests libraries
  (a folder, or `--whole-machine`) only after LOOK, and enrolls nothing.
- **Double-click opens the app's face,** web or the Qt window, as the user chose; the web view
  can be off entirely (the window then reads the peer in-process). Single click does nothing.
- **Fleet features are tested end to end:** two peers exchanging status through a synced
  folder, through a stand-in for the GitHub Contents API, and over a loopback stand-in for the
  tailnet, plus every transport at once (`tests/elaborate/test_fleet_transports.py`).
- Stored shape, no migration: the settings document's `machine` block and the app component's
  libraries are the machine enrollment; the app's transport selection is the fleet enrollment.
  The app record's defaults live in `Special/_sync/enrollment.py`. A fleet key can be replaced
  only while no transport is selected (nothing was shared under it).

