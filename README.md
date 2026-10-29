# gitSpecOps 

**git Special Operations** — careful, boring, stdlib-only tools for when you have far too many
Git repositories and doing it by hand has stopped being reasonable.

**Work-in-progress checkpoint:** settings, security and interface integration has changed
substantially and is still under way. Direct/CLI components have focused Windows evidence;
complete GUI parity, native Linux/macOS and real-fleet acceptance remain unfinished. This
checkpoint preserves development progress and does not declare a finished release.

**Work-in-progress checkpoint:** settings, security and interface integration has changed
substantially and is still under way. Direct/CLI components have focused Windows evidence;
complete GUI parity, native Linux/macOS and real-fleet acceptance remain unfinished. This
checkpoint preserves development progress and does not declare a finished release.

Each operation is the kind of script you would eventually write yourself, with the dangerous
parts already thought through: it shows you a plan before it acts, it refuses anything ambiguous,
and it never touches your credentials.

The common source launcher is `python gitso.py`: use `commands` to list operations, `docs`
to read source-derived usage, or a command such as `scan-tree --help`. With a terminal it also
offers a menu. Existing direct scripts remain supported; the launcher calls their entry
functions and preserves their individual behavior. It does not install a shell alias.

Security scans use built-in checks without extra Python packages. Optional credential engines
can be selected individually or together with repeatable `--engine gitleaks`, `--engine
betterleaks` or `--engine trufflehog`; `--engine none` overrides saved selection. Selected
unavailable/unsupported engines report incomplete checking. Findings are masked but include
locations, line numbers, finding ids and review guidance. No engine is installed automatically;
native engine/version validation remains development work.

Archive Sync's explicit `--publish` action now checks the exact outgoing history before sending
one planned commit/branch. Prohibited values, high-confidence credential patterns, unresolved
findings and incomplete checks hold the push; `--yes` does not bypass security. An earlier
commit can still block publication even if the latest files are clean. The direct checked
commit and push commands use the same checks. Select a profile with `--settings-home`;
security scan/review/commit/push commands can explicitly read existing text policy using
`--legacy-policy` without converting settings. Basic Git operations stay policy-free.

Full reports are explicit: `--out` creates a new private JSON file at the selected destination.
Outside Git, choose storage you control; inside Git the destination must be ignored and
untracked. Existing files, links and invalid destinations are refused, without fallback.
Normal stdout remains masked and lists the actual report artifact.

For a documented example or test fixture, preview a review tied to that exact finding/content:

```sh
python gitso.py scan-tree /path/to/repo --settings-home /private/profile --out /private/reports/scan.json --json
python gitso.py review-finding /private/reports/scan.json finding-000001 --settings-home /private/profile --reason "Reviewed example"
```

The review preview writes nothing. Rerun the same arguments with `--apply --approve REVIEW_PLAN_ID`
using the returned plan id. The private decision records the reason; ordinary output does not
repeat it. Rescan before taking an action. Changed bytes, location or repository require review
again; unchanged accepted examples stay visible with a review id. Prohibited values, strong
credentials, unsupported external-engine findings and coverage gaps cannot be waived.
To revoke, replace the finding argument with `--revoke REVIEW_ID`, preview and approve that plan.
Records stay local under the selected profile; they are not automatically shared with the fleet.

If Git's line-ending conversion or a clean filter changes a reviewed working file when staged,
the commit check can hold the different staged bytes. Use `scan-tree --staged --out FILE` to
inspect/review those staged changes, then create a fresh commit preview. This scan never stages
or commits anything and leaves the working files alone. It excludes deleted versions and
unstaged/untracked bytes; use history scanning separately for old material.

**Dangerous history maintenance:** `clean-history` plans explicit cleanup and rewrites only a
new private mirror. It preserves the source checkout and never publishes. Start with a full
private `scan-history --out` report, then select finding IDs and explicit paths in a choice
document. `python gitso.py docs clean-history` gives the current JSON format directly from source.
Raw protected values are read programmatically; an agent does not need them in its choice file.

```sh
python gitso.py clean-history plan /private/history.json --choices /private/choices.json --settings-home /private/profile --include-remote-refs --plan-out /private/plan.json --json
python gitso.py clean-history apply /private/plan.json --settings-home /private/profile --workspace /private/new-run --approve PLAN_ID
```

Use the same selected profile/policy mode for both steps. Tracking refs require explicit
inclusion; their names, remote-only commits and symbolic aliases are preserved without fetching.
Apply requires an attended terminal and typed `REWRITE`; there is no `--yes` or confirmation flag.
The exact plan, native diagnostics and full rescan remain private, with masked results and
presented artifacts. Settings/report/log failures never select another location or profile.
Remaining findings or coverage gaps hold the result for review. A verified mirror does not
rotate credentials, erase other copies, authorize publication or update other clones.

---

## The special operations

### 1. GitHub Organization Duplicator

*Copy an entire namespace — down, up, or across — without clicking through a hundred
repositories.*

```bash
python3 Special/duplicate_org.py
```

Downloads every repo in an org, uploads a folder of local repos into one, or migrates org → org.
Previews what it will do, checks for name collisions before any remote call, asks for typed
confirmation, and writes resumable run files so an interrupted 300-repo migration continues
instead of restarting. Handles private/archived/fork filters, mirror or working clones, and
parallel workers.

### 2. Archive Updater

*Point it at a folder full of clones and keep every one of them current, safely.*

```bash
python3 Special/update_archive.py --root /path/to/archive
```

Use `--scan-only --json --no-log` for a machine-readable inspection without report or log
files on an unconfigured profile. Saved roots, exclusions and output/logging preferences are
optional; explicit flags override them. Reports are off by default, while compact counts-only
logs default to the selected user-data home. `--no-report` forces stdout and `--no-log` disables
logging separately. Legacy settings require explicit migration; they are never silently adopted.

**Fast-forward pulls only.** It never merges, rebases, resets, stashes, or deletes; a repository
that is dirty, diverged, or on an unapproved remote is reported and skipped, not "fixed". The
richer engine (`archive_sync.py`) additionally discovers an org's full repo set and can clone
what is missing, repair stale origins after a rename, and rename folders to match upstream —
each as a separate, explicitly approved class of change.

Manage registered archives with current saved choices:

```sh
python3 Special/archive_manager.py --list
python3 Special/archive_manager.py --refresh /path/to/archive --scan-only --json --no-report --no-log
python3 Special/archive_manager.py --install /path/to/archive --mode update
```

Use `--settings-home /path/to/profile` to select a profile. Existing common v2 settings own
archive choices; legacy-only profiles retain their registry without automatic migration.
New archive launchers read saved choices when run. Reinstall without mode/remote-prefix flags
to preserve those choices; older launchers need deliberate regeneration before migration.
`--forget` removes common registration while retaining receipts and launchers for review.
Refresh uses common `archive_manage` output/logging preferences. Reports default off; a saved
preference or `--output-dir` enables one aggregate report. `--output-mode stdout|file|both`,
`--json`/`--format`, `--no-report`, `--log`/`--no-log` and `--log-dir` override those choices.
Invalid selected sinks stop the operation without choosing another location. Structured results
list the actual report/log artifacts; file-only mode announces them on stderr. Update mode uses
the Git-only updater; sync mode retains approved pull/clone discovery. Refresh never publishes,
rewrites origins or renames folders. `--force-sync` changes only that invocation's mode.

Programmatic callers can import `run_refresh` from `Special.archive_manager`; it returns a
masked result with per-archive operations, outcomes and partial failures, without printing or
capturing process output. Scan-only leaves receipts unchanged. Actual run receipts record
status/time, while report locations come from the invocation's artifacts; status no longer
guesses a report by searching archive folders. Registration/launcher creation and scheduling
retain their separate workflows and remaining legacy logging.

### 3. Sync Suggester

*Know what every one of your machines left unfinished — which clone on which computer has
uncommitted work, unpushed commits, or a report too stale to trust — and then put it all in
order from wherever you are sitting.*

```bash
python3 git-sync-suggester/sync_suggester.py check          # what needs attention, everywhere
python3 git-sync-suggester/sync_suggester.py fleet catchup   # plan a group fast-forward
```

An existing common profile owns CLI/app enrollment. Select it with `--settings-home` before
the command (after `fleet` for app commands); `--config-dir` separately selects local fleet
state and legacy inputs. CLI and app keep their own transport selections. Invalid common
settings never fall back to old files, and saves preserve other components. Profiles with
only legacy configuration still work in place. Common migration remains an explicit,
unfinished workflow; nothing is migrated merely by running a command.

Across machines it becomes the thing you actually want at 2am: "you left 17 uncommitted files on
the laptop." Then it helps you fix it: group fast-forward everything after weeks away, publish
ahead-only work, clone a set you are missing, or recover uncommitted work stranded on a machine
that is currently switched off.

**Watching never changes anything by itself.** The background peer observes, publishes and
fetches. It changes a repository only where you set up a standing consent for it — fast-forward
of clean, behind-only checkouts, say, on wake — and never commits, merges, rebases or forces.
Everything else is a command you ran, from the terminal or a button, with a plan shown first and
nothing ambiguous applied.

---

## Requirements and hard assumptions

Read this once; it explains most of the design.

| | |
|---|---|
| **Python 3.11+** | No runtime dependencies. Everything is the standard library. |
| **`git` on PATH** | Every Git operation shells out to your real `git`. |
| **`gh`, already authenticated** | Required for anything that talks to GitHub. |

```bash
gh auth login      # you do this; gitSpecOps never does
```

**The hard assumption is that authentication is yours and stays yours.** gitSpecOps stores no
token, writes no credential file, configures no keyring, and never prompts for a password. It
shells out to CLIs you have already logged into. If `gh` is not authenticated, GitHub-aware
features decline to run — they do not fall back to asking you for a secret.

Consequences worth knowing up front:

- Anything GitHub-specific (org listing, repo creation, following renames) needs `gh`. Plain
  archive updating needs only `git`, and works against any host.
- `GIT_TERMINAL_PROMPT=0` is forced everywhere, so a repository with expired credentials fails in
  under a second instead of hanging forever on an invisible prompt.
- Every subprocess has a timeout. Nothing blocks unbounded.

**Optional, and only where named:** `uv` (faster environment setup), Tailscale (live fleet tier
only), a folder-sync client or a private GitHub repo (cross-machine status transport).

---

## Install and run

There is no install step. Clone it and run the scripts:

```bash
git clone https://github.com/sb4ssman/gitSpecOps
cd gitSpecOps
python3 Special/archive_manager.py --help
```

Optionally, `run_setup` builds a clean `.venv` and writes one convenience launcher per tool for
your OS (`.sh` on Linux/macOS, `.ps1` + a `.bat` double-click shim on Windows):

```powershell
.\run_setup.bat          # or ./run_setup.sh
.\duplicate-github-org.bat
```

Launchers are **generated, never committed** — edit `setup_gitspecops.py`, not a launcher. The
project is deliberately *not* installed into `.venv`; the tools are plain scripts and `.venv` is
just a predictable interpreter.

Updater preferences can be configured without installing launchers or enrolling a fleet:

```bash
python3 setup_gitspecops.py settings
python3 setup_gitspecops.py settings-preview --root /path/to/archive --no-log --json
python3 setup_gitspecops.py settings-save --root /path/to/archive --no-log --json --approve '<review-id>'
```

Guided setup reviews changes and requires typed `SAVE`. For assisted use, copy the preview ID
and keep the same target/options when saving; changed files invalidate it. Paths are hidden
unless `--show-paths` is selected. A custom `--settings-home` stays an explicit invocation/
environment choice, without relocating other profiles. `settings-migration-preview` can inspect
legacy mapping. For an archive/security-only profile, use the reviewed existing-settings setup:

```sh
python3 setup_gitspecops.py settings-existing
python3 setup_gitspecops.py settings-existing-plan --json
```

The plan changes nothing. Guided saving requires separate confirmation that legacy writers are
stopped and the launcher plan was reviewed, then typed `SAVE`. Assisted use has an explicit
`settings-existing-save --approve '<review-id>' --legacy-writers-stopped --launcher-plan-reviewed`
action. Original bytes are retained under the selected user-data home before shared settings
are created. `settings-existing-status --switch-id '<review-id>'` inspects any interrupted switch;
`settings-existing-resume` requires the two confirmations again and refuses newer data. Add
`--settings-home /path/to/profile` when needed. Paths are hidden unless the plan's `--show-paths`
is selected. Launcher repair/retirement stays a separate choice; this action does not run Git,
refresh archives, change scheduling or enroll a fleet. Profiles with existing fleet configuration
need a separately reviewed conversion.

---

## Security scans

Active scans use common security policy and print masked results without creating reports or logs:

```sh
python3 Special/security/scan_tree.py /path/to/repo --settings-home /path/to/profile --json
python3 Special/security/scan_history.py /path/to/repo --settings-home /path/to/profile --json
```

Saved protected values remain in force when an additional `--never-publish` file is selected.
`--safe-file` and `--safe` add allowances; conflicting protected/safe values produce an error.
Excluded roots or subtrees are refused before inspection. `--out` explicitly requests a full
private report using the current ignored-location rules.

For an unmigrated profile, `--legacy-policy` explicitly reads its old text lists without
changing them. It refuses an existing common settings file. Default scans never silently
fall back to legacy policy. General settings conversion, policy editing UI and fleet/action integration remain
unfinished; these scans do not enforce commits or pushes in other tools.

### Checked named-file commits

Preview the working-tree files, message and effective Git author/committer before committing:

```sh
python3 gitso.py commit /path/to/repo file.py docs/usage.md -m 'Describe the change' --json
python3 gitso.py commit /path/to/repo file.py docs/usage.md -m 'Describe the change' --apply --approve '<plan-id>'
```

Use the same arguments and the preview's `plan_id`; changed inputs invalidate approval.
`Special/commit_repo.py` is the equivalent direct entry point. Both accept `--settings-home`.
Only the named files are committed, using their whole working-tree contents, preserving other
staged work. This is not a commit of the entire index. Checks include Git-filtered staged bytes
and the final native hook inputs. Findings needing review and incomplete checks hold the action.

Existing traditional hooks retain their order through a temporary per-invocation relay; no
hooks or Git settings are permanently installed. Requires Git 2.36 or later. Direct individual
files/deletions on an attached branch are supported; directories, linked files, merge/rebase
states and newer configured hook chains require compatibility work. Hook edits to approved
contents/message require another preview. A refusal after staging leaves the selected files
staged. If Git already created a commit and final verification fails, the result says `partial`
and reports whether a commit was observed; inspect locally before retrying. Nothing is pushed
or automatically undone. Native Git/hook error text stays out of normal text/JSON output.

### Checked publication and sync advice

```sh
python3 gitso.py push /path/to/repo --json
python3 gitso.py push /path/to/repo --apply --approve '<plan-id>'
python3 gitso.py sync --settings-home /path/to/profile check --root /path/to/library --local-only --no-publish --no-catalog --json
```

`Special/push_repo.py` is the direct push route. Preview selects the local branch/tip/destination
and policy without network access or outgoing security clearance. Apply requires the unchanged
plan, fetches and checks actual outgoing history through the same gate as Archive Sync, then
publishes that fixed branch snapshot. There is no force, extra-tag or security-bypass option.

Sync `check` now checks local working files and cached outgoing history alongside Git status.
Missing upstreams, stale scope, selected-engine failures and unsupported mappings are explicit;
advice does not authorize an action. Its JSON is a local envelope with `schema_version`,
`manifest`, `local_security` and `artifacts`, replacing the former bare-manifest stdout. Only
`manifest` is sent to transports. Security findings stay local. Observation still succeeds with
alerts so useful sync facts remain available; inspect each security `check_status`.

The running local peer dashboard offers **Check local security** on observed local repositories.
It invokes the same reader for every local copy and displays timestamped masked findings and
coverage in session memory. It writes no report and shares no findings. Existing manifest-only
dashboards and watch mode do not perform these checks; fleet status alone is not clearance.

Fleet setup now hides generated keys. Use `gitso sync fleet-key` or `gitso app fleet-key` for
metadata; `--show` deliberately prints the raw key here. An agent capturing that output sees it.
The native Windows tray uses the shared event/counter logger at the selected app logging
directory (`<user-data>/logs/app_tray.log` by default), respecting disabled logging and sink
errors. Console output and shown keys are not copied into logs or notifications.

## Archive updating in more detail

### `update_archive.py` vs `archive_sync.py`

Both fast-forward clean repositories. The difference is remote discovery:

- **`update_archive.py`** — `git` only, no network beyond the pull. It updates what is already
  on disk. Works with any Git host.
- **`archive_sync.py`** — asks a provider (GitHub via `gh`) what *should* be there, so it can
  clone missing repositories, spot renames, and flag orphans.

If no provider matches the host, or discovery fails, `archive_sync.py` **degrades to update-only**
— it pulls every clean repo and never invents a clone, an orphan, or a rename from a failed
listing. That fallback is enforced by a flag (`remote_authoritative`) and pinned by tests.

Identity is by **stable provider id**, never by folder name or URL. GitHub node ids survive both
repository and organization renames, so a deliberately renamed local folder is preserved while
genuine upstream drift is surfaced for you to confirm.

### `archive_manager.py` — the local front door

Registers archives, installs per-archive launchers, refreshes saved update/sync modes and writes
local logs. Scheduling remains in `Elaborate/archive_manage.py`. The registry, log and scheduled
refresh-all launcher live in
your per-user gitSpecOps folder (`%APPDATA%\gitspecops` on Windows, `~/.config/gitspecops`
elsewhere; `GITSPECOPS_HOME` overrides), never in the checkout, so the scheduled task keeps
working when the code moves.

```powershell
python Special\archive_manager.py --refresh-all --scan-only
python Elaborate\archive_manage.py --install-monthly-task --task-day 1 --task-time 09:00
python Elaborate\archive_manage.py --task-status
```

Generated archive launchers only refresh saved update/sync choices. Origin and folder repairs
require explicit archive-sync flags. Registration selects the saved mode, then offers a normal
refresh; it does not repair repositories while registering them.

`Special/update_archive.py` is the updater. `Special/archive_manager.py` owns registration and
local refresh. `Elaborate/archive_manage.py` only creates refresh-all launchers or manages
scheduling; it does not accept local management flags. Generated refresh-all launchers invoke
the Special manager directly. Existing launchers are never rewritten automatically.

Archive commands default to stdout, with optional counts-only local logging. Saved settings or
`--output-mode`, `--output-dir`, `--json`, `--log` and `--no-log` select channels. Required
destinations fail explicitly without fallback. Results list actual report/log artifacts;
file-only commands present their destinations on stderr. Direct scripts and `gitso` use the
same headless operations. Archive sync defaults to a preview; mutations require approval,
including `--yes` when invoked without a terminal.

### Publishing — explicit remote writes

```bash
python3 Special/archive_sync.py --root /path/to/archive --publish --dry-run
```

`--publish` pushes **without `--force`**, so Git itself refuses anything that is not a
fast-forward — the mirror image of `pull --ff-only`. Only clean, ahead-only repositories are
eligible. Diverged goes to a human; behind-only needs a pull first. It re-fetches immediately
before pushing, so "the remote moved" is reported rather than forced. It is its own apply class
and **cannot** be combined with update/sync/reconcile, nor emitted by any generated launcher or
scheduled task. Nothing is ever auto-committed, under any flag.

---

## Sync Suggester — the optional, larger one

The first two operations are careful scripts. This one is a small distributed system, so it is
opt-in and configured once per machine.

Every machine observes itself and writes **one file that it alone owns**; no machine is in charge
of another. That single-writer rule is why there is no conflict-resolution code anywhere in this
repository.

### Three transports — use as many as you can

They are complements, not alternatives. Each one is another way for a machine to leave a
fingerprint and another way for you to read one, so configuring all three is the goal rather
than a choice you have to make:

| Tier | What carries your status | Needs | Gives you |
|---|---|---|---|
| **Durable** | a private GitHub repo, via the Contents API — never cloned | your `gh` login | retains published status when a peer is offline |
| **Medium** | a folder your own sync client already replicates | any sync client | fast, no API budget |
| **Live** | machines talking directly over Tailscale | Tailscale | near-real-time, readable peer names |

```bash
python3 git-sync-suggester/sync_suggester.py init --state-repo owner/private-repo --root ~/code
python3 git-sync-suggester/sync_suggester.py check            # observe, publish, advise
python3 git-sync-suggester/sync_suggester.py dashboard        # text, every machine
python3 git-sync-suggester/sync_suggester.py dashboard --serve  # the browser dashboard
```

**The dashboard is local and needs nothing else to be running.** `dashboard --serve` binds to
loopback on this machine and renders whatever manifests it can read from whichever transports
are configured. No Tailscale, no second machine awake, no server anywhere. A laptop that has
been shut for a week still appears, with its last known state and an honest "this is three days
old" — because the freshness rules treat an old report as old, never as an all-clear.

That is the point of publishing to more than one transport: a machine that is unreachable right
now has usually still left a fingerprint somewhere you *can* read.

**The peer runtime ships:** `fleet setup` configures an independent machine, and `fleet run`
resumes it. Each peer observes through native filesystem events, serves its own loopback
dashboard, publishes to its configured transports, and optionally pulls from tailnet peers.
No central host is required. Existing host/client configurations migrate automatically.
See [the fleet guide](git-sync-suggester/docs/FLEET.md) for setup and transport commands.

### Catch up safely

When returning to a machine after time away, use the fleet command instead of pulling an
unreviewed pile of checkouts by hand:

```sh
python git-sync-suggester/sync_suggester.py fleet catchup
python git-sync-suggester/sync_suggester.py fleet catchup --apply --yes
```

The first command always performs a fresh, non-interactive fetch for each locally observed
checkout and prints a plan. It changes no branch, index, or working file. The second command
repeats that plan and fast-forwards only checkouts that are clean and behind-only; `--yes` makes
the mutation explicit for terminal and unattended use. Dirty, untracked, ahead, diverged,
detached, no-upstream, unreadable, and failed-fetch checkouts are listed for a human and are
never altered. Catch up neither commits nor pushes work. Stop the local peer before running it;
the command's configuration lock enforces that boundary, then the next peer start publishes the
new status.

### What crosses the wire

Published manifests (schema v5) identify repositories by `HMAC-SHA256(fleet secret,
host/owner/name)` — or, for a repository with no usable remote, an HMAC of its root commit, so
the only copy of something is still on the map. **By default each record also names the
repository, its checked-out branch and its current commit**, so every machine can show — and
route you to — what the others hold, even a machine not seen in a week. One setting
(`--withhold-names`, or "no" at setup) turns that off, and then a record is salted digests and
small integers only. Never published, either way: local paths, URLs, filenames, diffs, commit
messages or source content. A synced folder's provider can read whatever the manifest carries;
setup says so beside the question. Details and honest limits:
[`.agents/knowledge/manifest-privacy.md`](.agents/knowledge/manifest-privacy.md).

Two rules that make the advice trustworthy:

- **Silence is never good news.** A report too old to trust can never produce an "all clear"; a
  stale clean report becomes `unknown`, while stale unfinished work keeps its warning.
- **Machine freshness and remote freshness are separate clocks.** A manifest written a second ago
  says nothing about how old its remote-tracking refs are, and the dashboard says which is which.

---

## Layout

```text
Basic/                 careful primitives: one subprocess wrapper, repo facts, discovery,
                       prompts, state paths, and the host providers (Basic/_providers/)
_os/                   per-OS pieces, the same files for Windows, Linux and macOS
Elaborate/             archive_manage: scheduling and legacy command compatibility
Special/               update_archive, archive_sync, archive_manager, duplicate_org;
                       shared implementation in private helper folders
git-sync-suggester/    the optional fleet tool (see below)
tests/                 offline, synthetic; no network, no real repositories
.agents/               project brief, working notes, work log, durable knowledge
```

Sync Suggester is the largest, so its modules are grouped by role. They remain flat scripts —
no package, no console-script entry point; `_paths.py` widens `sys.path` once, in whichever file
is executed:

```text
git-sync-suggester/
  sync_suggester.py   the CLI: check, dashboard, converge, watch, doctor, fleet
  core/               observation, manifests, advice, config, transports
  fleet/              live tier: protocol, SQLite store, observer, display contract
  app/                process shells: fleet app, tray, desktop bundle, start-at-login
  ui/                 browser assets, served by exact name; never imported
  packaging/          PyInstaller recipe and build notes
  docs/               FLEET.md, DISPLAY-CONTRACT.md
```

`core/` knows nothing about the live tier or the UI, and `fleet_display.py` is the only module
permitted to turn fleet state into display semantics — every skin, the tray included, consumes
that versioned contract rather than reclassifying Git facts.

---

## Safety model

- **Fast-forward only, everywhere.** Pulls are `--ff-only`; the single push path is a non-force
  push. Git itself refuses anything that would lose work.
- **Detect → show the plan → approve by class → execute gracefully → review.** Failures are
  collected, never fatal, and reported at the end. Nothing ambiguous is auto-applied.
- **Destructive-adjacent actions are interactive-only** and require typed confirmation. They are
  structurally excluded from scheduled and launcher runs.
- **Watching never changes anything by itself; background change only under a consent you
  configured; everything else is a command you invoked.** Nothing is changed as a side effect of
  observation, or of time passing. The only unattended change is one you set up explicitly and
  can see and revoke — fast-forward of a clean, behind-only checkout, as the archive launchers
  already do — and no consent can cover a commit, merge, rebase, reset, rename, delete or force.
  A tray item or dashboard button runs the same command as the terminal, with the same plan and
  confirmation. Sync Suggester's mutating operations
  (`fleet catchup --apply`, `fleet materialize --apply`, recovery restore) are named, confirmed,
  refuse to run beside a live peer, and follow the same plan-then-approve ladder as the rest.
- **Bounded everything.** Per-command timeouts, bounded discovery, bounded thread pools, forced
  non-interactive Git so nothing can hang on a hidden prompt.
- **Your credentials stay yours.** No token is read, stored, forwarded, or logged.

When unsure, look before you leap:

```bash
python3 Special/archive_manager.py --refresh-all --scan-only
python3 Special/archive_sync.py --root /path --publish --dry-run
```

---

## Generated, local, and never committed

`.venv/`, `uv.lock`, `*.egg-info/`, `/build/`, `/dist/`, the generated root launchers
(`update-archive.*`, `manage-archives.*`, `duplicate-github-org.*`, `suggest-sync.*`),
`Special/duplicate_org/runs/`, and `.agents/output/`. The archive registry is not in the
checkout at all: it lives in the per-user gitSpecOps folder.

Sync Suggester keeps its state **outside the repository** entirely — `GITSPECOPS_SYNC_HOME`,
else XDG on POSIX / `%APPDATA%` on Windows, under `gitspecops/sync-suggester/`.

---

## Tests

Every test is offline and synthetic — no network, no real repository, no personal name:

```bash
python3 tests/run_all.py
```

---

## Contributing and license

Working on this repo, human or agent? Start with
[`.agents/README.md`](.agents/README.md) — the primary project brief — and the living
[`.agents/WORKING-NOTES.md`](.agents/WORKING-NOTES.md).

Licensed under the Apache License 2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
