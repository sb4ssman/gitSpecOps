# Work log

Append-only record of **completed** work. Newest first. Items that graduate from
[`working-notes.md`](working-notes.md) land here with an absolute date.

## 2026-08-31

- **Killed the editable install in `.venv` — it was crashing interpreter startup.** Running the
  duplicator via a VS Code "Run" action died with `Fatal Python error: init_import_site` before the
  script ran: `uv sync` had installed the project editable, whose `.pth` runs finder code on every
  startup, and the editor sent a stray `^C` into that import. Full write-up in
  [`knowledge/venv-and-editors.md`](knowledge/venv-and-editors.md). Fix: `pyproject.toml` gets
  `[tool.uv] package = false` (and loses `[build-system]`/`[tool.setuptools]`);
  `setup_gitspecops.py` builds a bare venv with no `pip install -e .`; removed the `__editable__*`
  artifacts + `dist-info` from site-packages, root `git_spec_ops.egg-info/`, and `uv.lock`. Added a
  local (gitignored) `.vscode/settings.json`: `python.terminal.activateEnvironment: false`,
  interpreter pinned to `.venv`, Code-Runner set to not pre-interrupt. `site` import is now ~5 ms
  with no project code; tools verified via `.venv`, the launcher, and system `python3`.

- **Org duplicator: timeout / input-sanitising / error-handling hardening pass.**
  - **Timing:** `gh_common.run_command` had NO timeout — a hung `git clone` (dead connection, or a
    credential prompt with no terminal) blocked a worker thread forever. Now: 3600s ceiling
    (`COMMAND_TIMEOUT_SECONDS`), `GIT_TERMINAL_PROMPT=0` forced on every git subprocess (a missing
    credential fails in <1s instead of deadlocking the pool), and `FileNotFoundError` /
    `TimeoutExpired` become `RuntimeError`. `operations.py` retries use exponential backoff **with
    jitter** (`_retry_backoff`) instead of a lockstep `sleep(5)`, catch `RuntimeError` (not bare
    `Exception`), and clean a partial clone before retrying. `gh_remote._check_lfs_flags` now runs
    the per-repo `.gitattributes` probe in an 8-way pool with a 20s per-probe timeout — a
    150-repo namespace drops from ~2.5 min to ~20 s and one slow probe can't stall the rest.
    `download_one_org` guards `future.result()` so a crashed worker fails one repo, not the batch.
  - **Input:** mode-5 spec rejects a leading `-` and empty string before calling `gh`
    (`resolve_repo_details` + `batch._resolve_one_repo`); `--answers` catches `UnicodeDecodeError`
    (binary file) not just `OSError`; `format_size` tolerates `None` / negatives / non-numbers
    ("size unknown"); `_resolve_repo_or_prompt` defends against a gh record missing owner/name.
  - **Errors:** `check_repo_for_lfs` narrowed from bare `except Exception` to
    `(GhError, binascii.Error, ValueError)` and returns False on any; `_fetch_org_repos` /
    `resolve_repo_details` raise a clear `GhError` on empty stdout instead of a raw
    `JSONDecodeError`; `show_summary` wraps the manifest write so a read-only `runs/` doesn't
    crash a finished run.
  - Tests: `test_batch_args.py` covers the spec guards; live-checked the LFS pool, the
    `run_command` timeout, and an end-to-end batch.

- **Org duplicator mode 5 (single repo): resolve the spec up front, catch the bare-username
  trap.** A user typed a friend's bare username; `setup_operation()` collected it plus a target
  directory with zero validation, then `run_single_repo` failed much later (`gh repo view <name>`
  reads a bare token as `<your-account>/<name>`). Now `run_single_repo(None, None)` owns the
  prompts: `_resolve_repo_or_prompt()` resolves and *shows* the matched repo before asking where
  to put it, re-prompting on failure; `_resolve_one_repo()` gives a bare name with no owner a
  specific "GitHub reads this as one of YOUR repos" message; a bare name that resolves to one of
  your own repos prints `⚠ owner was assumed` and asks to confirm. `--single` unchanged for the
  flag path (still resolves once; `--yes` needs `--dest`). Tests extended.

- **Org duplicator: non-interactive layer so it runs inside VS Code / CI.** The integrated
  terminal (and some shells) type virtualenv-activation lines into an open `input()` prompt and
  corrupt it. Fix:
  - `github_org_duplicator.py` gains `parse_args()` (argparse, flat — no subcommands, no entry
    point): `--batch` / `--single`, `--namespaces --dest --[no-]private --[no-]archived
    --[no-]forks --format {working,mirror} --parallel N --yes`, and `--answers FILE` (feeds any
    remaining prompt, one line each, blank = that prompt's default) for every mode. No flags ->
    the interactive menu, unchanged. `--yes` needs `--namespaces`+`--dest`, takes documented
    defaults for the rest, skips the typed confirmation.
  - `gh_common.use_scripted_answers()` holds the answer queue; `prompt_input()` serves from it,
    echoes each, broadens the activation-noise filter to a substring match over
    `_ACTIVATION_MARKERS` (adds `.ps1`/`.fish`/`.csh`/`conda activate`), and turns a
    "need an answer, none available" (strict queue empty, or terminal `EOFError`) into a clean
    `SystemExit` with guidance instead of a traceback. New `resolve_directory()` is the
    non-prompting twin of `prompt_for_directory()`.
  - `batch.py`: `run_batch_download(args=None)` / `run_single_repo(spec, root, args=None)` /
    `ask_filters(args, assume_yes)` resolve each value as flag > (`--yes` default) > prompt;
    the "pick individual repos" and typed-YES steps are skipped under `--yes`.
  - `tests/test_batch_args.py` (offline, synthetic): parser rejects/accepts, scripted-answer
    queue + echo + strict-overflow, activation filter, `ask_filters` resolution. Full suite green;
    end-to-end verified against a tiny real namespace.
  - Docs: `README.md` + `.agents/README.md` duplicator sections, `--help` epilog, Validation list.
  Modes 1-3 stay flag-less (use `--answers`) — noted in working-notes.

- **First live run of the org duplicator Mode 4 (batch download).** Backed up all 9 GitHub
  namespaces (`sb4ssman` + 8 orgs) to the `memory-lambda` archive drive at
  `/memory-lambda/Github/<namespace>/<repo>` — 153 repos, working clones, private + archived +
  forks included, 3 parallel per org. **153/153 succeeded, 0 failures**, ~16 min, ~69 GB on disk
  (GitHub's reported 26.8 GB understates full object/history size). Batch manifest:
  `github-org-duplicator/runs/batch_20260831_173958.json`.
  - The VS Code integrated terminal swallows interactive input, so the run was driven by piping a
    10-line answer file to stdin of `github_org_duplicator.py` (detached, logged). Recorded the
    prompt order and recipe in agent memory; UX follow-up (a real `--yes`/answer-file mode) is in
    `working-notes.md`.
  - `git-lfs` was absent and this box has no passwordless sudo — installed the standalone
    `git-lfs` 3.6.1 binary to `~/.local/bin`, ran `git lfs install`, and launched the job with
    `~/.local/bin` on PATH. Only one repo in the set uses LFS
    (`true-bots/magiconion-sample-client`); its LFS blobs were verified as real content, not
    pointers.
  - **Post-run trim (per user):** the `true-bots` org was not wanted — `True-Bots-Inc` is the
    keeper. Removed `true-bots` from the archive (moved to
    `/memory-lambda/Github/.trash-true-bots-20260831`, ~37 GB — final `rm -rf` left for the user
    to run; the sandbox refuses recursive delete outside `/tmp`) and deleted its four
    `runs/*__true-bots.txt` resume files. Also fully removed git-lfs again: `git lfs uninstall`
    (global config + repo hooks) and deleted `~/.local/bin/git-lfs`. Active archive is now 8
    namespaces; `True-Bots-Inc` intact at 55 repos.

- **Completed a pre-commit family audit and refreshed the root README.** Reframed the project as
  three repository-level special operations and documented Sync Suggester's one-machine usefulness
  and cross-machine purpose, current privacy boundary, commands, and roadmap. Corrected all launcher
  examples to the generated repo-root location. Audit fixes: batch existing/completed comparisons
  are case-insensitive; batch defaults no longer report ENTER as invalid; manifest publication now
  requires an explicit machine ID; stashes/operations cannot render as synchronized; observer status
  uses `GIT_OPTIONAL_LOCKS=0`; the duplicator no longer runs `gh auth setup-git`; and the shared
  `gh_cli.py` standalone interface no longer exposes an arbitrary command passthrough. Consolidated
  the remaining duplicator `gh` calls into `gh_remote.py` and made every clone-format prompt reject
  invalid input instead of silently choosing regular clones.

- **Established the Sync Suggester scaffold.** Added a runnable flat, stdlib-only read-only tool:
  bounded shared discovery/Git observation, SHA-256 canonical repository identities, a strict v1
  manifest privacy boundary, atomic one-machine-file folder transport, pure local advice, and a
  readable table joined from local-only names. `check` and `doctor` run; `init`, `watch`, and
  `handoff` are explicitly reserved for the next slice. Added the generated `suggest-sync` launcher
  spec and synthetic offline contract tests in `tests/test_sync_scaffold.py`.

- **Centralized tests under the root `tests/` folder.** Duplicator selection and local-discovery
  tests use invented org/repository names and disposable temporary paths only; no personal
  namespaces, repository names, or machine paths are present.

- **Duplicator upload discovery now uses the shared scanner.** Mode 2 prompts for recursive
  (default) or original direct-child scope and recognizes worktrees, `.git`-file links, and
  bare/mirror repositories. Case-insensitive basename collisions stop before any remote calls.
  Added `tests/test_local_repos.py`, using synthetic repositories in a temporary directory only.

- **Created the `shared/` layer** (first cross-operation refactor; decision in
  [`knowledge/shared-layer.md`](knowledge/shared-layer.md)). New stdlib-only, read-only,
  standalone-CLI modules: `remote_identity.py` (URL → host/owner/name), `git_facts.py` (`run_git` +
  per-repo facts incl. ahead/behind), `repo_discovery.py` (pruned repo finder / scanner), and
  `gh_cli.py` (single `gh` wrapper, `run_gh`/`GhError`). Admission rule: a method moves into
  `shared/` once two of the three special operations need it. `git_inspect.py` and `archive_diff.py`
  are now facades re-exporting shared primitives; `provider_github.py` and the duplicator's
  `gh_remote.py` route all `gh` calls through `shared/gh_cli.py`.

- **First Linux verification of setup + launchers.** `run_setup.sh` → `uv sync` built `.venv`
  (CPython 3.13.5); all three `.sh` launchers prefer `.venv/bin/python` and run correctly; shared
  CLIs, `archive_diff` self-test, live `provider_github list`, and all `--help`s pass. Fixed:
  `.sh` launchers were committed without the executable bit (mode 644) — now 755.

- **Folder naming made uniform (user-driven rename):** `gitArchiveUpdater/` →
  `git-archive-updater/`, `github-org-duplicator/` kept (GitHub-specific on purpose), empty
  `git-sync-suggester/` added for the planned status/decider tool. All stale references fixed:
  launchers, `archive_manager.py` generated-script strings, `.gitignore`, README, `.agents` docs.

- **Launcher policy changed:** per-tool launchers are now GENERATED by `setup_gitspecops.py`
  (`LAUNCHER_SPECS` + templates) and gitignored — no longer committed. `run_setup.*` stay
  committed as the setup bootstrap. Mode 4 batch org download (`batch.py`) landed in
  `github-org-duplicator/`: print-style range selection (`1-5, 7, 9-25`), names, `all`,
  `except`/`!` exclusions, runtime-prompted filters, per-org scoped tracking files, batch
  manifest.

- **Provider plumbing moved into `shared/`:** new `shared/providers.py` (RemoteProvider
  protocol, host registry, `provider_for` with subdomain matching); `RepoRef` moved to
  `shared/remote_identity.py`; `archive_diff.py` and `remote_provider.py` are now facades;
  providers register tool-side (`register_provider("github.com", GitHubProvider)`), keeping
  shared free of tool imports. Auth stance documented: users authenticate their own host
  CLIs; nothing here manages credentials.

- **Repo-level granularity + uniform flow (duplicator):** one shared selection grammar
  (`gh_common.parse_selection`: print-style ranges `1-5, 7`, names, `all`, `except`/`!`)
  now drives namespace selection, per-namespace repo picking (Mode 4), a repo-subset prompt
  (Mode 1), and the new Mode 5 — single repo by `owner/name` or URL (any public repo) into
  the same `<parent>/<owner>/<repo>` layout. Uniform pre-download warnings block
  (`gh_common.print_download_warnings`) shown in modes 1/4/5; `prompt_for_directory`
  expands `~` (already did) and `$VARS` now too.

## 2026-08-06

- **Consolidated Sync Suggester research and family design.** Added
  [`new-tool-sync-suggester.md`](new-tool-sync-suggester.md) covering the cross-machine problem,
  public-fork/private-branch constraint, privacy-minimized manifests, transport alternatives, watcher
  and UI concepts, safety classifications, how Archive Updater/Sync Suggester/Org Duplicator can
  share capabilities, and a no-mutation vertical slice. Identified a user-selected cloud-synced
  folder as the simplest experiment; private Git, provider app folders, object storage, and P2P remain
  optional transports.

## 2026-07-21

- **Stood up the `.agents/` workspace.** Migrated the full project brief out of the fat root
  `AGENTS.md` into [`README.md`](README.md) (primary project document + Directives), and slimmed
  root `AGENTS.md` / added an identical `CLAUDE.md` as lean pointers. Created `knowledge/`,
  `tools/`, `output/`, and the living `working-notes.md` / `work-log.md`.

- **Setup / venv architecture shipped** (commits `5165d17` + `cd5a608`). Settled model:
  UV-preferred, stdlib fallback, a permanent `.venv` instead of per-launch `uv run`.
  - `setup_gitspecops.py` rewritten as an optional bootstrap: `uv sync` first (honors `uv.lock`),
    falling back to stdlib `venv` + `pip install -e .`; reports git/gh/uv. No longer writes
    launchers.
  - Committed static launcher trios (`.bat` shim → real `.ps1` → `.sh`) for the org duplicator and
    the two archive-updater entry points; each prefers the repo's `.venv` Python and falls back to
    `uv run` when `.venv` is absent. `run_setup.{bat,ps1,sh}` added.
  - `archive_manager.py`'s runtime-generated per-archive launchers and `refresh-managed-archives`
    now emit the same trio + prefer-`.venv` scheme.
  - Duplicator folder safety: `prompt_for_directory()` re-prompts instead of `sys.exit`; the
    non-empty download destination warning now lists the colliding repo names and requires `[y/N]`.
