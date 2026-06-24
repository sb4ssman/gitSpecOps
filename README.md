# gitSpecOps

Small local special Git operations tools.

- GitHub Organization Duplicator
  - Copying whole GitHub organizations to disk or into another GitHub organization.
- Archive Updater
  - Keeping local folders full of cloned repositories refreshed in a controlled way.

The repo is intentionally plain. There is no package CLI, no hidden service, and no database. The tools are regular Python scripts launched through small generated `.bat` or `.sh` files.

## Quick Start

Install `uv`, `git`, and GitHub CLI (`gh`). Authenticate GitHub CLI if you plan to use the org duplicator:

```powershell
gh auth login
```

From the repo root, generate the local launchers:

```powershell
.\run_setup.bat
```

On Windows this writes:

- `gitArchiveUpdater\update-archive.bat`
- `gitArchiveUpdater\manage-archives.bat`
- `github-org-duplicator\duplicate-github-org.bat`

Setup detects the current operating system and writes only that system's launcher type. Running setup again simply overwrites those expected launchers.

## What Is Here

There are three entry-point Python tools:

- `gitArchiveUpdater\archive_manager.py`: the front door. Installs archive-local launchers, tracks managed archives, refreshes them all, and manages the optional scheduled refresh.
- `gitArchiveUpdater\archive_updater.py`: a standalone, dependency-free updater. Scans archive folders and fast-forward pulls eligible repos using only `git` (no `gh`, no provider).
- `github-org-duplicator\github_org_duplicator.py`: walks a user through copying repositories between GitHub orgs and local folders.

The manager and the archive-local launchers drive a small plan/apply engine made of single-purpose modules:

- `archive_sync.py`: the plan/apply engine (detect -> plan -> decide -> execute -> review) for update, clone, reconcile, and rename.
- `archive_diff.py`: pure decision logic (no git, no network), matching local repos to the remote set by stable id so renames survive. Run it directly to execute its self-test.
- `git_inspect.py`: read-only, host-agnostic local git facts.
- `remote_provider.py` / `provider_github.py`: the cross-git seam. Remote discovery (listing an org, following renames) is host-specific and lives behind a provider. GitHub via the `gh` CLI is the only provider today; any other host falls back to update-only.

Supporting files:

- `setup_gitspecops.py`: writes the launcher scripts.
- `run_setup.bat`, `run_setup.ps1`, `run_setup.sh`: convenient setup entry points.
- `_legacy_sources\`: older source snapshots kept only for reference.

### archive_updater.py vs archive_sync.py

Both fast-forward clean repos. The difference is remote discovery:

- `archive_updater.py` needs only `git`. It never lists an org, so it never clones, reconciles, or renames. The top-level `update-archive.bat` launcher uses it.
- `archive_sync.py` can additionally discover an org's full repo set through a provider, so it can clone missing repos and reconcile drift. The manager and the archive-local launchers it installs use it. When no provider matches the host, or discovery fails (e.g. `gh` is missing or unauthenticated), `archive_sync.py` degrades to the same update-only behavior as `archive_updater.py`.

## Archive Updater

The archive updater is the low-level repo refresh tool. Give it one or more archive roots. Each archive root should be a folder whose direct children are Git repositories.

Example:

```powershell
.\gitArchiveUpdater\update-archive.bat --root T:\Github\Archive-Public --default-output-dir
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
.\gitArchiveUpdater\manage-archives.bat
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
7. stores the archive in `gitArchiveUpdater\managed_archives.json`

The archive-local launcher calls `archive_sync.py` against the pinned archive root with the configured mode and `--yes` for unattended runs. It auto-detects the owner at run time, so it survives org and repo renames; the owner is never baked in. Scheduled runs only ever `--update` or `--sync` (never reconcile or rename), so they cannot silently rewrite origins or move folders. It writes that archive's reports into the archive itself:

```text
ARCHIVE_ROOT\update_archive.bat
ARCHIVE_ROOT\.gitSpecOps\archive-updates\
```

The manager registry stays local to this repo:

```text
gitArchiveUpdater\managed_archives.json
```

Manager logs live here:

```text
gitArchiveUpdater\runs\archive-manager.log
```

Refresh-all runs call `archive_sync.py` once per managed archive in its configured mode, then update the registry with the last run time, result, elapsed time, and latest report path. If a repo's host has no provider, or discovery fails (for example `gh` is missing or unauthenticated), that archive degrades to update-only and still fast-forwards every clean repo; the discovery failure is recorded as an issue in the run's report.

### Scheduling

On Windows, the manager can write `gitArchiveUpdater\refresh-managed-archives.bat` and register it with Task Scheduler. The default task name is:

```text
gitSpecOps Archive Refresh
```

Useful direct commands:

```powershell
uv run python gitArchiveUpdater\archive_manager.py --write-refresh-all-script
uv run python gitArchiveUpdater\archive_manager.py --install-monthly-task --task-day 1 --task-time 09:00
uv run python gitArchiveUpdater\archive_manager.py --task-status
uv run python gitArchiveUpdater\archive_manager.py --remove-task
```

Task creation and removal are explicit. The manager does not silently install background jobs.

## GitHub Organization Duplicator

Run it with:

```powershell
.\github-org-duplicator\duplicate-github-org.bat
```

The duplicator is interactive. It checks for `git`, `gh`, GitHub authentication, and Git credential setup before doing work.

Modes:

- **Remote to Local**: clone every repo in a GitHub org to a local folder.
- **Local to Remote**: scan a local folder for Git repos and push them into a GitHub org.
- **Remote to Remote**: copy repos from one GitHub org to another.

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
- `gitArchiveUpdater\managed_archives.json`
- `gitArchiveUpdater\runs\`
- `gitArchiveUpdater\refresh-managed-archives.bat`
- `github-org-duplicator\runs\`

The ignored state is useful on one machine but should not be shared as repo source.

## Safety Model

Archive updates are deliberately conservative: direct child folders only, approved remotes only, clean repos only, command timeouts, and fast-forward pulls only.

The GitHub org duplicator can create repositories and push refs, so it stays interactive and confirmation-driven. It uses GitHub CLI credentials instead of storing tokens itself.

When in doubt, scan first:

```powershell
uv run python gitArchiveUpdater\archive_manager.py --refresh-all --scan-only
```
