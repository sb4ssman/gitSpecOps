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

## Sync Suggester

Sync Suggester is a status and memory operation. On one machine it is a useful whole-folder Git
dashboard. Across machines it becomes much more valuable: each computer publishes a tiny report of
what it last knew, and another computer can warn about committed-but-unpushed work, an old dirty
clone, divergence, or a machine whose clean report is too stale to trust.

It synchronizes **facts and advice**, not unfinished source content. It does not commit, stash, pull,
push, patch, or copy working files.

The initial scaffold already supports bounded local observation:

```bash
python3 git-sync-suggester/sync_suggester.py check --root /path/to/repositories
```

Roots scan direct children by default. Add `--recursive` explicitly for a nested development tree.
To publish this machine's record into a folder managed by OneDrive, Dropbox, Syncthing, or another
folder-sync tool, provide a stable non-personal machine ID:

```bash
python3 git-sync-suggester/sync_suggester.py check \
  --root /path/to/repositories \
  --state-dir /path/to/gitspecops-state \
  --machine-id machine-a \
  --machine-label workstation-a
```

The synchronized manifest contains hashed canonical repository identities and status facts. It does
not contain repository display names, remote URLs, absolute paths, filenames, diffs, commit messages,
or source content. Readable names come from an unsynchronized local catalog/table.

`check` and the read-only folder `doctor` are runnable today. Persistent configuration, peer-report
aggregation, configurable freshness, and the reserved `watch`/`handoff` workflows are the next
vertical slice. The intended watcher will publish semantic changes plus heartbeats and make a
best-effort final observation—but no tool can guarantee that an external cloud client uploads a
last-second write before abrupt sleep or power loss.

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
