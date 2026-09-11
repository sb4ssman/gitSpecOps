# gitSpecOps

**git Special Operations** — careful, boring, stdlib-only tools for when you have far too many
Git repositories and doing it by hand has stopped being reasonable.

Each operation is the kind of script you would eventually write yourself, with the dangerous
parts already thought through: it shows you a plan before it acts, it refuses anything ambiguous,
and it never touches your credentials.

---

## The special operations

### 1. GitHub Organization Duplicator

*Copy an entire namespace — down, up, or across — without clicking through a hundred
repositories.*

```bash
python3 github-org-duplicator/github_org_duplicator.py
```

Downloads every repo in an org, uploads a folder of local repos into one, or migrates org → org.
Previews what it will do, checks for name collisions before any remote call, asks for typed
confirmation, and writes resumable run files so an interrupted 300-repo migration continues
instead of restarting. Handles private/archived/fork filters, mirror or working clones, and
parallel workers.

### 2. Archive Updater

*Point it at a folder full of clones and keep every one of them current, safely.*

```bash
python3 git-archive-updater/archive_updater.py --root /path/to/archive
```

**Fast-forward pulls only.** It never merges, rebases, resets, stashes, or deletes; a repository
that is dirty, diverged, or on an unapproved remote is reported and skipped, not "fixed". The
richer engine (`archive_sync.py`) additionally discovers an org's full repo set and can clone
what is missing, repair stale origins after a rename, and rename folders to match upstream —
each as a separate, explicitly approved class of change.

### 3. Sync Suggester

*Know what every one of your machines left unfinished — which clone on which computer has
uncommitted work, unpushed commits, or a report too stale to trust.*

```bash
python3 git-sync-suggester/sync_suggester.py check
```

It reads Git state and tells you what needs attention. **It never pulls, pushes, commits,
stashes, or copies a working file.** Across machines it becomes the thing you actually want at
2am: "you left 17 uncommitted files on the laptop."

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
python3 git-archive-updater/archive_manager.py --help
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

---

## Archive updating in more detail

### `archive_updater.py` vs `archive_sync.py`

Both fast-forward clean repositories. The difference is remote discovery:

- **`archive_updater.py`** — `git` only, no network beyond the pull. It updates what is already
  on disk. Works with any Git host.
- **`archive_sync.py`** — asks a provider (GitHub via `gh`) what *should* be there, so it can
  clone missing repositories, spot renames, and flag orphans.

If no provider matches the host, or discovery fails, `archive_sync.py` **degrades to update-only**
— it pulls every clean repo and never invents a clone, an orphan, or a rename from a failed
listing. That fallback is enforced by a flag (`remote_authoritative`) and pinned by tests.

Identity is by **stable provider id**, never by folder name or URL. GitHub node ids survive both
repository and organization renames, so a deliberately renamed local folder is preserved while
genuine upstream drift is surfaced for you to confirm.

### `archive_manager.py` — the front door

Registers archives, installs per-archive launchers, refreshes everything, writes logs, and
manages an optional Windows scheduled task.

```powershell
python git-archive-updater\archive_manager.py --refresh-all --scan-only
python git-archive-updater\archive_manager.py --install-monthly-task --task-day 1 --task-time 09:00
python git-archive-updater\archive_manager.py --task-status
```

Scheduled and launcher runs may only ever *update* or *sync*. `--reconcile` and
`--rename-folders` are interactive-only, by construction — a background job must never rewrite
an origin or rename a folder while you are asleep.

### Publishing — the one command that writes to a remote

```bash
python3 git-archive-updater/archive_sync.py --root /path/to/archive --publish --dry-run
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

### What crosses the wire

Published manifests (schema v3) identify repositories by `HMAC-SHA256(fleet secret,
host/owner/name)`. No display names, URLs, paths, filenames, diffs, commit messages, commit SHAs,
or source content — a record is salted digests and small integers. Readable names come from an
unsynchronized local catalog. The live tier shares readable names *within your own private
tailnet* only. Details and honest limits:
[`.agents/knowledge/manifest-privacy.md`](.agents/knowledge/manifest-privacy.md).

Two rules that make the advice trustworthy:

- **Silence is never good news.** A report too old to trust can never produce an "all clear"; a
  stale clean report becomes `unknown`, while stale unfinished work keeps its warning.
- **Machine freshness and remote freshness are separate clocks.** A manifest written a second ago
  says nothing about how old its remote-tracking refs are, and the dashboard says which is which.

---

## Layout

```text
git-archive-updater/   archive updating: updater, sync engine, pure diff logic, provider seam
github-org-duplicator/ org duplication: orchestrator, gh calls, local scans, workers, resume
git-sync-suggester/    the optional fleet tool (see below)
shared/                primitives used by two or more operations; each a read-only CLI
tests/                 offline, synthetic; no network, no real repositories
.agents/               project brief, working notes, work log, durable knowledge
```

Sync Suggester is the largest, so its modules are grouped by role. They remain flat scripts —
no package, no console-script entry point; `_paths.py` widens `sys.path` once, in whichever file
is executed:

```text
git-sync-suggester/
  sync_suggester.py   the read-only CLI: check, dashboard, converge, watch, doctor, fleet
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
- **Sync Suggester never mutates a repository — including cloning.** When it finds repos you are
  missing, it prints the `archive_sync.py` command that would fix it, and stops.
- **Bounded everything.** Per-command timeouts, bounded discovery, bounded thread pools, forced
  non-interactive Git so nothing can hang on a hidden prompt.
- **Your credentials stay yours.** No token is read, stored, forwarded, or logged.

When unsure, look before you leap:

```bash
python3 git-archive-updater/archive_manager.py --refresh-all --scan-only
python3 git-archive-updater/archive_sync.py --root /path --publish --dry-run
```

---

## Generated, local, and never committed

`.venv/`, `uv.lock`, `*.egg-info/`, `/build/`, `/dist/`, the generated root launchers
(`update-archive.*`, `manage-archives.*`, `duplicate-github-org.*`, `suggest-sync.*`),
`git-archive-updater/managed_archives.json`, both `runs/` folders, and `.agents/output/`.

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
[`.agents/working-notes.md`](.agents/working-notes.md).

Licensed under the Apache License 2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
