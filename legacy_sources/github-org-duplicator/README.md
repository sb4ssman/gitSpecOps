# GitHub Organization Duplicator

A Python script to duplicate all repositories from one GitHub organization to another, preserving all branches, tags, commit history, and repository metadata.

## Purpose

This tool is designed for **one-time complete organization migrations** where you need to copy an entire GitHub organization's repositories into a new, empty organization. It is **not** designed to handle conflicts or merge with existing repositories.

## Features

- ✅ **Three operation modes**: Remote→Local, Local→Remote, Remote→Remote
- ✅ **Automated dependency checks**: Detects and offers to install git and GitHub CLI
- ✅ **Package manager detection**: Supports winget, Chocolatey, Homebrew, apt, yum, dnf
- ✅ Duplicates all repositories with complete git history
- ✅ Preserves all branches and tags
- ✅ Maintains repository privacy settings (public/private)
- ✅ Preserves repository descriptions
- ✅ Detects Git LFS usage and warns about special handling requirements
- ✅ Resumable - if interrupted, rerun to continue from where it stopped
- ✅ Retry logic for network issues (3 attempts per operation)
- ✅ Detailed logging and progress tracking
- ✅ Shows timing information for each repository

## Prerequisites

### Required Software

1. **Python 3.7+** (required to run the script)
   - Check: `python --version` or `python3 --version`

2. **GitHub CLI (`gh`)** - The script will check and offer to install automatically
   - Supported package managers: winget, Chocolatey (Windows), Homebrew (macOS), apt/yum/dnf (Linux)
   - Manual install: https://cli.github.com/

3. **Git** - The script will check and offer to install automatically
   - Supported package managers: winget, Chocolatey (Windows), Homebrew (macOS), apt/yum/dnf (Linux)
   - Manual install: https://git-scm.com/downloads

### Automated Checks

The script automatically checks for required tools and offers to install them if missing:
- ✅ Detects available package managers (winget, Chocolatey, Homebrew, apt, yum, dnf)
- ✅ Checks for git and GitHub CLI installation
- ✅ Offers automated installation via detected package manager
- ✅ Verifies GitHub authentication
- ✅ Configures git to use GitHub credentials

### Authentication Setup

**Before first use**, authenticate with GitHub:
```bash
# Authenticate with GitHub (includes 2FA)
gh auth login

# The script will automatically run: gh auth setup-git
```

### Permissions Required

- **Source organization**: Admin/Owner access (to read all repositories)
- **Destination organization**: Admin/Owner access (to create repositories) - *only for Remote→Remote mode*

## Pre-flight Checklist

The script handles most checks automatically, but verify these before running:

1. **GitHub Authentication** - Run `gh auth login` if you haven't already
2. **Disk Space** - Ensure you have at least 3-5 GB free in your target/temp directory
3. **Organization Access** - Verify you have admin access to the organizations you'll be working with

## Usage

1. **Run the script:**
   
   **Windows:**
   ```batch
   duplicate.bat
   ```
   
   **Or directly:**
   ```bash
   python github_org_duplicator.py
   ```

2. **Select operation mode:**
   - **1. Remote → Local**: Download all repos from a GitHub org to your disk
   - **2. Local → Remote**: Upload local git repos to a GitHub org
   - **3. Remote → Remote**: Migrate repos between two GitHub orgs (original conduit mode)

3. **Follow the prompts:**
   - The script will check for required tools and offer installation if needed
   - Enter organization names or directory paths as prompted
   - Review repository information tables
   - Specify target/temp directory (needs ~3-5 GB free space)
   - Type "YES" to confirm and start

4. **Monitor progress:**
   - The script processes repositories one at a time
   - Progress, timing, and status are displayed for each repository
   - Progress is logged to mode-specific log files

## Output Files

The script creates mode-specific tracking files:

**Remote → Local mode:**
- **`downloaded_repos.txt`** - List of successfully downloaded repositories
- **`download_log.txt`** - Timestamped log of successful downloads
- **`download_errors.txt`** - Timestamped log of failed downloads

**Local → Remote mode:**
- **`uploaded_repos.txt`** - List of successfully uploaded repositories
- **`upload_log.txt`** - Timestamped log of successful uploads
- **`upload_errors.txt`** - Timestamped log of failed uploads

**Remote → Remote mode:**
- **`completed_repos.txt`** - List of successfully migrated repositories
- **`migration_log.txt`** - Timestamped log of successful migrations
- **`migration_errors.txt`** - Timestamped log of failed migrations

## Resuming After Interruption

If the script is interrupted (Ctrl+C, network failure, etc.):

1. Simply **run the script again** with the same source/destination organizations
2. It will automatically skip repositories listed in `completed_repos.txt`
3. Failed repositories are **not** marked as complete, so they will be retried

## What Gets Migrated

### ✅ Included
- All git commit history
- All branches
- All tags
- All files and directories
- Repository name
- Repository description
- Privacy setting (public/private)
- Repository creation date (relative order preserved)

### ❌ Not Included
- GitHub Issues
- GitHub Pull Requests (PRs are not migrated, though PR refs may be copied)
- GitHub Actions secrets and workflows
- Repository settings (branch protection, webhooks, etc.)
- Collaborators and teams
- Stars, forks, and watchers counts
- GitHub Pages settings (pages content IS migrated if in a `gh-pages` branch)

## Git LFS Repositories

If repositories use Git LFS (Large File Storage):

1. The script will detect and warn you during the information gathering phase
2. LFS repositories may require manual handling after migration
3. Ensure you have Git LFS installed: `git lfs install`
4. You may need to manually configure LFS in the destination organization

## Limitations

- **Conflict handling**: Script will abort if destination org has any repositories with matching names
- **Repository size**: GitHub has a 2GB file size limit; larger files may cause push failures
- **API rate limits**: Unlikely but possible with very large organizations (>1000 repos)
- **Network reliability**: Large repositories may fail if network is unstable (retry logic helps)

## Troubleshooting

### "gh is not recognized"
- Install GitHub CLI: https://cli.github.com/
- Restart your terminal after installation

### "Authentication failed"
- Run: `gh auth login`
- Run: `gh auth setup-git`

### "Cannot access organization"
- Verify you have admin/owner access to both organizations
- Check organization name spelling (case-sensitive)

### Clone or push fails
- Check your internet connection
- Verify the repository isn't corrupted in the source org
- Check `migration_errors.txt` for specific error details
- Retry by running the script again (it will skip completed repos)

### Disk space errors
- Ensure temp directory has at least 3-5 GB free
- Largest repos may temporarily use significant space

## Example Run
```
============================================================
GitHub Organization Repository Migration
============================================================

✓ gh CLI installed
✓ gh authenticated
✓ git configured to use gh credentials

Source organization name: OldOrg
Destination organization name: NewOrg

Verifying organization access...
✓ Admin rights confirmed for OldOrg
✓ Admin rights confirmed for NewOrg

Detecting repos in both orgs...
✓ 51 repos found in OldOrg
✓ 0 repos found in NewOrg

✓ No conflicts!

[Detailed repository table displayed]

Press ENTER to continue to migration setup...
Temporary directory path: /tmp/migration

Ready to copy 51 repos from OldOrg to NewOrg
Type "YES" to continue: YES

============================================================
Starting migration...
============================================================

[1/51] Processing: first-repo
  → Cloning from OldOrg...
  → Creating in NewOrg...
  → Pushing to NewOrg...
  → Cleaning up...
✓ first-repo complete (took 12.3s)

[2/51] Processing: second-repo
...
```

## Technical Details

### Migration Process

For each repository, the script performs these steps:

1. **Clone**: `git clone --mirror` from source organization
2. **Create**: `gh repo create` in destination organization
3. **Push**: `git push --mirror` to destination repository
4. **Cleanup**: Remove temporary local clone
5. **Log**: Record success in `completed_repos.txt`

### Retry Logic

- Clone and push operations retry up to 3 times on failure
- 5-second delay between retry attempts
- Helps handle temporary network issues or rate limiting

### Sorting

Repositories are processed in order of creation date (oldest first) to preserve the relative chronological order in the destination organization.

## License

MIT License - Feel free to use and modify for your needs.

## Support

This is a one-time migration tool. For issues:
1. Check the `migration_errors.txt` file
2. Review GitHub CLI documentation: https://cli.github.com/manual/
3. Verify your GitHub organization permissions

## Notes

- This tool uses `git clone --mirror` and `git push --mirror` to ensure complete repository duplication
- Repositories are processed sequentially (one at a time) to avoid rate limiting
- The script is idempotent - safe to run multiple times
- No repositories are deleted from the source organization
- Temporary clones are automatically cleaned up after each repository
