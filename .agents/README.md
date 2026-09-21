# gitSpecOps — project brief (`.agents/README.md`)

**This is the primary project document. Read it first.** Root `AGENTS.md` and `CLAUDE.md` are lean
pointers to this file. Tend this document as the project evolves — it is the durable, hand-authored
knowledge the code and git history do not capture.

## What this is for (read before any rule below)

**Start from the situation:** a user has many repositories, spread across many orgs and
namespaces, checked out on several machines. Off-the-shelf clients (GitHub Desktop, Sourcetree,
GitKraken) are surgical tools — fine for one repository at a time, and weak at exactly this. The
family here starts from the many-repos-many-machines case and keeps it in order.

Each operation came from a plain "I should be able to…":

- *I should be able to pull a whole org down to a new machine* → **org duplicator**
- *I should be able to keep a set of repos pulled and fast-forwarded as a group* → **archive updater**
- *I should be able to see which repos need syncing — everywhere they are, from any machine, and
  then fix it* → **Sync Suggester**

The desktop outcome, in the user's words: glance at the system tray, see that repositories are out
of sync, open a dashboard to see where and what, rescue orphaned uncommitted changes, and get
everything in order for every machine — including after not touching a computer for weeks.
Simple, visual, and **equally operable from the terminal**, like the first two tools.

**Therefore these tools perform Git operations.** That is the point. The safety model is about
*how* they act — never *whether*. Two rules, not one:

1. **Watching never changes anything.** No mutation is ever a side effect of observation or of
   time passing. A daemon that silently pulls is the actual catastrophe.
2. **Every mutation is a command the user invoked**, planned, shown, and confirmed:
   detect → plan → approve → execute → review. Fast-forward-only pulls, non-force pushes, nothing
   auto-committed.

The tiers are meant to *differ in capability*, not just latency: durable (a private repo — free,
`gh`-shaped, available to anyone) carries committed history and status; medium (a synced folder or
faster-pinging store) adds saved-but-uncommitted content; live (tailnet) adds real-time and
unsaved buffers. See [`knowledge/tiers-and-capture.md`](knowledge/tiers-and-capture.md).

If a rule further down this file contradicts this section, **this section wins** and the rule is
the thing to fix. That is not hypothetical: a scaffold-era "never writes" claim outranked this
goal for seventeen days — see the correction note in the Sync Suggester section.

## Directives (how to work in this repo)

### Start every session by looking, not remembering

1. **Read this file**, then [`HANDOFF.md`](HANDOFF.md) for where the project stands right
   now, then [`working-notes.md`](working-notes.md) for open items.
2. **Map the tree with the tool**, do not reconstruct it from memory or a few `ls` calls:

   ```bash
   python .agents/tools/generate_folder_structure.py --path . --out .agents/output/folder_structure.md
   ```

   If the script is not there, fetch it first — [`tools/README.md`](tools/README.md) has the
   one-line `curl`. It is gitignored on purpose and takes seconds to retrieve on any machine.
   Then **read the output file.** This repo has been reorganized; a session working from a
   remembered layout will confidently reference files that moved.
3. **Verify before asserting.** Anything you state about this codebase — a path, a flag, a
   behavior — gets checked against the working tree in the same turn you claim it. A memory or
   an older note is a lead, never evidence.

### This is a PUBLIC repository — never write personal information into it

Applies to **every tracked file**: code, comments, docstrings, tests, `working-notes.md`,
`work-log.md`, `knowledge/`, and commit messages. Never commit:

- **Absolute local paths** (`T:\…`, `/home/<you>`, `/srv/<drive>`, `C:\Users\…`) — use
  `<library-root>`, `/path/to/archive`, or a clearly invented example.
- **Real machine names, IP addresses (Tailscale `100.x` included), or tailnet topology** — use
  `<prime-tailscale-ip>`, `machine-a`.
- **Real account, organization, or repository names** — fixtures and self-tests use invented
  names (`old-team`, `new-team`, `example/work`). A real namespace in a self-test is still a
  disclosure, and `archive_diff.py` shipped with one for months before it was caught.
- **Secrets of any kind.** The fleet secret, tokens, anything 64-hex. `doctor` and config dumps
  must keep printing `(set, hidden)`.

Write the *shape* of the finding, not the specimen: "a root under an ignored name discarded
every event" beats naming the drive it happened on. When you must record an operational detail
to be useful, sanitize it as you write it — not later.

`output/` and everything in `tools/` except its README are gitignored, so local detail may live
there freely. That is the release valve.

### Keeping the record

- **Keep `working-notes.md` current** — a living todo / scratch pad. Add items as they arise; prune
  stale or resolved ones regularly. It is what saves the next session from reconstructing state.
- **Graduate completed work into `work-log.md`** with an **absolute date** (e.g. `2026-07-21`).
  Always write dates absolutely — never "yesterday" / "last week".
- **Record durable decisions and findings under `knowledge/`** (one topic per file). Working notes
  are transient; knowledge is kept.
- **Record the bug's cause, not just its fix.** The valuable half is why it hid — which platform,
  which assumption, which test could not see it.

### Constraints that do not bend

- **Prior auth first. Auth belongs to the user.** Tools shell out only to already-authenticated
  host CLIs (`gh auth login`, ...); nothing here stores, configures, or manages credentials, and
  nothing falls back to asking for a secret.
- **Cross-platform first.** Windows, Linux and macOS are peers, not a primary and two ports. A
  platform-specific mechanism (registry Run key, XDG autostart, LaunchAgent, `ReadDirectoryChangesW`
  vs inotify) is written behind one command that works everywhere.
- **Plain scripts, layered — not a package.** No `src/` package, no console-script entry points,
  no clever indirection; every module stays a plain script that can be run directly. Directories
  express the layer stack ([`knowledge/architecture-layers.md`](knowledge/architecture-layers.md)),
  with a one-way import rule: a layer imports only layers below it. *Amended 2026-09-20 — this
  previously read "keep the repo flat", which was about avoiding premature packaging; it was
  being read as "never introduce structure" and would have contradicted the agreed architecture.*
- **No runtime dependencies.** Everything is stdlib. A build-time tool (PyInstaller) lives in a
  disposable environment, never in `pyproject.toml`.
- **Validate on the platform you claim.** "The suite passes" means the suite passes *here*.
  Windows-only defects have shipped twice because validation happened on Linux.

## Repo Shape

> **Target architecture agreed 2026-09-20:** a composition stack built down from git —
> `Basic → Special → Elaborate → App` — with a one-way import rule, the host seam in
> `Basic/providers/`, three skins under `App/skins/`, and `_build/ _docs/ _tests/` at the root.
> See [`knowledge/architecture-layers.md`](knowledge/architecture-layers.md) for the model and the
> full target tree, and [`HANDOFF.md`](HANDOFF.md) for the migration phases. **The section below describes what is
> on disk today.** Phase 1 landed 2026-09-21 (`Basic/` and `_os/` exist; the tool folders import
> downward); the tool folders themselves move in phase 3. Update this as each phase lands.

This repo is intentionally small. Keep it that way.

The entry-point tools are:

- `git-archive-updater/archive_manager.py` (front door: registry, launchers, scheduling)
- `git-archive-updater/archive_updater.py` (standalone, git-only, update-only)
- `github-org-duplicator/github_org_duplicator.py`
- `git-sync-suggester/sync_suggester.py` (cross-machine status, and the group operations that act
  on it — observation never mutates, mutation is always an invoked command)

The archive engine behind the manager is split into single-purpose modules in the same folder:

- `archive_sync.py` (plan/apply: detect -> plan -> decide -> execute -> review)
- `archive_diff.py` (pure decision logic; no git, no network; has a self-test)
- `git_inspect.py` (read-only local git facts; host-agnostic)
- `remote_provider.py` + `provider_github.py` (the cross-git provider seam)

The optional bootstrap helper is:

- `setup_gitspecops.py` (writes the generated launchers, then builds a bare `.venv` — `uv sync`,
  or the stdlib `venv` module as a fallback; the project itself is never installed into it)

Inside each tool folder the modules are still sibling files (imported with a `try: from . / except: from` shim) until phase 3 moves them into the layers. There is no `src/` package, no `cli.py` and no console-script entry point, and there will not be.

### `Basic/` and `_os/` — the bottom of the stack (phase 1, 2026-09-21)

`Basic/` holds the careful primitives every operation builds on. Underscored files are plumbing;
the others are commands, runnable by path:

- `_run.py` — **the one subprocess wrapper**, for git and host CLIs alike: a required timeout that
  kills the whole process tree when it expires, `GIT_TERMINAL_PROMPT=0` for git, UTF-8 decoding,
  and failures as flagged results (`run`, `run_git`) or exceptions (`run_checked`,
  `CommandTimeout`). Nothing else calls `subprocess` for git or `gh`.
  **The tree kill matters on Windows:** the venv `python.exe` and `cmd\git.exe` are launchers
  whose child is the real program; killing only the launcher left the child holding the output
  pipe, so a timed-out call hung until the child exited on its own — a timeout that did not
  bound anything. Both earlier wrappers had this.
- `_facts.py` — read-only repository facts (`repo_facts`, ahead/behind, top level).
- `_identity.py` — parse any remote URL into host/owner/name.
- `_discovery.py` — find repositories on disk. **Cross-filesystem exclusion happens only on
  positive evidence** — an unknown device id never means "skip". Windows is why:
  `os.DirEntry.stat()` there returns a cached record with `st_dev == 0`, and comparing that
  against the root's real device number once made an entire drive scan come back empty.
- `_console.py` — `enable_unicode_output()`, called first in every entry point. The status
  glyphs (`✓ ✗ ⚠ ✎ ↑ ↓ ↕ ⚑ →`) are not cp1252-encodable, which is what Python picks for a
  **redirected** stream on Windows, so `check > status.txt`, a launcher log, or any pipe died
  with `UnicodeEncodeError` *after* the real work succeeded. Printing must never be the thing that fails.
- `_confirm.py` — the approve step: prompts, `--answers` scripted queue, activation-noise filter,
  `confirm_typed("PUBLISH", ...)`. Running out of answers is a clean `SystemExit`, never a "yes".
- `_files.py` — `atomic_write_bytes`, for every state file.
- `_paths.py` — the per-user state folder (`config_home()`, `sync_home()`); never the checkout.
- `status.py`, `discover.py` — read-only commands over `_facts` and `_discovery`.

`_os/` sits beneath every layer and holds per-OS components: `_os/windows/`, `_os/linux/` and
`_os/macos/` carry the same files with the same functions (`tests/os/test_os_parity.py`), and
callers import `from _os.current import <component>` without ever branching on the OS. Today:
`paths` (the per-user config base) and `process` (spawn options and whole-tree kill).

`shared/` still holds `gh_cli.py` and `providers.py` (they become `Basic/_providers/` in phase 2)
and `version.py` (App, phase 4). Scripts reach all of these with the small repo-root `sys.path`
bootstrap they already carry. On Linux the `.sh` launchers need the executable bit (mode 755) —
keep it.

## Launchers

Launchers are **generated by `setup_gitspecops.py` and not committed** — they are convenience
shims; the `.py` entries are the real tools and can always be run directly
(`python3 git-archive-updater/archive_updater.py --help`, or via `uv run python ...`).
One launcher per tool, written into the REPO ROOT (not the tool folder), and only for the
running OS: `.sh` on Linux/macOS, `.ps1` + a `.bat` double-click shim on Windows:

- `update-archive` → `git-archive-updater/archive_updater.py`
- `manage-archives` → `git-archive-updater/archive_manager.py`
- `duplicate-github-org` → `github-org-duplicator/github_org_duplicator.py`
- `suggest-sync` → `git-sync-suggester/sync_suggester.py`

They are gitignored. To change launcher behavior, edit `LAUNCHER_SPECS` / the templates in
`setup_gitspecops.py` and rerun setup — never edit a generated launcher. Each `.ps1` holds the
Windows logic, the `.bat` is a double-click shim, the `.sh` is the POSIX twin; every launcher
prefers the repo's `.venv` and falls back to `uv run`. `run_setup.{bat,ps1,sh}` stay committed —
they bootstrap setup itself. The per-archive `update_archive` launchers and
`refresh-managed-archives` remain generated at runtime by `archive_manager.py` (they bake in
real archive paths) and follow the same prefer-`.venv` scheme.

## Archive Tools

`archive_updater.py` is the low-level, git-only updater. It scans direct children of archive roots and only updates repos that:

- are Git work trees rooted at that child folder
- have an approved `origin` remote
- have clean work tree and index state

It should use fast-forward pulls only. It must not merge, rebase, reset, delete repos, install dependencies, run project code, or recurse through arbitrary nested directories.

`archive_sync.py` is the richer engine used by the manager. It can also discover an org's full repo set through a provider and clone missing repos, reconcile stale origins, and rename folders to match upstream. Every operation is graceful (failures are collected, never fatal) and nothing ambiguous is auto-applied. Discovery is the only host-specific part: when no provider matches the host, or discovery fails, `archive_sync.py` must degrade to the same fast-forward-only behavior as `archive_updater.py` (pull every clean repo; never invent clones, orphans, or renames). The `remote_authoritative` flag in `detect_plan`/`build_plan` is what enforces this; keep it honest.

`archive_manager.py` owns the archive registry and friendly workflow. It installs archive-local `update_archive` launchers (which call `archive_sync.py` in the archive's configured `update` or `sync` mode), tracks managed archive folders, refreshes all managed archives, writes manager logs, and manages the optional Windows scheduled task. Scheduled/launcher runs must never pass `--reconcile` or `--rename-folders`; those mutations stay interactive only.

The registry is local runtime state:

```text
git-archive-updater/managed_archives.json
```

Do not commit local registry contents.

### The push direction ("publish") — shipped 2026-09-03, first slice

`archive_sync.py --publish` is the only code in gitSpecOps that writes to a remote. It is
deliberately narrow, and the narrowness is the feature:

- **Non-force push only.** `git push` with no `--force`, so git itself refuses anything that is
  not a fast-forward — the mirror of `pull --ff-only`. The pull-direction guarantees are NOT
  reused; `archive_diff.build_publish_plan()` is a separate pure classifier.
- **Only ahead-only, clean repositories are eligible.** Diverged goes to a human; behind-only
  needs a pull first; detached or no-upstream means the direction is unknown; in-sync is a no-op.
- **`--publish` is its own apply class** and *refuses* to run alongside
  `--update/--sync/--reconcile/--rename-folders`. `archive_manager.py` never emits it, so
  generated launchers and the scheduled task can never push. `tests/test_archive_publish.py`
  asserts both of those, so the invariant cannot rot quietly.
- **Fetch, then re-check, then push.** The remote may move between planning and pushing; the
  re-check catches that and reports "remote moved — needs a human" instead of forcing.
- **Dirtiness is broader here than for pulling.** `repo_facts` reports tracked changes only,
  which is correct for fast-forward eligibility — untracked files never block a pull. For
  publishing, the question is "is someone mid-edit here?", and an untracked file answers it, so
  `_publish_dirty()` uses `git status --porcelain`. Keep this policy in the publish path; making
  the shared fact stricter would needlessly narrow pull eligibility. `--include-dirty` pushes the
  committed work anyway. **Nothing is ever auto-committed, under any flag.**
- `--dry-run` previews; a typed `PUBLISH` confirms; pushes are paced (`--publish-pause`) so a
  bulk publish cannot become a CI storm.

Still not built, from the original design notes: per-agent branches and `open_pr()` on the
provider seam, auto-commit behind an explicit flag, protected-branch awareness, and secret/size
pre-flight checks. Ship those only if the ahead-only slice proves insufficient.

### Original design notes for the push direction

Historical design rationale, superseded by the shipped `--publish` slice above. A need (e.g. an org where an agent
edits many repos and that work must go back upstream) is the opposite direction. Notes for
whoever builds it, so the safety model is not broken:

- Pull is safe because fast-forward can never destroy data or require a choice. Push needs
  write auth, can overwrite remote history, and can trigger CI / other agents. Do NOT reuse
  the pull guarantees; build a narrower set.
- The provably-safe primitive is "publish" = `git push` WITHOUT `--force` (git refuses a
  non-fast-forward, mirroring `--ff-only` on pull). Classify each repo by ahead/behind vs its
  upstream (`git rev-list --left-right --count @{u}...HEAD`): ahead-only -> ff-push; in sync ->
  nothing; uncommitted -> surface, never auto-commit; diverged -> human only; detached/no
  upstream -> skip.
- Agent considerations: agents leave dirty trees (committing is a policy opt-in, not default);
  do not push agents straight to default branches - prefer a per-agent/per-run branch + PR
  (add `open_pr()` to the provider seam); fetch immediately before each push and let non-force
  rejection mean "remote moved, needs human"; rate-limit to avoid CI/agent storms; give agent
  commits their own identity/trailers; guard blast radius (`--dry-run` preview, typed-YES bulk
  confirm, protected-branch awareness, optional secret/size checks); make runs idempotent and
  resumable.
- Architecture: keep the layers. `git_inspect` gains ahead/behind facts; `archive_diff` gains a
  pure push-direction classifier; `archive_sync` gains a `--publish` phase that is its OWN apply
  class and is NEVER bundled into `--update`/`--sync` nor baked into scheduled launchers (same
  rule that keeps `--reconcile`/`--rename-folders` interactive-only); the provider gains
  `open_pr()`. Ship the ahead-only ff-push slice first; layer auto-commit and branch+PR behind
  explicit flags once the org workflow is settled.

## GitHub Org Duplicator

`github_org_duplicator.py` is the interactive, confirmation-heavy orchestrator. It checks `git`, `gh`, authentication, and org access before moving repositories. **It is GitHub-specific by design** (org concept, `gh repo create`, LFS probing); multi-host support is a stated goal, tracked in `working-notes.md`, and will enter through the shared provider seam — the archive tools are the multi-host frontier. The work is split into cohesive sibling modules in the same folder, imported with plain `import` (the entry point is always run as a script, so its directory is on `sys.path`):

- `gh_common.py` - subprocess wrapper, print lock, run-file dir, console helpers
- `gh_remote.py` - all `gh` CLI calls (env checks, inventory, duplicate comparison)
- `local_repos.py` - adapts shared repo discovery for direct/recursive upload scans + safe deletion
- `tracking.py` - resume state / run files
- `operations.py` - the per-repo download/upload/migrate workers
- `batch.py` - modes 4 (batch) and 5 (single) flows, incl. their flag resolution

Keep new GitHub/`gh` logic in `gh_remote.py` and new filesystem logic in `local_repos.py`; the orchestrator should stay flow-only.

**Subprocess timing rules.** Every `gh` call goes through `shared/gh_cli.run_gh` (120s default);
every git call through `gh_common.run_command` (3600s ceiling — a git op with no progress that
long is hung, not slow — plus a forced `GIT_TERMINAL_PROMPT=0` so a missing credential fails fast
instead of deadlocking a worker pool). Both raise `RuntimeError`/`GhError` on timeout; nothing
blocks unbounded. Retries in `operations.py` use jittered backoff (`_retry_backoff`). The LFS
`.gitattributes` probe (`gh_remote._check_lfs_flags`) is pooled (8 workers, 20s each) — it is a
warning-only signal and must never gate or stall a run.

**Non-interactive layer (added 2026-08-31).** Run with no flags it is still the interactive menu.
`parse_args()` in the orchestrator adds `--batch` / `--single` plus `--namespaces --dest
--[no-]private --[no-]archived --[no-]forks --format --parallel --yes` for an unattended batch,
and `--answers FILE` feeds any remaining prompt (one line each; blank = default) for every mode.
This is why it exists: VS Code / CI type venv-activation lines into an open prompt and corrupt
`input()`. `gh_common.use_scripted_answers()` holds the queue; `prompt_input()` serves from it,
skips activation-noise lines (`_ACTIVATION_MARKERS`), and raises a clean `SystemExit` (not an
`EOFError` traceback) when an answer is needed and none is available. `resolve_directory()` is the
non-prompting twin of `prompt_for_directory()`. Argparse flags in the one script are fine — still
no `src/` package, no console-script entry point. Modes 1-3 are flag-less for now (use `--answers`);
giving them real flags can follow the same pattern.

**Mode 5 spec resolution.** `batch._resolve_repo_or_prompt()` resolves the `owner/name`/URL spec
*before* asking for a target directory and shows the matched repo. A bare token (no `/`, no
`://`) is the trap: `gh repo view <name>` silently prepends the authenticated user as owner, so
`_resolve_one_repo()` rejects a failed bare name with a specific message, and a bare name that
*does* resolve (to one of your own repos) prints `⚠ owner was assumed` and asks to confirm.
`setup_operation()` no longer pre-collects the spec/dir for mode 5 — `run_single_repo(None, None)`
drives the prompts itself.

Run/resume files live under:

```text
github-org-duplicator/runs/
```

Keep output and tracking files there. Do not move them back to the repo root.

## Sync Suggester

**Current fleet model (2026-09-11):** every machine is an independent peer. There is no
host authority and no client enrollment dependency. `fleet setup` guides first run;
`fleet peer` configures directly, and `fleet run` resumes. Old v1/v2 configurations migrate
to v3 while preserving the fleet key. `host` and `connect` are retired commands.

`app/fleet_peer.py` observes locally, publishes to configured folder/GitHub transports,
serves a loopback dashboard, and optionally pulls reports from tailnet peers every 30 seconds.
`app/fleet_config.py` owns peer configuration. SQLite is a local cache, never an authority.
`gh` is required only for the GitHub transport; Tailscale is optional and independent.
One acknowledged inventory is followed by native filesystem events and targeted checks;
there is no periodic repository scan. Newly detected checkouts are announced, then included
only after `fleet rescan`. All transports currently carry status, not recovery content.
See [the current user guide](../git-sync-suggester/docs/FLEET.md) and
[the tier roadmap](knowledge/tiers-and-capture.md).

The folders `core/`, `fleet/`, and `app/` group plain modules; `_paths.py` handles imports.
The legacy `init`/`check`/`watch` commands below use a separate `config.json` and a single
transport. Their polling and transport exclusivity rules do not describe the peer runtime.

**Lifecycle shell (2026-09-11):** `fleet_tray.py` (native Windows tray via ctypes; no runtime
dependency) and `fleet_autostart.py` (per-user start-at-login: registry Run key / XDG autostart /
LaunchAgent, plus an explicit systemd `--user` option) make the app survive a closed terminal.
`fleet tray` and `fleet autostart {status,enable,disable}` are the commands; `tray` degrades to a
foreground run where no tray exists, so one registered command works fleet-wide. Two rules:
start-at-login is **per-user, never a service** (the app must run as the interactive user or the
`gh` login, Git ownership and Tailscale identity all differ), and the tray is **a skin** — it
reads `summary` from the display contract and refuses an unknown contract version rather than
recomputing anything. `fleet_app._main` gained a `stopping`/`on_ready` seam for it, because
`signal.signal` cannot run off the main thread and the Win32 message loop owns that thread.

**Display boundary (2026-09-05):** `fleet_display.py` is the pure, versioned display-model
builder. It owns presentation semantics such as attention, tones, filter tags, notices and
capability availability. `fleet_client.js` owns transport/compatibility; `fleet_view.js` owns
generic selectors; `fleet_dashboard.html` + `fleet_standard.*` are only the standard skin.
Future skins, including LCARS, must consume the same `gitspecops.fleet.display` contract and
must not reimplement Git/freshness policy. See `git-sync-suggester/docs/DISPLAY-CONTRACT.md`.

`sync_suggester.py` is the entry point. **This tool performs Git operations** — that is the
product. It exists so that a user with many repositories, spread across many orgs and several
machines, can see the whole picture from any one of them and then *act on it*: group fast-forward
everything after three weeks away, publish ahead-only work, clone a missing set, rescue
uncommitted work stranded on a machine that is now switched off.

> **Correction, 2026-09-20.** From 2026-09-03 to 2026-09-19 this section claimed the tool "never
> pulls, pushes, commits, stashes, or otherwise touches an observed repository." That described
> the first vertical slice — which genuinely only observed and printed advice — and it was written
> into this brief as if it were a safety principle. It was not one. It contradicted the recorded
> product goal ("convergence is the product, not just observation",
> [new-tool-sync-suggester.md](new-tool-sync-suggester.md)) from the day both were written, and
> because this file is what every session reads first, the stale scope kept outranking the goal.
> **Do not restore that framing.** The boundary below is the real one.

**The boundary: observation never mutates; mutation is always a command the user invoked.** The
observer, the manifest publisher, the watcher, the dashboard, the tray and the scheduled fetch
read local Git facts, publish this machine's status manifest, and read what other machines left
behind — none of them may change a repository as a side effect of observing, or of time passing.
The mutating operations (`fleet catchup --apply`, `fleet materialize --apply`, recovery restore)
are separate named commands that refuse to run beside a live peer and follow the same
detect → plan → approve → execute → review ladder as the archive updater. The flat modules are:

- `observer.py` - bounded direct-child/recursive discovery and local Git observation
- `manifest.py` - salted identities, fleet secret/id, v2 privacy boundary, JSON validation
- `folder_transport.py` - one manifest per machine, same-directory atomic replacement
  (`atomic_write_bytes` is the shared primitive; `config.py` uses it too)
- `repo_transport.py` - the same interface backed by a private GitHub repo via the
  Contents API through `gh` — never cloned
- `config.py` - persistent local config + the local-only catalog (the privacy pressure point:
  it is the file mapping an opaque `repo_id` back to a readable name and a path on this disk)
- `advice.py` - pure single-machine classification and the local ASCII table.
  `classify_repository` gives one **headline** state for severity ordering; anything that renders
  or advises must use `repository_flags`/`describe_repository`/`secondary_facts`, because a single
  state necessarily hides the rest (dirty AND ahead reported only "dirty" until 2026-09-04)
- `aggregate.py` - freshness, cross-machine advice, and the control-tower dashboard
- `watcher.py` - the polling loop; pure enough to test with an injected clock
- `convergence.py` - which repositories peers have that this machine lacks, and naming them

The medium-tier recovery chain (built 2026-09-12 … 2026-09-19) lives beside them in `core/`. None
of it runs until the user has separately confirmed a private recovery location *and* selected
namespaces in the capture basket — an unenrolled machine captures nothing:

- `capture.py` - builds a snapshot of staged/unstaged/selected-untracked work, only after a
  filesystem quiet period, under a per-repository `CapturePolicy` (obey `.gitignore`, secret
  protection, `allow_paths`). Relaxations are recorded in the bundle rather than being silent.
- `secret_scan.py` - the screen that runs before content is ever written into a bundle
- `patch_parse.py` - parsing bundles back into reviewable hunks
- `snapshot_store.py` - bundle storage, retention and size caps
- `snapshot_preview.py` - read what a bundle would do, without touching a repository
- `snapshot_restore.py` - `prepare_disposable_checkout`: restore into a throwaway clone. A
  snapshot is never applied over a live working tree.
- `retirement.py` - **the proof is exact.** It recreates a bundle's resulting tree in a temporary
  index, freshly fetches origin, and permits retirement only if the upstream tree is *identical*.
  Clean state, ahead/behind counts, or an old snapshot never suffice.
- `vscode_buffers.py` - reads VS Code's own backup store for unsaved editor buffers. Bounded,
  root-confined, **metadata only** — it never outputs or transmits buffer content.

**Snapshots are not encrypted**, deliberately; the trust-boundary argument and the per-tier
authority table are in `git-sync-suggester/docs/RECOVERY-DESIGN.md`. Do not reopen it without a
concrete threat the three tiers do not already cover, and do not add a dependency for it.

### Command surface

The legacy read-only commands `init`, `check`, `dashboard`, `converge`, `alias`, `watch`, and
`doctor` all run. **`handoff` stays reserved on purpose** — moving unfinished work between machines
is a mutation flow and gets its own design pass rather than hiding inside the watcher.

The peer runtime's commands are under `fleet` (`app/fleet_app.py` parses them):

- `setup`, `peer`, `run`, `tray`, `autostart`, `rescan`, `baskets` — configuration and lifecycle
- `preflight` - read-only: is Git / the optional GitHub and Tailscale tiers / the loopback port
  usable, and where might a synced folder already be. Creates no configuration.
- `audit` - read-only fleet-scale report of missing origins/upstreams, plain-HTTP origins,
  detached heads, local-only commits, behind state and tracked changes
- `catchup` - fresh non-interactive fetch of every observed checkout, then a printed plan.
  `--apply --yes` fast-forwards **only** clean behind-only checkouts; every other state is listed
  for a human. It cannot commit, push, stash, reset, merge, rebase, or recurse submodules, and it
  refuses to run beside a live peer via the per-configuration lock.
- `materialize` - a reviewed **clone-only** plan for the locally observed working set, behind
  `--apply --yes`. It never replaces or updates an existing destination, validates portable path
  components, and rejects destinations that would escape the library through a symlink.
- `live-buffers` - explicit, local-only, content-free VS Code unsaved-buffer evidence
- `safe-to-wipe` - accepts a dirty checkout **only** for an exact current snapshot acknowledged by
  another peer. Never for unpushed commits, never for a merely recent snapshot.

`catchup`, `materialize` and the recovery applies are the only mutating paths here, they are all
terminal-first and explicitly confirmed, and the dashboard and tray remain skins: they may invoke
the same planner and show its summary, but must never carry their own Git policy.

Four rules hold this design together; do not quietly relax any of them:

- **Silence is never good news.** A machine report that is not current can never produce an "all
  clear". A stale *clean* report becomes `unknown`; a stale *dirty*/*ahead*/*diverged*/*operation*
  report keeps its warning as last-known unresolved work. `WORK_STATES` and `_effective_state()`
  in `aggregate.py` are where that lives, and `tests/test_sync_aggregate.py` pins every case.
- **Machine freshness and remote freshness are separate.** A manifest written a second ago says
  nothing about how old its remote-tracking refs are. `upstream_observed_at` is stamped per
  repository by `--fetch` and evaluated against its own freshness thresholds, so the dashboard
  footnote counts exactly the ↑/↓ values that are actually cached and says how stale they are.
  Never collapse these two clocks into one.
- **The watch must not churn.** It republishes only on a semantic change (`semantic_fingerprint`
  deliberately ignores `observed_at`) plus a heartbeat, because a manifest rewritten every cycle
  would make the user's cloud client upload constantly and bury the write that mattered.
- **Observation never mutates; mutation is always an invoked command.** This is the rule that
  replaced "Sync Suggester never writes" (see the correction note above). Nothing on the observing
  side — the peer loop, the watcher, the tray, the dashboard, the scheduled fetch — may change a
  repository, ever, for any reason, including "it was obviously safe". Mutating operations live on
  the command side, are named and confirmed, refuse to run beside a live peer through the
  per-configuration lock, and follow detect → plan → approve → execute → review. When a mutation
  needs org-wide discovery, call `archive_sync` through the provider seam rather than regrowing a
  cloner here — that is a de-duplication argument, not a safety boundary.

Local state lives outside the repo — `GITSPECOPS_SYNC_HOME`, else XDG on POSIX / `%APPDATA%` on
Windows, under `gitspecops/sync-suggester/`. `config.json` and `catalog.json` are per-machine and
never enter the state directory.

### Transports

Two, behind one small interface (`list_manifests` / `read_manifest` / `write_own_manifest` /
`doctor`). `open_transport()` in the CLI is the single place that decides which is in play, and a
config may hold `state_dir` **or** `state_repo`, never both — two places to publish means two
disagreeing sources of truth.

**The property both must preserve: one file per machine, single writer.** That is why there is no
conflict-resolution code anywhere in this codebase, and any shared-document design would import
that entire bug class. Do not add a transport that breaks it.

`repo_transport.py` uses the GitHub Contents API rather than cloning, because a clone means a
working copy on every machine plus a commit/pull/push cycle plus merge handling, for what is a few
KB of JSON. Read returns the blob `sha`; the write sends that `sha` back, so a concurrent write is
rejected with 409 and re-read rather than clobbered. Retries once, then gives up — it never forces.

Its rules:

- **Never call it from a git hook.** A network round trip inside `git commit` is unacceptable. A
  hook writes local state; upload happens elsewhere.
- **A public state repository is refused**, not warned about (`--allow-public-state-repo` is the
  deliberate escape hatch). Branch names alone say a great deal about what someone is working on.
- **Creating the repository is a separate, explicitly requested act** (`create_state_repo()` /
  `--create-state-repo`). Making a repository on someone's account must never be a side effect of
  a status command.
- Auth is the user's own `gh` login — nothing here stores or manages a credential.

### Compression (`compress_manifests`, off by default)

`init --compress-manifests` gzips published manifests. Measured on a real 20-repository
manifest: 6425 -> 769 bytes, about 8:1, because status records are highly repetitive. That is
what decides how many repositories fit inside one Contents API read at scale.

**It stays off by default deliberately.** An uncompressed manifest is readable by anyone looking
at the folder or the repository, and that inspectability is worth more than headroom most users
never need.

Two details that matter:

- The file is named `<machine>.json.gz` when compressed, so the extension tells the truth. Both
  extensions are listed and readable, and `decode_manifest` detects gzip by magic bytes rather
  than filename, so a renamed file still reads.
- **Toggling the setting changes the filename**, so the writers delete the counterpart — two
  files for one machine would read as two machines' worth of state. `load_manifests` also keeps
  only the newest manifest per `machine_id`, which makes that cleanup non-critical rather than
  load-bearing.
- `gzip.compress(..., mtime=0)` keeps output deterministic: identical content must produce
  identical bytes, or every publish would look like a change.

### Fetching (the only network activity)

`--fetch` on `check`/`watch` is the only network access on the *observation* side (the mutating
commands obviously reach the network too). Rules:

- It runs `git fetch --quiet` with **no refspec**, which moves remote-tracking refs only — never a
  local branch, never the working tree. That is precisely why a fetch is allowed on the
  observation side at all: it is the one network operation that changes nothing the user owns.
- `GIT_TERMINAL_PROMPT=0` is forced. This is the lesson the org duplicator already paid for: a
  repository whose credentials expired otherwise blocks on an invisible prompt until the timeout
  instead of failing in under a second.
- Bounded: a small thread pool (network-bound, so parallelism is a large win) with a per-fetch
  timeout. A failure is collected and the repository keeps its cached counts; a fetcher that
  *raises* is caught too, because one repository must never cost the observation of the rest.
- `upstream_observed_at` is stamped only for repositories that actually succeeded. Never stamp
  optimistically — the whole point is to be able to distinguish measured from remembered.
- The fetch boundary is injectable (`observe_roots(..., fetcher=...)`), which is how the tests
  exercise success and failure with no connection at all. A real fetch of even a bogus host still
  performs a DNS lookup, so an "offline" suite that fetches for real is not offline.

`operation` (rebase/merge/cherry-pick/revert/bisect in progress) is detected from marker paths in
the git dir. It had been in the schema and the advice logic from the start but was never populated
— worth remembering that a field the classifier handles is not the same as a field anyone sets.

### Convergence and the deterministic-hash trick

`converge` answers "which repositories do my peers have that I do not?". The privacy boundary
makes that harder than it sounds: a peer publishes only `HMAC(fleet_secret, host/owner/name)`, so
a machine cannot clone what it cannot name.

The resolution is that the hash is deterministic. Enumerate candidates through the provider seam
for the namespaces this machine already works in, hash each under the same fleet secret, and match.
Consequences worth preserving:

- A repository the provider can see is named **without any name crossing the transport**.
- A repository the user genuinely cannot see stays an opaque id. That is the correct answer; do
  not add a guessing fallback.
- The local catalog is consulted first, so a name already known costs no network call.
- Namespaces default to the ones this machine already has repositories in — not "every org on the
  account". The tool looks where the user already is rather than enumerating their whole presence.

Namespace-level work has no repository URL to parse, so it resolves a provider by host through
`shared/providers.provider_for_host()`; `provider_for(url)` is now a thin wrapper over it.
Registration lives in `git-archive-updater/remote_provider.py` (importing `provider_github.py`
alone registers nothing) — `_register_providers()` in the CLI imports that module.

### Manifest schema v3 and the fleet secret

Synced manifests identify repositories by `HMAC-SHA256(fleet_secret, host/owner/name)` — no names,
paths, URLs, or commit SHAs. Three rules govern the secret; none of them are negotiable:

- **It is generated by `init` on the first machine and carried to the others by the user**
  (`init --fleet-secret <hex>`). It lives only in each machine's local `config.json`.
- **It must never be written into the state directory.** A secret stored beside the data it
  protects protects nothing — that is the whole reason v2 is stronger than v1's bare SHA-256 over
  a brute-forceable `host/owner/name`.
- **Never print it.** `init` shows it once, on purpose, when creating a fleet; `doctor` and the
  config dump show `(set, hidden)` and the public `fleet_id` instead.

`fleet_id` (`HMAC(secret, "…fleet-id")[:16]`) is published so a machine that joined with the wrong
secret is *detected*. Without it, that machine's every `repo_id` would simply differ and it would
look like it shared no repositories with anyone — a configuration error disguised as a data error.
`split_by_fleet` separates those manifests and the dashboard names the machine and the fix.

**v3 closed the last clear-text fields.** `branch` became `branch_id` (HMAC under the fleet
secret, readable names in the local-only catalog's `branches` map), and `upstream` became the
boolean `has_upstream` because every consumer only tested it for truthiness. Identifiers shrank to
128 bits for a repository and 64 for a branch — beyond collision range here, and record size is
what decides how many repositories fit in one manifest at scale. A published record is now salted
digests and small integers; nothing in it names anything.

**How much the salt is worth depends on the transport**, and that is not a contradiction of the
"never store the secret beside the data" rule — it is the scope of it. A cloud folder's provider
reads everything, so the secret must travel out of band. A private repo's access is already gated
and GitHub already hosts the repositories being described, so a key stored there adds no reader.
That asymmetry is what allows a zero-friction join for the repo transport and forbids it for the
folder one. See [`knowledge/manifest-privacy.md`](knowledge/manifest-privacy.md).

Changing the schema again once several machines publish into one folder is expensive, so
schema-affecting work goes first. `validate_manifest` refuses an unknown `schema_version` — with a
specific "re-run check on that machine" message for a v1 file — so a mixed-version fleet fails
loudly instead of silently mis-joining. The complete product/design record remains in
[`new-tool-sync-suggester.md`](new-tool-sync-suggester.md).

## Generated And Ignored State

These are local artifacts and should remain ignored:

- `.venv/`
- `*.egg-info/`
- `uv.lock`
- generated per-tool launchers in the repo root (`update-archive.*`, `manage-archives.*`, `duplicate-github-org.*` — this OS's only)
- `git-archive-updater/managed_archives.json`
- `git-archive-updater/runs/`
- `git-archive-updater/refresh-managed-archives.*`
- `github-org-duplicator/runs/`

If tests or `uv run` recreate `uv.lock` or egg-info metadata, remove or ignore them according to `.gitignore`; do not treat them as source.

## Validation

Useful checks:

Run the whole offline suite with one command — every test file is synthetic, needs no network,
and touches no real repository:

```powershell
uv run python tests\run_all.py
```

Manual experiments live in tracked `tests/probes/`, with synthetic fixtures and their own
instructions. The runner explicitly excludes probes. Their generated profiles, raw logs and
results stay in temporary storage or ignored `.agents/output/`; never track personal output.

Tests are grouped by area — `tests/archive/`, `tests/duplicator/`, `tests/sync/`,
`tests/fleet/`, `tests/repo/` — and each bootstraps imports through `tests/_bootstrap.py`
(`setup("sync")`, `setup("duplicator")`, ...), which adds only the tool folders that file
actually imports. All three tools are flat script directories, so putting every one of them on
`sys.path` would let a module in one shadow a same-named module in another.

**`tests/repo/test_repo_hygiene.py` is the sanitization guard.** It scans *tracked* files for
secrets, local paths, real addresses, tracked generated launchers, and a missing LICENSE. Every
pattern in it corresponds to something this repository actually shipped or nearly shipped. When
it fails, fix the file; only widen its allowlist after deciding the match is genuinely
documentation or invented fixture data. It reports on the working tree only — no test can clean
git history.

Individually, plus the compile and `--help` smoke checks:

```powershell
uv run python -m py_compile setup_gitspecops.py git-archive-updater\archive_updater.py git-archive-updater\archive_manager.py github-org-duplicator\github_org_duplicator.py
uv run python git-archive-updater\archive_updater.py --help
uv run python git-archive-updater\archive_manager.py --help
uv run python github-org-duplicator\github_org_duplicator.py --help
uv run python git-sync-suggester\sync_suggester.py --help
uv run python tests\duplicator\test_selection.py
uv run python tests\duplicator\test_local_repos.py
uv run python tests\duplicator\test_batch_args.py
uv run python tests\sync\test_sync_scaffold.py
uv run python tests\sync\test_sync_config.py
uv run python tests\sync\test_sync_aggregate.py
uv run python tests\sync\test_sync_watch.py
uv run python tests\sync\test_sync_converge.py
uv run python tests\sync\test_sync_observe.py
uv run python tests\archive\test_archive_publish.py
uv run python tests\sync\test_repo_transport.py
```

A fleet is testable on one box: give each simulated machine its own `--config-dir` pointed at one
shared `--state-dir`. Joining with a deliberately wrong `--fleet-secret` should be *reported*, not
silently empty.

Sync Suggester's **observation** commands (`init`, `check`, `watch`, `dashboard`, `doctor`,
`preflight`, `audit`) change no repository, so they are safe to smoke-test live against real
roots — point them at a scratch config dir so they cannot disturb the real one. Do **not** smoke-test
the mutating commands (`catchup --apply`, `materialize --apply`, recovery restore) against real
roots; they have their own disposable-Git tests:

```powershell
uv run python git-sync-suggester\sync_suggester.py --config-dir <scratch> init --machine-id test --root <path> --state-dir <scratch>\state
uv run python git-sync-suggester\sync_suggester.py --config-dir <scratch> check
uv run python git-sync-suggester\sync_suggester.py --config-dir <scratch> watch --interval 2 --heartbeat 0 --cycles 3
```

Do not run live GitHub duplication, archive refreshes, or scheduled-task creation/removal as validation unless the user explicitly requests it.

## Style

Prefer boring, visible, local behavior:

- direct script calls through `uv run python`
- explicit output directories
- JSON or text files in obvious `runs/` folders
- progress output for long scans
- typed confirmation before remote writes or bulk updates

Avoid hidden background behavior, broad filesystem traversal, clever packaging, or surprising cleanup.
