# gitSpecOps

Cautious tools for multi-repository Git and GitHub operations.

This repo collects tools that started life as separate personal scripts and now belong under one sharper umbrella:

- **Archive Updater**: scans archive folders containing sibling Git repos and fast-forward-pulls only clean, approved remotes.
- **Archive Manager**: installs per-archive launchers that keep using the centralized updater from this checkout or package install.
- **GitHub Org Duplicator**: downloads, uploads, or mirrors repositories across GitHub organizations with `git` and `gh`.

The Python package has no required third-party Python dependencies. The tools shell out to external developer tools:

- `git` is required for archive updates and repository copy operations.
- `gh` is required for GitHub organization operations.

## Install For Development

```powershell
python -m pip install -e .
```

Or with `uv`:

```powershell
uv pip install -e .
```

## Commands

```powershell
git-spec-ops --help
git-spec-ops archive update --root T:\Github\Archive --scan-only
git-spec-ops archive manage --install T:\Github\Archive
git-spec-ops archive manage --status
git-spec-ops github duplicate-org
```

Direct entry points are also installed:

```powershell
archive-updater --root T:\Github\Archive --scan-only
archive-manager --install T:\Github\Archive
github-org-duplicator
```

## Safety Posture

These tools are intentionally conservative, but they still operate on Git repositories at scale. Prefer scan/dry-run modes first, read the summaries, and keep the generated JSON/log reports around when doing real maintenance.

Archive updates never merge, rebase, reset, force-push, install dependencies, or run project code. The updater only pulls clean work trees whose `origin` starts with an approved prefix.

GitHub organization duplication can create repositories and push mirrored refs. It requires explicit prompts and GitHub CLI authentication.

## Migrated History

`github-org-duplicator` was imported with `git subtree`, so its original commits are preserved in this repository's history. `ArchiveUpdater` was untracked in its source repo at migration time, so it enters gitSpecOps as an initial snapshot.

## More Docs

- [GitHub Org Duplicator](docs/github-org-duplicator.md)
