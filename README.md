# gitSpecOps

Small, cautious special operations for whole collections of Git repositories.

- **Archive Updater** wants an archive folder to stay present and current. It inventories repositories,
  fast-forward pulls clean clones, and can explicitly reconcile an archive with its source namespace.
- **GitHub Organization Duplicator** wants a complete collection moved safely. It downloads, uploads,
  or migrates repositories with previews, conflict checks, typed confirmation, and resumable run files.
- **Sync Suggester** thinks about your working repositories as a fleet—and the fun part is that it can
  do that across computers. It wants every clone to be safely synchronized, remembers the last facts
  each machine reported, and explains what needs attention before you move from one computer to another.

The repository is intentionally plain and stdlib-first. There is no package CLI, hidden service, or
database. The tools are regular Python scripts; optional convenience launchers are generated locally
by setup and are never committed.

> Working on this repo (human or agent)? Start with [`.agents/README.md`](.agents/README.md) — the primary project brief — and the living [`.agents/working-notes.md`](.agents/working-notes.md).

## Quick Start

Install Python 3.11+ and `git`. GitHub CLI (`gh`) is required for the organization duplicator and
GitHub-aware archive discovery; `uv` is optional but recommended for setup. Authentication remains
yours to manage:

```powershell
gh auth login
```

Run any tool directly—no setup or launcher is required:

```bash
python3 github-org-duplicator/github_org_duplicator.py
python3 git-archive-updater/archive_manager.py --help
python3 git-sync-suggester/sync_suggester.py --help
```

For convenience, `run_setup` also writes one launcher per tool into the repo root — only for your OS (`.sh` on Linux/macOS, `.ps1` + a `.bat` double-click shim on Windows):

- `update-archive`, `manage-archives`, `duplicate-github-org`, `suggest-sync`

Launchers are generated, not committed — edit `setup_gitspecops.py`, never a launcher. Every launcher prefers the repo's `.venv` interpreter and falls back to `uv run` when `.venv` is absent. After setup:

```bash
./duplicate-github-org.sh        # Linux/macOS
.\duplicate-github-org.bat       # Windows
./suggest-sync.sh --help         # Linux/macOS
.\suggest-sync.bat --help        # Windows
```

### Optional: build a local environment

Running the bootstrap once creates `.venv`, after which the launchers call it directly — faster cold start and no dependency on `uv` staying on `PATH`:

```powershell
.\run_setup.bat
```

`run_setup` builds `.venv` with `uv sync` (or the stdlib `venv` module when `uv` is absent) and
reports whether `git`, `gh`, and `uv` are present. The project is **not** installed into `.venv` —
the tools are stdlib-only scripts and `.venv` is just a clean interpreter for the launchers. It is
entirely optional; you can always run `python3 <tool>/<script>.py` directly.

## What Is Here

Three special operations currently have four entry-point Python scripts:

- `git-archive-updater\archive_manager.py`: the front door. Installs archive-local launchers, tracks managed archives, refreshes them all, and manages the optional scheduled refresh.
- `git-archive-updater\archive_updater.py`: a standalone, dependency-free updater. Scans archive folders and fast-forward pulls eligible repos using only `git` (no `gh`, no provider).
- `github-org-duplicator\github_org_duplicator.py`: walks a user through copying repositories between GitHub orgs and local folders.
- `git-sync-suggester\sync_suggester.py`: the read-only observer/advisor. Its initial `check` path
  inventories bounded roots, renders local advice, and can atomically publish a privacy-minimized
  machine record to a user-selected synchronized folder.

The manager and the archive-local launchers drive a small plan/apply engine made of single-purpose modules:

- `archive_sync.py`: the plan/apply engine (detect -> plan -> decide -> execute -> review) for update, clone, reconcile, and rename.
- `archive_diff.py`: pure decision logic (no git, no network), matching local repos to the remote set by stable id so renames survive. Run it directly to execute its self-test.
- `git_inspect.py`: read-only, host-agnostic local git facts.
- `remote_provider.py` / `provider_github.py`: the cross-git seam. Remote discovery (listing an org, following renames) is host-specific and lives behind a provider. GitHub via the `gh` CLI is the only provider today; any other host falls back to update-only.

Shared primitives used across the tools live in `shared\` (see `.agents\README.md`):
`remote_identity.py`, `git_facts.py`, `repo_discovery.py` (the machine/root scanner), `providers.py`,
and `gh_cli.py`. Their standalone interfaces are read-only information operations.

Supporting files:

- `setup_gitspecops.py`: optional bootstrap — writes the convenience launchers, builds `.venv` (via `uv sync`, or stdlib `venv` as a fallback), and reports prerequisites. It never touches authentication.
- `run_setup.bat`, `run_setup.ps1`, `run_setup.sh`: convenient entry points for the optional bootstrap.
- `tests\`: synthetic offline tests; fixtures never use personal repository or organization names.
- `_legacy_sources\`: older source snapshots kept only for reference.

### archive_updater.py vs archive_sync.py

Both fast-forward clean repos. The difference is remote discovery:

- `archive_updater.py` needs only `git`. It never lists an org, so it never clones, reconciles, or renames. The top-level `update-archive.bat` launcher uses it.
- `archive_sync.py` can additionally discover an org's full repo set through a provider, so it can clone missing repos and reconcile drift. The manager and the archive-local launchers it installs use it. When no provider matches the host, or discovery fails (e.g. `gh` is missing or unauthenticated), `archive_sync.py` degrades to the same update-only behavior as `archive_updater.py`.

## Archive Updater

The archive updater is the low-level repo refresh tool. Give it one or more archive roots. Each archive root should be a folder whose direct children are Git repositories.

Example:

```powershell
.\update-archive.bat --root T:\Git\Archive-Public --default-output-dir
```

Under the hood, `archive_updater.py` inspects each direct child folder and only marks it updateable when all of these are true:

- the child is a Git work tree rooted at that folder
- it has an `origin` remote
- the remote starts with an approved prefix, defaulting to `https://github.com/`
- the work tree is clean
- the index is clean

Repos that fail any check are skipped and explained in the console output and JSON report.

When updating, it runs:

```powershell
git fetch --dry-run origin
git pull --ff-only
```

It does not merge, rebase, reset, force-push, install dependencies, run project code, or recurse into nested folders. Git commands time out after 45 seconds by default; use `--git-timeout` to change that.

Reports are written only when an output directory is provided. Archive-local launchers installed by the manager write reports here:

```text
ARCHIVE_ROOT\.gitSpecOps\archive-updates\archive-update-YYYYMMDD-HHMMSS.json
```

Reports include the root, eligible repos, skipped repos, update results, elapsed time, and Git timeout setting.

## Archive Manager

The archive manager is the friendly front door for archive folders.

Run it with:

```powershell
.\manage-archives.bat
```

The dashboard shows known archive folders, install time, repo count at install, launcher status, last refresh result, elapsed time, and latest report.

Main actions:

- install or refresh an archive-local `update_archive.bat`
- scan all managed archives without pulling
- update all managed archives
- show detailed status
- write a refresh-all script
- create, inspect, or remove the monthly Windows scheduled refresh

When you install an archive, the manager:

1. accepts an archive folder path
2. verifies the folder exists and is not itself a Git repo
3. scans direct child folders, and (if a provider matches the host) the authoritative remote set
4. presents a plan and applies only the classes you approve (pull, clone, reconcile, rename)
5. asks which mode future automated runs should use: `update` (safe, default) or `sync` (auto-clone new repos)
6. writes `update_archive.bat` into that archive folder
7. stores the archive in `git-archive-updater\managed_archives.json`

The archive-local launcher calls `archive_sync.py` against the pinned archive root with the configured mode and `--yes` for unattended runs. It auto-detects the owner at run time, so it survives org and repo renames; the owner is never baked in. Scheduled runs only ever `--update` or `--sync` (never reconcile or rename), so they cannot silently rewrite origins or move folders. It writes that archive's reports into the archive itself:

```text
ARCHIVE_ROOT\update_archive.bat
ARCHIVE_ROOT\.gitSpecOps\archive-updates\
```

The manager registry stays local to this repo:

```text
git-archive-updater\managed_archives.json
```

Manager logs live here:

```text
git-archive-updater\runs\archive-manager.log
```

Refresh-all runs call `archive_sync.py` once per managed archive in its configured mode, then update the registry with the last run time, result, elapsed time, and latest report path. If a repo's host has no provider, or discovery fails (for example `gh` is missing or unauthenticated), that archive degrades to update-only and still fast-forwards every clean repo; the discovery failure is recorded as an issue in the run's report.

### Scheduling

On Windows, the manager can write `git-archive-updater\refresh-managed-archives.bat` and register it with Task Scheduler. The default task name is:

```text
gitSpecOps Archive Refresh
```

Useful direct commands:

```powershell
uv run python git-archive-updater\archive_manager.py --write-refresh-all-script
uv run python git-archive-updater\archive_manager.py --install-monthly-task --task-day 1 --task-time 09:00
uv run python git-archive-updater\archive_manager.py --task-status
uv run python git-archive-updater\archive_manager.py --remove-task
```

Task creation and removal are explicit. The manager does not silently install background jobs.

### Publishing (the push direction)

Everything else in the archive tools pulls. `--publish` is the one command that writes to a
remote, and it only ever does the provably safe thing: a push **without** `--force`, which git
refuses unless it is a fast-forward.

```bash
python3 git-archive-updater/archive_sync.py --root /path/to/archive --publish --dry-run
python3 git-archive-updater/archive_sync.py --root /path/to/archive --publish
```

Only repositories that are **ahead-only and clean** are eligible. Diverged goes to a human,
behind-only needs a pull first, and a detached HEAD or missing upstream is skipped as
direction-unknown. A repository that is ahead but has uncommitted work — including untracked
files — is reported and held back; `--include-dirty` pushes its committed work anyway. **Nothing
is ever auto-committed.**

Each repository is fetched and re-checked immediately before its push, so a remote that moved
since planning is reported as "needs a human" rather than forced. `--publish` refuses to run
alongside `--update`/`--sync`, and the generated launchers and scheduled task never pass it, so a
background job can never push on your behalf.

## Sync Suggester

Sync Suggester is a status and memory operation. On one machine it is a useful whole-folder Git
dashboard. Across machines it becomes much more valuable: each computer publishes a tiny report of
what it last knew, and another computer can warn about committed-but-unpushed work, an old dirty
clone, divergence, or a machine whose clean report is too stale to trust.

It synchronizes **facts and advice**, not unfinished source content. It does not commit, stash, pull,
push, patch, or copy working files.

Set the machine up once. `init` records who this machine is, which roots it may look at, and the
folder your own sync client (OneDrive, Dropbox, Syncthing, a mounted share) replicates between
machines:

```bash
python3 git-sync-suggester/sync_suggester.py init \
  --machine-id machine-a --machine-label workstation-a \
  --root /path/to/repositories \
  --state-dir /path/to/gitspecops-state
```

That prints a **fleet secret**. Every other machine joins the same fleet with it:

```bash
python3 git-sync-suggester/sync_suggester.py init \
  --machine-id machine-b --machine-label laptop \
  --root /path/to/repositories \
  --state-dir /path/to/gitspecops-state \
  --fleet-secret <the 64-character value machine-a printed>
```

Carry that secret yourself — a password manager, or typed by hand. **Do not put it in the state
directory.** It is what stops anyone who obtains that folder from working out which repositories
you have, and a secret stored beside the data it protects protects nothing. A machine that joins
with the wrong secret is detected and named on the dashboard rather than silently appearing to
share nothing.

Roots scan direct children by default; use `--recursive-root` for a nested development tree, and
`--from-archives` to reuse the roots Archive Updater already manages. Configuration lives in
`~/.config/gitspecops/sync-suggester/` (`%APPDATA%` on Windows, or `GITSPECOPS_SYNC_HOME`).

After that, `check` observes, publishes this machine's manifest, and prints the fleet view:

```bash
python3 git-sync-suggester/sync_suggester.py check
```

```text
Repository    DESKTOP  LAPTOP  OLDPI    Advice
------------  -------  ------  -------  ------------------------------------------------------
notebooks     ✎3       ✎5      ✎5 (3d)  ⚠ COLLISION: uncommitted work on DESKTOP, LAPTOP, OLDPI
website       ⚠rebase  ✓       ? (3d)   finish rebase on DESKTOP
data-loader   ✓        ✓       ✎7 (3d)  last known uncommitted work on OLDPI (3d ago)
api           ✓        ✓       ↑1 (3d)  PUSH OLDPI ↑1 (last seen 3d ago)
experiments   ↕2/4     ✓       ? (3d)   ↕ diverged on DESKTOP — human decision
toolbox       ↑3       ✓       ? (3d)   PUSH DESKTOP ↑3
docs-site     ↓2       ✓       ? (3d)   PULL DESKTOP ↓2

11 repositor(ies) need no action (use --all to list them) — clean on every current machine, but
OLDPI has not reported, so their state there is unknown, not proven clean
Machines: DESKTOP current (4m ago), LAPTOP current (just now), OLDPI stale (3d ago)
Legend: ✓ clean  ✎ uncommitted  ↑ ahead  ↓ behind  ↕ diverged  ⚑ stash  ⚠ attention  ? unknown  - not present
```

By default every ↑/↓ is *cached* knowledge, read from remote-tracking refs that may be days old,
and the dashboard says so. `check --fetch` refreshes them first:

```bash
python3 git-sync-suggester/sync_suggester.py check --fetch
```

That is the only network activity the tool performs. It updates remote-tracking refs and nothing
else — never a branch, never your working tree — and it records *when* each repository was fetched,
because a manifest written a second ago says nothing about how old its remote knowledge is. Those
two kinds of freshness are tracked and displayed separately. A repository whose fetch fails keeps
its cached counts and says so, rather than the run failing. 20 repositories take about four seconds
over four workers (`--fetch-workers`, `--fetch-timeout`).

It is an exceptions view: rows nothing can be done about are folded into that summary line, which
still names any machine whose silence is the reason a row is quiet. **A report that is not current
never produces an "all clear."** A stale clean report becomes *unknown*; a stale *dirty* or *ahead*
report keeps its warning, because the last thing anyone knew was that unresolved work existed there.
Reports are current for 24 hours, stale for 7 days, and expired after that (`--stale-hours` /
`--expired-days` at `init`).

### Converging a new machine

`check` tells you the state of repositories you have. `converge` answers the other half — which
repositories your *other* machines have that this one does not:

```bash
python3 git-sync-suggester/sync_suggester.py converge
```

```text
17 repositor(ies) reported by peers are not on this machine.

Repository                           Present on
-----------------------------------  ----------
sb4ssman/Chess_App                   ALPHA, BRAVO
sb4ssman/Laboratory                  ALPHA, BRAVO
...

To clone them, hand each namespace to the archive engine, which already discovers and
clones through the same provider seam:
    python3 git-archive-updater/archive_sync.py --root /memory-lambda/Github/sb4ssman \
      --github-owner sb4ssman --sync
```

There is a neat problem here worth knowing about. Peers publish only *hashed* identities, so a
machine cannot clone what it cannot name. But the hash is deterministic: ask GitHub what exists in
the namespaces you already work in, hash each candidate under the same fleet secret, and match.
A repository you can see gets named without its name ever crossing the transport, and a repository
you genuinely cannot see stays an opaque identifier — which is the correct answer, not a failure.
Names the local catalog already knows cost no network call at all; `--namespace OWNER` searches
somewhere else, and `--no-resolve` skips the provider entirely.

`converge` never clones. Cloning is a mutation and it already has an owner — `archive_sync.py` —
so this command reports the gap and hands over the exact command.

### The other commands

```bash
python3 git-sync-suggester/sync_suggester.py dashboard            # read peers, observe nothing
python3 git-sync-suggester/sync_suggester.py watch --interval 60  # keep publishing while you work
python3 git-sync-suggester/sync_suggester.py alias <id> <name>    # name a repo only a peer has
python3 git-sync-suggester/sync_suggester.py doctor               # inspect local state, change nothing
```

`watch` republishes only when the facts actually change, plus a periodic heartbeat proving the
machine is alive, and makes a best-effort final observation when you stop it (Ctrl-C or SIGTERM,
answered in well under a second). No tool can guarantee an external cloud client uploads that last
write before abrupt sleep or power loss, which is why an explicit `check` before you walk away is
still worth running.

The synchronized manifest (schema v2) identifies repositories by `HMAC-SHA256(fleet secret,
host/owner/name)`. It contains no display names, remote URLs, absolute paths, filenames, diffs,
commit messages, commit SHAs, or source content; readable names come from an unsynchronized local
catalog. Branch names *are* still published in the clear — a deliberate trade-off, since knowing
which branch each machine sits on is worth showing. See
[`.agents/knowledge/manifest-privacy.md`](.agents/knowledge/manifest-privacy.md) for exactly what
that boundary does and does not protect.

`handoff` remains reserved: moving unfinished work between machines is a mutation flow and gets its
own design pass rather than hiding inside the watcher.

## GitHub Organization Duplicator

Run it with:

```powershell
.\duplicate-github-org.bat
```

Run with no flags it is interactive. It checks for `git`, `gh`, GitHub authentication, and reminds
you that private Git credentials remain yours to configure before doing work.

It also takes flags for an unattended run — useful inside editors/CI where a terminal helper may
type virtualenv-activation lines into an open prompt:

```bash
# Back up every namespace, working clones, no further questions:
python3 github-org-duplicator/github_org_duplicator.py --batch --namespaces all --dest /backups/github --yes

# Batch, skip one org, mirror clones:
python3 github-org-duplicator/github_org_duplicator.py --batch --namespaces 'all,!some-org' --dest /backups/github --format mirror --yes

# One repo:
python3 github-org-duplicator/github_org_duplicator.py --single owner/name --dest /backups/github --yes
```

`--yes` requires `--namespaces` and `--dest`; it takes documented defaults for anything else
(private: yes, archived: no, forks: no, format: working, parallel: 3) and skips the typed
confirmation. For any prompt not covered by a flag — including in the other modes — `--answers FILE`
feeds answers one per line (a blank line accepts that prompt's default). See `--help`.

Modes:

- **Remote to Local**: clone every repo in a GitHub org to a local folder.
- **Local to Remote**: recursively scan a local folder for Git repos and push them into a GitHub
  org. Direct-child-only scanning remains available. Worktrees, linked worktrees, and bare/mirror
  repos are recognized; duplicate local basenames stop the run before remote writes.
- **Remote to Remote**: copy repos from one GitHub org to another.
- **All My Orgs → Local (batch)**: pick namespaces — your own account plus your orgs — with the
  print-style grammar (`all`, `1-5, 7`, names, `except`/`!`), optionally pick individual repos
  per namespace, review one plan table, type YES once. Per-namespace resume; batch manifest in `runs/`.
- **One Repo → Local**: any single repo by `owner/name` or full URL (public repos included),
  downloaded into the same `<parent>/<owner>/<repo>` layout. The spec is resolved and the
  matched repo shown before anything else is asked; a bare name with no owner is rejected with
  an explanation (GitHub would otherwise read it as one of *your* repos).

All download modes share the same selection grammar, the same
`<parent>/<namespace>/<repo>` arrival layout, the same limitations block before
confirmation, and resumable per-namespace run files.

The tool lists what it finds, warns about Git LFS, checks for existing repositories, and asks for a typed `YES` before it starts moving data.

Run files are kept here:

```text
github-org-duplicator\runs\
```

Those files include completed-repo trackers, success logs, error logs, and operation session files. If a run is interrupted, rerun the same operation and completed repos are skipped.

The duplicator is meant for whole-org copies into clean destinations. If it finds name conflicts that are not verified duplicates, it stops instead of trying to reconcile unrelated repositories.

## Runtime Files

These are generated locally and ignored by Git:

- `.venv\`
- `*.egg-info\`
- `uv.lock`
- `git-archive-updater\managed_archives.json`
- `git-archive-updater\runs\`
- `git-archive-updater\refresh-managed-archives.bat` / `.ps1` / `.sh`
- `github-org-duplicator\runs\`
- generated root launchers (`update-archive.*`, `manage-archives.*`, `duplicate-github-org.*`,
  `suggest-sync.*` — your OS's only)

The per-tool launchers are generated by `run_setup` and ignored; the per-archive `update_archive`
launchers and `refresh-managed-archives` are generated by the manager and ignored. Source scripts,
tests, documentation, and the `run_setup.*` bootstrap files are committed; generated launchers are not.

The ignored state is useful on one machine but should not be shared as repo source.

## Safety Model

Archive updates are deliberately conservative: direct child folders only, approved remotes only, clean repos only, command timeouts, and fast-forward pulls only.

The GitHub org duplicator can create repositories and push refs, so it stays interactive and confirmation-driven. It uses GitHub CLI credentials instead of storing tokens itself.

Sync Suggester only reads repository state. Its sole write in the current scaffold is an explicitly
requested, privacy-minimized machine manifest in the selected state folder; source repositories are
never modified.

When in doubt, scan first:

```powershell
uv run python git-archive-updater\archive_manager.py --refresh-all --scan-only
```
