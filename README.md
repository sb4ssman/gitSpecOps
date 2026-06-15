# gitSpecOps

Small local tools for maintaining Git archive folders and duplicating GitHub organizations.

Runtime requirements:

- `uv`
- `git`
- `gh` for the GitHub org duplicator

## Setup

Run setup from the repo root:

```powershell
.\run_setup.bat
```

Equivalent direct command:

```powershell
uv run python setup_gitspecops.py
```

Setup detects the current OS and writes one launcher type. On Windows it writes:

- `gitArchiveUpdater\update-archive.bat`
- `gitArchiveUpdater\manage-archives.bat`
- `github-org-duplicator\duplicate-github-org.bat`

Setup only overwrites those expected launchers.

## Layout

Archive tools:

- `gitArchiveUpdater\archive_updater.py`
- `gitArchiveUpdater\archive_manager.py`
- `gitArchiveUpdater\update-archive.bat`
- `gitArchiveUpdater\manage-archives.bat`

GitHub org duplicator:

- `github-org-duplicator\github_org_duplicator.py`
- `github-org-duplicator\duplicate-github-org.bat`

Legacy source snapshots:

- `_legacy_sources\`

## Archive Updater

`archive_updater.py` scans one or more archive roots. Each archive root should contain sibling Git repo folders.

For each direct child folder, it checks:

- the child is a Git work tree rooted at that folder
- an `origin` remote exists
- the `origin` starts with an approved prefix, defaulting to `https://github.com/`
- the working tree and index are clean

In update mode, eligible repos run:

```powershell
git fetch --dry-run origin
git pull --ff-only
```

It never merges, rebases, resets, force-pushes, installs dependencies, or runs project code.

Git subprocess calls time out after 45 seconds by default. Override with:

```powershell
uv run python gitArchiveUpdater\archive_updater.py --root T:\Github\Archive --git-timeout 90
```

Reports:

- Console inventory and summary are always printed.
- JSON reports are written when `--output-dir` or `--default-output-dir` is provided.
- Reports include elapsed timing and the Git timeout setting.
- Archive-local launchers installed by the manager write reports to:

```text
ARCHIVE_ROOT\.gitSpecOps\archive-updates\archive-update-YYYYMMDD-HHMMSS.json
```

## Archive Manager

Run the dashboard:

```powershell
.\gitArchiveUpdater\manage-archives.bat
```

Direct command:

```powershell
uv run python gitArchiveUpdater\archive_manager.py
```

The dashboard shows managed archive roots, install time, repo count, launcher status, last run, last result, elapsed time, and latest report time.

Actions:

- Install or refresh an archive launcher.
- Scan all managed archives.
- Update all managed archives.
- Show detailed status.
- Write a refresh-all script.
- Create a monthly Windows scheduled refresh.
- Show scheduled refresh status.
- Remove scheduled refresh.

Install directly:

```powershell
uv run python gitArchiveUpdater\archive_manager.py --install T:\Github\Archive
```

Installing an archive:

- validates the folder is not itself a Git repo
- scans direct children with progress output
- writes `update_archive.bat` into that archive folder on Windows
- records the archive in `gitArchiveUpdater\managed_archives.json`

The archive-local `update_archive.bat` calls:

```powershell
uv run python gitArchiveUpdater\archive_updater.py --root ARCHIVE_ROOT --output-dir ARCHIVE_ROOT\.gitSpecOps\archive-updates
```

Refresh all managed archives:

```powershell
uv run python gitArchiveUpdater\archive_manager.py --refresh-all
```

Scan without pulling:

```powershell
uv run python gitArchiveUpdater\archive_manager.py --refresh-all --scan-only
```

Scheduling:

```powershell
uv run python gitArchiveUpdater\archive_manager.py --write-refresh-all-script
uv run python gitArchiveUpdater\archive_manager.py --install-monthly-task --task-day 1 --task-time 09:00
uv run python gitArchiveUpdater\archive_manager.py --task-status
uv run python gitArchiveUpdater\archive_manager.py --remove-task
```

The default task name is `gitSpecOps Archive Refresh`.

Current Windows scheduled task:

- Name: `gitSpecOps Archive Refresh`
- Schedule: monthly on day `1` at `09:00`
- Next verified run: `2026-07-01 09:00`
- Action: `gitArchiveUpdater\refresh-managed-archives.bat`

Inspect or remove it with:

```powershell
uv run python gitArchiveUpdater\archive_manager.py --task-status
uv run python gitArchiveUpdater\archive_manager.py --remove-task
```

Manager runtime files:

- Registry: `gitArchiveUpdater\managed_archives.json`
- Manager log: `gitArchiveUpdater\runs\archive-manager.log`
- Generated refresh-all script: `gitArchiveUpdater\refresh-managed-archives.bat`

## GitHub Org Duplicator

Run:

```powershell
.\github-org-duplicator\duplicate-github-org.bat
```

Direct command:

```powershell
uv run python github-org-duplicator\github_org_duplicator.py
```

Modes:

- **Remote to Local**: download all repos from a GitHub org to disk.
- **Local to Remote**: upload local Git repos into a GitHub org.
- **Remote to Remote**: mirror repos from one GitHub org to another.

The tool checks for `git`, `gh`, GitHub authentication, and git credential setup before doing work. It ignores accidental VS Code virtualenv activation commands pasted into prompts and asks again.

Run/resume files live under:

```text
github-org-duplicator\runs
```

Mode-specific files:

- Download: `downloaded_repos.txt`, `download_log.txt`, `download_errors.txt`, `download_session.txt`
- Upload: `uploaded_repos.txt`, `upload_log.txt`, `upload_errors.txt`, `upload_session.txt`
- Migrate: `completed_repos.txt`, `migration_log.txt`, `migration_errors.txt`, `migration_session.txt`

If a run is interrupted, rerun the same operation. Completed repos listed in the matching resume file are skipped.

## Local Artifacts

Ignored runtime/build artifacts include:

- `.venv\`
- `*.egg-info\`
- `uv.lock`
- `gitArchiveUpdater\managed_archives.json`
- `gitArchiveUpdater\runs\`
- `github-org-duplicator\runs\`

## Safety

Prefer scan-only modes first.

Archive updates are narrow by design: direct child folders only, approved remotes only, clean working trees only, Git command timeouts, and fast-forward pulls only.

GitHub organization duplication can create repositories and push mirrored refs. It requires explicit prompts and GitHub CLI authentication.
