# Work log

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

## 2026-08-06

- **Consolidated Sync Suggester research and family design.** Added
  [`new-tool-sync-suggester.md`](new-tool-sync-suggester.md) covering the cross-machine problem,
  public-fork/private-branch constraint, privacy-minimized manifests, transport alternatives, watcher
  and UI concepts, safety classifications, how Archive Updater/Sync Suggester/Org Duplicator can
  share capabilities, and a no-mutation vertical slice. Identified a user-selected cloud-synced
  folder as the simplest experiment; private Git, provider app folders, object storage, and P2P remain
  optional transports.

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
  namespaces (`<account>` + 8 orgs) to the external archive drive at
  `<archive-root>/Github/<namespace>/<repo>` — 153 repos, working clones, private + archived +
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
    (`example-org-a/magiconion-sample-client`); its LFS blobs were verified as real content, not
    pointers.
  - **Post-run trim (per user):** the `example-org-a` org was not wanted — `example-org-b` is the
    keeper. Removed `example-org-a` from the archive (moved to
    `<archive-root>/Github/.trash-<namespace>-<date>`, ~37 GB — final `rm -rf` left for the user
    to run; the sandbox refuses recursive delete outside `/tmp`) and deleted its four
    `runs/*__example-org-a.txt` resume files. Also fully removed git-lfs again: `git lfs uninstall`
    (global config + repo hooks) and deleted `~/.local/bin/git-lfs`. Active archive is now 8
    namespaces; `example-org-b` intact at 55 repos.

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

## 2026-09-03

- **Manifest compression as an opt-in setting (`compress_manifests`, default off).** Requested by
  the user after the scale measurements. `init --compress-manifests` gzips published manifests:
  6425 -> 769 bytes on a real 20-repository manifest, about 8:1, since status records are highly
  repetitive. Off by default because an uncompressed manifest is readable by anyone looking at the
  folder or repository, and that inspectability beats headroom most users never need.
  - Compressed manifests are named `<machine>.json.gz` so the extension does not lie, but
    `decode_manifest` detects gzip by magic bytes rather than filename, so a renamed file still
    reads. Both transports list and read either extension.
  - **Toggling the setting changes the filename**, which would otherwise leave one machine
    publishing two files and reading as two machines. Both writers now delete the counterpart, and
    `load_manifests` independently keeps only the newest manifest per `machine_id` — so the
    cleanup is a tidiness measure rather than something correctness depends on. A cleanup failure
    never fails a publish.
  - `gzip.compress(..., mtime=0)` keeps the bytes deterministic; identical content must not look
    like a change.
  - Verified live in both directions: off -> on -> off leaves exactly one file each time.
  - Also dropped the "personal vs org fleets" product speculation from the notes. It was not
    blocking any code, and "fleet" simply means the machines sharing one `fleet_secret`.

- **Manifest schema v3: the last clear-text fields are gone, and the record got smaller.**
  Agreed with the user before wiring change-detection hooks, on the same reasoning as v2 — a
  schema change is free while no fleet is deployed.
  - **`branch` -> `branch_id`**, HMAC under the fleet secret. `feature/acquire-northwind` says more
    than a repository name does. Readable names moved to the local-only catalog (`catalog.json`
    gained a `branches` map), so a branch this machine has seen still renders as `main` and one
    only a peer has renders as `branch:1a2b3c4d` — the same arrangement repository names already
    used. Branch ids are not lowercased: git branch names are case-sensitive.
  - **`upstream` -> `has_upstream`** (boolean). Grepping every consumer first showed the string was
    only ever tested for truthiness, so publishing the ref name was pure surplus.
  - **Identifiers shrank** to 128 bits (repository) and 64 bits (branch). Beyond collision range
    here, and at scale record size is what decides how many repositories fit in one manifest.
  - Verified live: `main`, `origin`, the account name and the archive path are all absent from a
    real 20-repository manifest, while the local table still shows real branch names. 11/11 pass.
  - **Corrected an over-broad claim of my own.** The note "a secret stored beside the data it
    protects protects nothing" is transport-dependent, not universal. A cloud provider reads both,
    so the folder transport must carry the secret out of band. A private repo's access is already
    gated and GitHub already hosts the repositories being described, so a key stored there adds no
    reader — which is what makes a zero-friction join possible for the repo transport specifically.
  - **Scale measured, not guessed** (the user asked whether this suits enterprise/mega users):
    361 B/repo before, 321 after, so ~3,200 repositories fit the Contents API's 1 MB inline read.
    Compression is the real lever — status manifests are highly repetitive and gzip to ~59 B/repo,
    which is ~18,000 repositories in one manifest. Rate limits are a non-issue (5,000/hr against
    ~2 calls per publish). What does *not* scale yet is `--fetch` over tens of thousands of repos
    (20 took 4s at 4 workers) and discovery over a very large tree; the dashboard is already fine
    because the exceptions view shows only what needs action.

- **Second transport: a private GitHub repo, without ever cloning it.** The user found the
  designated-private-repo option (transport #2 in the design doc) correct but tedious. The tedium
  is not inherent — it comes from assuming a repo must be cloned, committed to, pulled and merged.
  For a few KB of JSON with one writer per file, none of that is needed.
  - `repo_transport.py` uses the GitHub Contents API through the already-authenticated `gh`: read
    is one GET, write is one PUT. The blob `sha` a read returns is exactly what the write must send
    back, which buys optimistic concurrency for free — a concurrent write is rejected with 409, and
    the code re-reads and retries once rather than forcing. No clone, no working copy, no local git
    state, no merge logic, no new auth, no new dependency.
  - Setup is one flag: `init --state-repo owner/name --create-state-repo`.
  - **A public state repository is refused outright**, not merely warned about. First implementation
    only warned; that is too weak for something whose whole premise is not leaking. Branch names are
    still published in the clear, and in a public repo that is readable by anyone.
    `--allow-public-state-repo` is the deliberate escape hatch. Verified against a real public repo.
  - Creating the repository is a separate explicit act, never a side effect of a status command.
  - `open_transport()` is now the single place that decides which transport is in play; config may
    hold `state_dir` or `state_repo` but never both, and that is enforced in `validate_config`.
  - `tests/test_repo_transport.py` fakes `gh` entirely (offline) and pins the concurrency contract:
    a write carries the sha it read, a first write carries none, a 409 re-reads with the fresh sha,
    a persistently rejected write gives up instead of clobbering, no force-like argument ever
    reaches `gh`, unsafe machine ids and manifest names are rejected, the v2 boundary still applies
    on the way out, and a 403 is not swallowed like a 404. 11/11 suite files pass.
  - Decided with the user: `--fetch` stays opt-in and user-scheduled. The watchdog discussion
    settled on git hooks via a chained global `core.hooksPath` as the zero-idle-cost change
    detector, with an OS timer optional; see working-notes.

- **The push direction shipped: `archive_sync.py --publish`, first slice.** The only code in
  gitSpecOps that writes to a remote, kept as narrow as the design notes demanded.
  - `archive_diff.build_publish_plan()` is a separate pure classifier — the pull-direction
    guarantees are explicitly not reused. Only ahead-only clean repositories are eligible;
    diverged is a human decision, behind-only needs a pull, detached/no-upstream is
    direction-unknown, in-sync is a no-op.
  - Push is `git push` with no `--force`, so git itself refuses a non-fast-forward. Each
    repository is fetched and **re-checked immediately before its push**, so a remote that moved
    between planning and pushing reports "needs a human" instead of being forced. Pushes are paced
    so a bulk publish cannot become a CI storm. `--dry-run` previews; a typed `PUBLISH` confirms.
  - `--publish` is its own apply class and *refuses* to combine with
    `--update/--sync/--reconcile/--rename-folders`; `archive_manager.py` never emits it, so
    generated launchers and the scheduled task cannot push. Both invariants are asserted by tests
    rather than left to memory.
  - **Dirtiness had to be redefined for this direction.** `repo_facts` reports tracked changes
    only — correct for fast-forward eligibility, since untracked files never block a pull. The
    first test run caught the consequence: a repository whose only change was an untracked file
    read as clean and got pushed. `_publish_dirty()` now uses `git status --porcelain` in the
    publish path only; making the shared fact stricter would have needlessly narrowed pull
    eligibility.
  - `git_inspect.py` re-exports `repo_facts`/`ahead_behind` — the facade existed to re-export
    shared primitives and was simply missing these.
  - `tests/test_archive_publish.py` pushes for real, but every remote is a bare repository in a
    temporary directory, so nothing leaves the machine. It proves the ahead-only commit reaches
    the remote, a diverged repository is refused and its history left intact, a dirty repository
    is held back and its uncommitted file untouched, a re-run is a clean no-op, and both
    never-bundled / never-scheduled invariants hold. 10/10 suite files pass.
  - Not built, and deliberately: per-agent branches with `open_pr()`, auto-commit behind a flag,
    protected-branch awareness, secret/size pre-flight. Ship those only if this slice proves
    insufficient.

- **Wrote the handoff design pass** ([`handoff-design.md`](handoff-design.md)). `handoff` has been
  a reserved subcommand since the scaffold; this is the document it was reserved for. Key points:
  handoff would put **real source code into the state folder**, which today holds only hashes — so
  content must live in a separately configured directory, be expiring by design, and never be on
  by default. The five transferable things (unpushed commits, tracked changes, untracked files,
  ignored files, stashes) carry sharply different risk; untracked files are the most likely way
  this tool would ever leak a secret, and ignored files must never move. The public-fork
  visibility constraint applies directly: a WIP branch in a public repository is world-readable,
  so the tool must check visibility and refuse rather than assume. **Recommendation: do not build
  handoff yet — build publish and see whether the remaining need is real**, since most of "I left
  work on the other machine" is unpushed commits, which needs no new transport, no new privacy
  boundary, and no patch machinery. Three open questions are listed for the user.

- **Real remote knowledge: opt-in `--fetch`, and `operation` detection that was never wired up.**
  - Until now every ↑/↓ came from remote-tracking refs that could be days old, and
    `upstream_observed_at` rode through the schema always `null`. `check --fetch` / `watch --fetch`
    now refresh refs first and stamp the time per repository. `git fetch` with no refspec moves
    remote-tracking refs only — never a branch, never the working tree — which is what lets a
    read-only tool do it at all. `GIT_TERMINAL_PROMPT=0` is forced, reusing the org duplicator's
    hard-won lesson: expired credentials otherwise block on an invisible prompt until the timeout.
    Bounded thread pool, per-fetch timeout; 20 real repositories take ~4s over 4 workers.
  - The dashboard note is now precise instead of blanket: it counts exactly the ↑/↓ values that are
    still cached and distinguishes "never fetched" from "fetched too long ago", evaluating
    `upstream_observed_at` against its own thresholds. Machine freshness and remote freshness stay
    two separate clocks.
  - **`operation` was in the schema and the advice logic from the beginning but nothing ever set
    it** — a repository left mid-rebase reported as merely clean or dirty. Now detected from marker
    paths in the git dir (rebase-merge/rebase-apply/MERGE_HEAD/CHERRY_PICK_HEAD/REVERT_HEAD/
    BISECT_LOG). A field the classifier handles is not the same as a field anyone populates.
  - **Made fetch failures graceful.** A fetcher that *raised* took the entire observation down,
    against this repo's own "failures are collected, never fatal" rule. Now caught per repository.
    The test that first documented the bad behavior was rewritten to demand the good behavior
    rather than enshrine what the code happened to do.
  - **The fetch boundary is injectable** (`observe_roots(..., fetcher=...)`), the same discipline
    that makes `watcher.py` testable. This was not cosmetic: the first version of the test used
    real `example.test` remotes and an `insteadOf` rewrite, and both were wrong — a bogus host
    still performs a DNS lookup (so an "offline" suite that fetches for real is not offline), and
    `insteadOf` changes what `git remote get-url` reports, which silently destroyed the repository
    identity and made repositories vanish from the observation.
  - `tests/test_sync_observe.py` (offline): every operation marker, the opt-in boundary, fetch
    success/failure/raise, unparseable origins being skipped with a reason, and progress reporting.
    9/9 suite files pass.

- **Fleet convergence: `converge`, and the deterministic-hash trick that makes it possible.**
  This is the half of the product that answers "which repositories do my other machines have that
  this one does not" — the thing GitKraken's grouping cannot do across machines.
  - The obstacle was self-inflicted and worth stating: after schema v2, peers publish only
    `HMAC(fleet_secret, host/owner/name)`, so a machine **cannot clone what it cannot name**. The
    resolution is that the hash is deterministic — enumerate candidates through the provider seam
    for the namespaces this machine already works in, hash each under the same fleet secret, and
    match. A repository the provider can see is named without any name crossing the transport; one
    the user genuinely cannot see stays an opaque id, which is the correct answer rather than a
    guess.
  - The local catalog is consulted first, so names already known cost no network call; the catalog
    now records host/owner/name (it is local-only, so it may hold the full identity) and gains
    entries for identified peer repositories, deliberately *without* a `path` — that absence is
    what distinguishes "known but absent" from "on disk".
  - `converge` never clones. It prints the concrete `archive_sync.py --root <derived from where
    that owner's repos already live> --github-owner <owner> --sync` command instead. Growing a
    second cloner here would duplicate `archive_sync`'s preview/confirmation logic *and* move a
    mutation into the one tool whose safety story is that it only reads.
  - **Two real bugs found by running it live**, both silent failures rather than errors:
    `_register_providers()` imported `provider_github.py`, which registers nothing — the
    `register_provider()` call lives in `remote_provider.py`. And `provider_for()` needs a full
    repository URL, so a namespace-only URL parsed to no host and returned `None`. Fixed the second
    properly by adding `shared/providers.provider_for_host()` — namespace-level work legitimately
    has no repository URL to parse — with `provider_for(url)` now a thin wrapper over it. Also
    added a warning when no providers register at all, so this fails loudly next time.
  - Verified live end to end: a machine with an empty catalog named all 20 peer repositories
    through `gh`, and a machine whose catalog already knew them made zero provider calls.
  - `tests/test_sync_converge.py` (offline, stub provider that records its calls): the missing-set
    logic, peer attribution, catalog seeding proving the network was skipped, unresolvable ids
    staying opaque, candidates hashed under the wrong secret never matching, provider errors and
    unregistered hosts being reported rather than fatal, `roots_by_owner` choosing the common
    parent, and the report emitting a real command. 8/8 suite files pass.

- **Manifest schema v2: salted identities, and the fleet secret.** Done first and deliberately —
  the user's goal is three machines converging on one state folder, and a schema change is free
  today and expensive once a fleet is publishing.
  - `repo_id` is now `HMAC-SHA256(fleet_secret, host/owner/name)`. The secret is 32 random bytes
    made by `init` on the first machine, kept only in that machine's local config, and carried to
    the others by the user via `init --fleet-secret`. It is never written into the state directory,
    because a secret stored beside the data it protects protects nothing.
  - **`head` dropped.** A commit SHA identifies any public repository outright and nothing in the
    tool ever read it — classification works from ahead/behind, dirty counts, stashes, operation.
  - **`fleet_id` added** (a public HMAC-derived label). Without it, a machine that joined with the
    wrong secret produces valid manifests whose every `repo_id` differs, so it silently looks like
    it shares no repositories — a configuration error disguised as a data error. `split_by_fleet`
    now separates those and the dashboard names the machine and the fix.
  - Publishing without a fleet secret is refused rather than falling back to weaker unsalted
    identities; unsalted ids remain only for a local preview that never reaches the transport.
    `doctor` and the config dump print `(set, hidden)` and the public `fleet_id`, never the secret.
  - Verified live with three machine configs against one state folder: two sharing a secret
    correlate 20/20 repositories, the third (wrong secret) correlates 0/20 and is reported by name.
    Confirmed the published manifest contains no secret, no `head`, and no name/path/URL.
  - **Still in the clear: `branch` and `upstream`.** Kept on purpose — a hashed branch could be
    compared but never displayed, and cross-machine branch differences are worth showing — but it
    is now the main remaining correlator. Options recorded in `knowledge/manifest-privacy.md`.
  - Tests updated to v2 across the three sync suites, plus new coverage: the identity must change
    with the secret, must differ from the unsalted form, malformed secrets must raise, the secret
    must not appear in a manifest, `head` must be rejected, a v1 manifest must be refused with
    actionable guidance, and the wrong-fleet machine must be named on the dashboard. 7/7 pass.

- **Sync Suggester: the first vertical slice is complete and the tool is genuinely useful.**
  `init`, `check`, `dashboard`, `alias`, `watch`, and `doctor` all run; only `handoff` is still
  reserved, deliberately, because moving unfinished work between machines is a mutation flow that
  needs its own design pass rather than hiding inside the watcher.
  - **Persistent local state** (`config.py`): OS-appropriate config dir (`GITSPECOPS_SYNC_HOME`,
    else XDG / `%APPDATA%`) holding `config.json` (machine identity, registered roots with a
    per-root recursive flag, state dir, freshness thresholds) and the local-only `catalog.json`
    (`repo_id` -> readable name, path, user alias). `init` is flag-driven and refuses to clobber
    without `--force`; `--from-archives` imports the roots Archive Updater already manages.
    `merge_catalog` lets re-observation update facts while user aliases survive.
    `folder_transport.atomic_write_bytes` was factored out so config and manifests share one
    atomic-replace implementation.
  - **Cross-machine aggregation** (`aggregate.py`): freshness classification (current <= 24h,
    stale <= 7d, expired beyond), per-machine cells, cross-machine advice, and the control-tower
    dashboard from the design document. The rule that shapes it: **silence is never good news** —
    a stale *clean* report becomes `unknown`, while a stale *dirty*/*ahead*/*diverged*/*operation*
    report keeps its warning as last-known unresolved work. Everything except one manifest-reading
    helper is pure, so a fixed clock drives every boundary in the tests.
  - **The dashboard is an exceptions view.** Showing 20 clean rows plus "OLDPI unknown" on each was
    unreadable, so rows needing no action fold into a counted summary — a summary that still names
    the machine whose silence made them quiet, so a folded row is never mistaken for a proven
    all-clear. `--all` lists everything. Any ↑/↓ on screen is footnoted as cached remote-tracking
    knowledge, since no fetch has been run.
  - **`watch`** (`watcher.py`): a visible polling loop that republishes only on a semantic change
    (`semantic_fingerprint` ignores `observed_at`, so time passing is not a change) plus a periodic
    heartbeat, survives a failing cycle instead of dying, and makes a best-effort final observation
    on the way out. The loop takes its observation, publication, clock, and sleep as parameters, so
    the tests drive hours of behavior instantly. The CLI stops on an `Event` rather than a flag, so
    a SIGTERM mid-interval is answered in ~0.5s instead of waiting out a 30s sleep — measured.
  - **Duplicator modes 1-3 timeout bug fixed.** Three retry loops in `operations.py` caught
    `RuntimeError`, which `CommandTimeout` subclasses — so a command that had already burned the
    full 3600s ceiling was retried twice more, turning a 1-hour hang into a 3-hour one. They now
    re-raise like mode 4's clone loop. `tests/test_batch_args.py` gained an AST check asserting
    every retry loop in that file handles `CommandTimeout` first; verified it fails when the guard
    is removed.
  - **Tests:** new `tests/test_sync_config.py`, `tests/test_sync_aggregate.py`,
    `tests/test_sync_watch.py`, and `tests/run_all.py` (one command for the whole suite). All
    offline and synthetic — invented repository names, temporary directories, injected clocks, no
    network. 7/7 files pass. Live smoke was read-only only: `check`, `dashboard`, and `watch`
    against real local roots via a scratch `--config-dir`.
  - **Privacy finding, needs a user decision.** A real published manifest was verified to leak no
    name, path, URL, or host. But `repo_id` is an unsalted hash of `host/owner/name` (a tiny,
    brute-forceable input space), `head` publishes a commit SHA that de-anonymizes any public
    repository and that *nothing in the tool reads*, and branch names are human-authored. Analysis,
    options, and a recommendation are in [`knowledge/manifest-privacy.md`](knowledge/manifest-privacy.md);
    each option is a `schema_version` bump, so it is the user's call.

## 2026-09-04

- **Fixed the Windows discovery bug reported in the outside fleet review — the tool found nothing
  at all on a Windows drive.** A `check` against `<library-root>\...` returned an empty fleet. The
  review's diagnosis was exactly right: `os.DirEntry.stat()` on Windows serves data cached from
  the directory scan, and that cached record carries `st_dev == 0`, while the root statted
  directly reports a real device number. The cross-filesystem guard compared the two, found them
  unequal, and rejected **every** direct child — so a whole drive silently disappeared.
  - `shared/repo_discovery.py` now excludes only on *positive evidence* of a different device.
    Unknown never means skip. `device_id()` treats a zero as unknown, and `entry_device_id()` uses
    the free cached value first, paying for a real `os.stat` only when the cache has none — so the
    fast path on Linux is unchanged.
  - `tests/test_repo_discovery_devices.py` reproduces the Windows symptom on any platform by
    wrapping `os.scandir` so entries report a cached device of 0. Mutation-checked: against the old
    code it fails with "found 0 of 3 repositories". It also pins that a genuinely different device
    is *still* excluded, so the fix is not just the check being disabled, and that
    `cross_filesystems=True` still bypasses it entirely.
  - Confirmed on the real Windows T: drive after landing: direct-child discovery found all 5
    repositories under `<namespace-a>`, all 8 under `<namespace-b>`, and all 3 under
    `<namespace-c>`. A combined Sync Suggester check rendered 15 repositories (the sixteenth,
    `<namespace-c>/tools`, was correctly reported separately because it has no recognized origin).
  - The full suite then exposed two POSIX-only test assertions, not product failures: one compared
    a native Windows path to a slash-delimited suffix and one expected POSIX archive roots.
    Rewrote both assertions with `pathlib.Path` so the offline suite is portable.

- **Compound facts are no longer hidden by precedence** (also from the review). `classify_repository`
  returns one headline state, which severity ordering needs but which necessarily buries everything
  behind it — a repository that was both dirty and ahead reported only "dirty", and the unpushed
  commits vanished. The headline is now documented as ordering-only, and everything that renders or
  advises uses the new `repository_flags` / `describe_repository` / `secondary_facts`. Live result
  on this repository: `STOP: uncommitted work on cbox (also ahead 9)`. Tests cover dirty+ahead,
  behind+stash, diverged+dirty, missing-upstream+dirty, and that a clean repository invents no
  extras. 12/12 suite files pass.

## 2026-09-05

- **Removed perpetual fleet scanning and deployed native event-driven observation on machine-a.**
  Configuration v2 performs one acknowledged startup inventory, then Linux inotify or Windows
  `ReadDirectoryChangesW` wakes the observer only for filesystem changes. Events are debounced and
  mapped to the deepest known checkout; only that repository is inspected. The 30-second heartbeat
  updates authenticated presence without Git or directory scans. `fleet rescan` is the deliberate local
  inventory command for added/removed repositories. The former v1 polling configuration migrates
  automatically. A real temporary-repository test confirms idle silence and targeted untracked-file
  detection; the machine-a host migrated and restarted with 105 repositories and no periodic scan.
  Live create/delete smoke checks each inspected exactly one repository. Full offline validation
  passes 14/14 files; Python compilation, JavaScript syntax and whitespace checks pass.
  The live heartbeat was further reduced to one authenticated timestamp: no full report crosses the
  network or gets rewritten merely to prove that an observer is online.
- **Added and validated the desktop-preview build boundary.** `fleet_desktop.py` owns only first-run
  launch and opening the browser; `GitSpecOpsSync.spec` embeds Python and the standard UI without
  moving fleet policy into the shell. A clean Linux PyInstaller 6.22.2 one-folder build completed
  at 24 MiB and reached isolated first-run setup. The same recipe must be built on Windows to make
  the Windows executable. Existing configurations can now add, create, change, or clear scheduled
  folder/GitHub replicas explicitly with `fleet replicas` while the observer is stopped.
  Prime was then switched from the source command to the built bundle; its embedded dashboard,
  SQLite host and native observer reported all 105 repositories in a live smoke check.

- **Made the live Fleet Management dashboard dark by default and fixed group-collapse state.**
  The standard skin now has an immediate dark theme with a saved light/dark preference. Closed
  repository groups survive the three-second display refresh and browser reloads. App & setup now
  shows the live Tailscale, synchronized-folder and GitHub-replica levels plus the actual
  availability of continuous observation, remote actions and unfinished-work recovery snapshots;
  planned controls are not rendered as working toggles.
- **Made continuous discovery explicit and reduced its cadence.** Interactive setup names every
  recursive root and requires the user to type `SCAN`; direct setup requires
  `--acknowledge-continuous-scan`, and existing configurations use `fleet acknowledge-scan`.
  Changed the default and this machine-a pilot from five to 30 seconds after each scan. The
  earlier five-second pilot measured about 34 MiB RSS and 11.2% of one CPU while observing 105
  repositories; a scan itself normally takes 3.2–3.4 seconds. The scanner reads Git metadata and
  status only and does not copy repository content into the fleet store.
- Live verification: `machine-c` answered a direct Tailscale ping at `<machine-c-tailscale-ip>` in 13 ms;
  `machine-b` timed out and appears offline/asleep. The restarted dashboard reports 105
  repositories through display contract v1 at `http://<machine-a-tailscale-ip>:8765/`.

- **Established the Fleet Management display boundary and replaced the prototype dashboard.**
  `fleet_display.py` now emits versioned `gitspecops.fleet.display` v1 with explicit attention,
  tones, tags, facts, notices and capability availability. The standard responsive UI consumes
  it through separate transport and selector modules; repository, machine, detail and app/setup
  views contain no Git classification rules. `DISPLAY-CONTRACT.md` defines compatibility and
  gives a future LCARS skin the same source of truth. The source-ZIP endpoint was removed after
  user feedback; `/download` now returns 404.
- **Recorded the desktop distribution and update direction.** A normal user installs a
  self-contained app, uses graphical first run, and does not clone source or install Python.
  Developer checkouts remain the current preview. `knowledge/distribution.md` records staged
  bundling/signing, per-channel signed release metadata, store/direct update ownership, rollback,
  and the remaining release work. Verified the corrected `machine-c` Tailscale name.
- Validation: display/authorization tests pass, all three JavaScript modules pass syntax checks,
  pure selectors pass Node fixture checks, static routes and display v1 respond live, the removed
  download responds 404, and the full offline suite passes 13/13 files. The host remains running
  at `http://<machine-a-tailscale-ip>:8765/` with the new interface.

- **Implemented and started the personal Tailscale fleet pilot on machine-a.** New
  foreground app with guided setup, stable device identity, per-peer write authorization,
  SQLite persistence, browser namespace/status dashboard, and source-only observer ZIP.
  Existing gh auth is checked without configuring or forwarding credentials. Private tailnet
  reports share repository names; scheduled folder/GitHub replicas contain only v3 manifests.
  Replica clocks do not perform early runtime reads/writes or retry immediately on failure.
- Live smoke: host HTML, dashboard JSON and ZIP returned 200; machine-a observed 105 repositories
  and detected this session's own uncommitted work. Browser screenshot inspected. Added tests
  for authorization, stale/old reports, metadata validation, scheduling, locking and bundle
  contents. Full offline suite passed 13/13 files before final documentation updates.
  Windows observers remain pending; no source sync, remote commits, content capture or
  GitHub publication was performed. See git-sync-suggester/docs/FLEET.md for usage and limitations.

- Retried fleet connectivity: both Windows devices answered Tailscale ping; former machine-c
  now advertises machine-b at its previous IP. Old hostname no longer resolves.
  Reviewed official GitHub permission/API guidance, Obsidian Headless Sync, Tailscale grants,
  and OCI free-instance reclamation constraints for the continuing transport/auth discussion.

- Reviewed exchange and distribution options at the user’s request before fleet deployment.
  Verified Microsoft Store MSIX versus MSI/EXE update routes, Apple sandbox/notarization
  constraints, Flathub requirements and GitHub REST content-write limits against official docs.
  Recommendations are proposals, not approved architecture or implemented desktop features.

- **Fleet readiness audit on machine-a.** Read the project brief, roadmap and transport
  implementation. Confirmed existing GitHub authentication and Tailscale reachability to both
  Windows laptops outside the sandbox. Remote-management probes (22/5985/5986) timed out.
- Ran a read-only recursive Sync Suggester check against `<archive-root>/Github` using isolated
  config/state under `/tmp/gitspecops-fleet-audit-9sp2xmx5`: 105 repositories observed, dirty
  Chassis and FlowNode surfaced, FlowNode stash surfaced, and one unrecognized-origin warning
  for the <namespace-b> root. Ahead/behind readings remain cached; no fetch was requested.
- Validation: `python3 tests/run_all.py` passed all 12 test files. No repository synchronization,
  remote state publication, persistent configuration or background service was performed.

## 2026-09-11

- **Built the lifecycle shell the fleet was missing: tray, start-at-login, Windows build.**
  The app had no way to outlive a terminal, so the host was simply not running and no machine
  could enrol — `fleet connect` cannot reach a host that is down. New `fleet_tray.py` is a
  stdlib-only native Windows tray (ctypes; the project carries no runtime dependencies) showing
  one reported state with counts, a menu (open dashboard / rescan / start-at-login / quit), and
  balloon notifications on real transitions only. It is a **skin**: every number comes from the
  `gitspecops.fleet.display` document and an unknown contract version is refused, not parsed.
  New `fleet_autostart.py` does per-user start-at-login (registry Run key, XDG autostart,
  LaunchAgent, plus explicit systemd `--user`), reversible from the same API. `fleet tray`
  degrades to a foreground run where no tray exists, so one registered command works on every
  machine. Added `fleet_app` commands `tray` and `autostart`, a `stopping`/`on_ready` seam
  (`signal.signal` cannot run off the main thread, and the Win32 message loop owns it), and
  `--configure-only` so a graphical shell can finish setup and then start under the tray.

- **Fixed three real bugs found by building and running the above, not by reading it.**
  - **Windows filesystem observation never fired.** `WindowsEvents._read` tested the ignore list
    against the *absolute* path, so a root that merely sat under an ignored name — `AppData`,
    any folder called `Library`, `env` or `venv` — discarded every event and observed nothing,
    silently, forever. Linux prunes while walking and was unaffected. This was failing at HEAD
    on Windows before any of today's work. Extracted `ignored_relative()` and pinned it with a
    cross-platform regression test so the Linux suite cannot hide it again.
  - **`UnicodeEncodeError` on every redirected run.** Status glyphs are not cp1252-encodable,
    which is what Python picks for a redirected stream on Windows, so `check > file`, a pipe or
    a launcher log crashed *after* the work succeeded. Affected the org duplicator too. New
    `shared/console.py` (`enable_unicode_output()`) is called first in each entry point.
  - **Intermittent 64-bit ctypes overflow in the tray.** `restype` was set without `argtypes`,
    so ctypes marshalled GDI/window handles as C `int`; handle values grow during a session, so
    the first icon built and a later one raised "int too long to convert" inside the window
    procedure. Every signature is now declared explicitly.
  Also: `launch_command` no longer guesses the entry point from `sys.argv[0]` — the same tray
  menu item can be clicked from `sync_suggester.py fleet tray`, from `fleet_app.py`, or from the
  frozen build, and registering an argv the target cannot parse yields a login entry that fails
  silently every boot. Callers pass the script explicitly.

- **Produced the Windows executable that was blocking deployment.** PyInstaller 6.22.2,
  one-folder, 25 MiB, built on `machine-c` (PyInstaller does not cross-compile, which is why
  only the Linux bundle existed). `GitSpecOpsSync.spec` now names `fleet_tray`,
  `fleet_autostart` and `shared.console` as `hiddenimports` — all three are imported lazily, so
  static analysis missed them and the frozen build would have failed only when a user clicked a
  tray menu item. The bundle is also the full CLI, which is how it is smoke-tested.

- **Setup no longer demands a hand-typed Tailscale URL.** `fleet_net.discover_hosts()` lists
  tailnet peers and marks which are actually serving; `fleet setup` offers those and, when none
  are, names the machines it can see and says the host app is not running — previously that
  appeared as a bare connection error. Verified live: machine-a reported online but not serving.

- Validation: full offline suite **15/15** including the previously failing
  `test_fleet_events.py`; new `tests/test_fleet_tray.py` (14 checks: contract handling, stale
  reports, autostart against an in-memory backend so no real registry entry is ever written,
  discovery ranking). Unicode fix verified under both pipe and file redirection. Frozen exe
  verified for hidden imports and a clean exit path. No start-at-login entry was registered and
  no fleet configuration was created on this machine during this work.

## 2026-09-11 (later) — public-repo readiness

- **Sanitization is now a test, not a habit.** `tests/repo/test_repo_hygiene.py` scans every
  *tracked* file for secrets, local paths, real Tailscale addresses, tracked generated
  launchers, leaked `.agents/tools|output` files, and a missing LICENSE. Every pattern maps to
  something this repo shipped or nearly shipped today. It found two real problems on its first
  run (an unsanitized path in `FLEET.md`, and LICENSE not yet tracked). It audits the working
  tree only — no test can clean history.
- **Tests grouped by area**: `tests/{archive,duplicator,sync,fleet,repo}/`, with
  `tests/_bootstrap.py` replacing five different hand-rolled `sys.path` incantations. `setup()`
  takes the areas a file needs, because all three tools are flat script directories and loading
  them all could shadow same-named modules. `run_all.py` recurses and labels by folder.

- **Licensed the project.** Was MIT in `pyproject.toml` with **no `LICENSE` file at all**, which
  on a public repository means nobody had permission to use it. Now Apache-2.0 (`LICENSE` +
  `NOTICE`): permissive like MIT, but adds an explicit patent grant, contribution terms, and a
  trademark clause — worth having for a tool that operates on other people's repositories. Done
  now because there are no releases and no outside contributors, so it is still free to change.

- **Security / disclosure audit of every tracked file, and of the full git history.**
  - **No secrets, in the working tree or in history** — no tokens, no 64-hex fleet secrets, no
    keys. SQL is fully parameterized; no `shell=True`, `eval`, `exec`, or `pickle` anywhere; the
    fleet listener binds to the Tailscale address only, not `0.0.0.0`; asset serving is an exact
    URL map with no traversal. The fleet secret is printed only where intended and `doctor`
    still hides it.
  - **Caught before it shipped:** a generated launcher (`gitArchiveUpdater/refresh-managed-…bat`)
    containing an absolute personal path was **staged for commit** — `.gitignore` covered the
    post-rename folder but not the old-cased one. Unstaged and ignored.
  - **`archive_diff.py`'s self-test used a real organization and real repository names**, against
    this repo's own stated rule that fixtures never do. Replaced with invented ones
    (`old-team`/`new-team`); the rename changed a `sorted()` expectation, which was fixed rather
    than papered over.
  - Sanitized tracked docs: real machine names, tailnet addresses, archive paths, and private
    namespaces are now placeholders (`machine-a`, `<library-root>`, `<archive-root>`).
    **History still contains the originals** — a rewrite was not done, and would break clones.
  - `_legacy_sources/` removed from tracking (reference-only snapshots; still in history).

- **Rebuilt the README** around what the tool actually *does*: three special operations (org
  duplication, archive updating, cross-machine sync suggestion), then requirements and the one
  hard assumption that explains most of the design — **authentication is the user's and stays
  theirs**. Corrected a stale privacy claim that still described schema v2 and said branch names
  were published in the clear; v3 salts them.

- **Version contract (`shared/version.py`).** The version had been typed into two files with no
  tags and no releases, so "am I current?" had no answer. One constant now feeds `pyproject.toml`
  and the display contract, with `--version` / `version --check` on the CLI and a line in the
  tray menu. The check is **read-only**: it reports, never downloads or self-replaces. Every
  failure — offline, no `gh`, rate limited, no release yet — reports **unknown**, never "up to
  date"; `tests/test_version.py` pins that, and caught `check_for_update` propagating an
  unexpected exception, which was then fixed in the code.

- **Reorganized `git-sync-suggester/`** from 25 flat files into `core/` `fleet/` `app/` `ui/`
  `packaging/` `docs/`, with `_paths.py` as the single place that widens `sys.path`. Still flat
  scripts — no package, no console-script entry point. A folder named `build/` was renamed to
  `packaging/` after discovering `.gitignore`'s `build/` pattern silently ignored it at any
  depth; the root patterns are now anchored (`/build/`, `/dist/`). Caught during the move: the
  deleted `REPO_ROOT` was still referenced by `--from-archives`, a path no test covers.

- **`.agents/` directives rewritten.** Sessions kept working from remembered layouts, so the
  brief now opens with: map the tree using `.agents/tools/generate_folder_structure.py` (fetched
  per-machine, gitignored) and *read the output* before reasoning about structure. Added the
  privacy directive — no local paths, machine names, addresses, or real namespaces in any
  tracked file — plus "validate on the platform you claim". `tools/` and `output/` are now
  untracked except their READMEs.

- Validation: offline suite **16/16**; all four entry points; `archive_diff` self-test; Windows
  bundle rebuilt from the new layout and smoke-tested.

## 2026-09-11 (later) — the peer model

- **Collapsed host/connect into one kind of machine: a peer.** The old split was the design
  mistake behind every symptom: one machine owned the SQLite store and served the dashboard,
  clients pushed reports to it, and when it was off nobody could publish and nobody had a
  dashboard. Now every machine observes itself, publishes to every transport it has, serves its
  own loopback dashboard, and talks to peers only when Tailscale happens to be up.
- **Peers pull; they never push.** `make_peer_server` is GET-only (`/v1/manifest`, plus
  `/v1/session` for painless joining); POST is 405. That deletes the write path entirely — no
  write authorization to model, and an unreachable peer is simply not polled rather than an
  error. The old `make_server` remains only for the retired host.
- **Tailscale is now strictly optional and strictly last.** `resolve_machine_identity` falls
  back to the Sync Suggester machine id, and `PeerNetwork.start()` degrades with a message
  saying what still works. A peer with no network observes, publishes to a synced folder, and
  shows a dashboard.
- New `app/fleet_config.py` (schema v3 + migration), `app/fleet_peer.py` (runtime),
  `fleet/ui_assets.py`, `fleet/local_view.py`, `app/local_dashboard.py`. Transports became a
  dict because they are complements, not alternatives. `fleet transports` replaces `replicas`.
- **Bugs found by running it, not reading it:** the multi-source merge counted one machine
  twice (`load_manifests` dedupes internally; my merge bypassed it — fixed with a public
  `newest_per_machine` that stays silent across sources, since a duplicate there is expected
  rather than a defect), and peer logging did not flush, leaving an empty log exactly when the
  process runs under the tray or at login with stdout redirected.
- v1 and v2 configurations migrate automatically; `host`/`connect` print a migration message
  instead of an argparse error. Validation 19/19, plus a live no-Tailscale peer and a rebuilt
  Windows bundle.

## 2026-09-11 (later) — new-repository detection, and the tier design

- **A repository cloned into the library was invisible until someone ran `fleet rescan`.**
  The events always fired; `affected_repositories` maps an event only to a *known* checkout, so
  they were dropped. `IncrementalObserver.detect_new_checkouts` now walks up from an unmatched
  event to the enclosing directory containing `.git`, and the peer logs it and raises it as a
  dashboard issue. It detects without adding — membership stays explicit, per
  detect -> alert -> approve. The defect was the silence, not the confirmation step.
- **Recorded the tier design** in [knowledge/tiers-and-capture.md](knowledge/tiers-and-capture.md):
  the three tiers should differ in what they can *rescue*, not only in latency, and today they
  all carry the same status manifest. Includes the finding that VS Code already persists dirty
  editor buffers to `%APPDATA%\Code\Backups`, which — if written eagerly rather than at exit —
  means unsaved work can be observed without any editor plugin. Flagged as needing an empirical
  test before anything is built on it.
- Also recorded: there is no scanning anywhere (one inventory, then kernel notifications), and
  the only periodic work in a peer is a 20s tailnet poll plus change-gated transport publishes.

## 2026-09-11 (later) — history audit, handoff, tailnet poll 30s

- **Audited the whole git history properly, and stated the confidence honestly.** The first pass
  used `git log -p --all | grep`, which covers only diff text on reachable refs and skips binary
  blobs — not good enough to make a claim. The second enumerated every object
  (`git rev-list --objects --all`) and scanned the content of **every blob**: 566 objects, 355
  blobs, seven secret shapes. **No secrets in history.** The one credential-shaped hit is a test
  fixture asserting that `http://user:password@...` is rejected. Personal data *is* in history
  (3 addresses, 4 machine names, 5 namespaces, 1 Windows path) and was sanitized forward only.
  Method, confidence limits, and the full "what to do if a secret is ever found" procedure —
  rotate first, rewrite second, purge GitHub fork/cache last — are recorded in
  [knowledge/repo-privacy-and-history.md](knowledge/repo-privacy-and-history.md).
- **Wrote [HANDOFF.md](HANDOFF.md)** for the next session: current state, the one important
  unbuilt thing (the tier ladder), decisions owed by the user, and the traps this codebase has
  already fallen into once each.
- Tailnet peer poll moved from 20s to 30s at the user's request.

## 2026-09-11 — handoff takeover verification

- Read the brief, handoff, working notes and tier design; regenerated and inspected the tree.
  Working tree was clean at entry. Verified the peer runtime and guided-setup entry point.
- Ran the offline suite on Windows using the existing Python 3.14.2 virtual environment:
  **19/19 test files passed**. System Python 3.10 is below the project's required minimum.
- Independently reproduced lost publication during a transport cooldown; recorded the cause
  and proposed regression coverage in working notes. No runtime changes made in this review.
- Flagged obsolete host-based enrollment guidance; the current peer model takes precedence.

## 2026-09-11 — guidance, durable setup, and reusable probes

- Reconciled active host/client guidance across the primary brief, root README, fleet user
  guide, packaging guide and working notes. The old pilot knowledge record is explicitly
  historical. Updated moved test paths and distinguished legacy commands from peer behavior.
- Guided durable setup now opts in before calling gh, suggests a private state repo using the
  existing login, describes app-owned status files and publication conditions, and requires
  named CREATE/USE confirmation. Public/read-only repositories are refused. No real state
  repository was created during development.
- Fixed lost transport updates: observation previously consumed the change fingerprint even
  when publication was rate-limited, and the idle loop had no deferred delivery. Each transport
  now retains its latest pending snapshot until successful delivery and retries at its next
  slot. The idle loop drains cached status without Git scans or invented observation times.
  Regression checks cover cooldown, coalescing, failed writes, and idle-loop integration.
- Wrote the recovery implementation contract in `git-sync-suggester/docs/RECOVERY-DESIGN.md`.
  A single HEAD diff loses staging boundaries; the design preserves separate staged/unstaged
  changes. Capture implementation waits on the encryption dependency decision.
- Added `tests/probes/` for versioned manual experiments at the user's request. The VS Code
  backup probe creates a disposable profile/workspace and records pre-exit backup evidence;
  default execution only prepares it. Automated tests explicitly exclude probes. Preparation
  and JavaScript syntax checks pass; no editor run or empirical backup result is claimed.
- Windows offline suite passed 19/19 after the durable setup/publication changes.

## 2026-09-11 (later) — editor backup evidence and the desktop Git client shortcut

- **VS Code hot-exit probe run, with a real unsaved edit.** The user left one unsaved change in
  the root README; the probe found a backup whose content differs from the saved file while the
  saved file was untouched. VS Code 1.137.0 therefore persists dirty buffers before exit on this
  machine. The probe measures existence, **not** latency — do not claim a timing guarantee.
  This supports evaluating a backup reader for the live tier; it is not an editor integration.
- **Optional desktop Git client shortcut (`app/git_client.py`).** Per-machine selection in
  App & setup and an "Open in ..." action in repository details. Clients are discovered only in
  standard install locations, launched with fixed arguments and no shell, and the browser may
  supply only a known client id or an observed repository id — never a path or command. No Git
  mutation happens here; serious work moves to the chosen client, by design.
- `build_display` remains the only place this becomes semantics: a row carries `desktop_action`
  with an honest reason, and a repository with no local checkout reports unavailable.
- Verified end to end over HTTP against the synthetic probe server: client selection, a launch
  for the local checkout (simulated launcher fired exactly once), refusal for a peer-only
  repository, and a 403 for a cross-site origin. `tests/fleet/test_git_client.py` covers the
  same boundaries. Windows offline suite: **20/20 test files passed**.

## 2026-09-11 (later) — baskets: per-scope repository selection

- **Baskets built** (`app/baskets.py`, config schema **v4**, `fleet baskets`). Roots stay the
  filesystem boundary; baskets narrow what happens inside it in three independent scopes —
  `observe`, `publish`, `capture`. Selection is by namespace (`host/owner`) with modes
  `all` / `none` / `only` / `except`.
- **Capture cannot be turned on.** It is not implemented, so `validate_scopes` refuses anything
  but `none` and the CLI cannot set it. A toggle that claims to protect uncommitted work while
  protecting nothing is worse than no toggle.
- **Matching is local by construction.** A manifest carries salted digests and no names, so the
  filter can only be applied where the catalog lives. No peer can see or infer another machine's
  baskets.
- **Publication is filtered once, before either consumer.** The tailnet peer endpoint serves the
  same report object as the transports, so filtering per transport would have leaked a withheld
  repository to any reachable peer. The publish fingerprint is taken on the filtered view, so a
  change confined to a withheld namespace correctly publishes nothing.
- **Found and fixed a real defect with an end-to-end check.** `sources()` read this machine's
  *own* manifest back out of the transport, where the publish basket had already narrowed it,
  and that narrower echo won over live local state — so withheld repositories disappeared from
  the one screen that must always show them. A peer now ignores its own manifest as read back
  from a transport. The seam-level unit tests could not have caught this; the integration test
  that did is now `test_withheld_work_never_reaches_a_transport`.
- Narrowing is stated, never silent: a withheld row is badged *not published* in the dashboard
  with a reason, `withheld` / `unobserved` notices appear, App & setup shows all three scopes,
  and new-checkout alerts no longer nag about namespaces the observe basket excludes.
- Migration v3 → v4 reproduces v3 behavior exactly (observe all, publish all, capture none).
- Windows offline suite: **21/21 test files passed**; hygiene gate passed.

## 2026-09-12 — recovery: trust boundary settled, capture core built

- **Decided: snapshots are NOT encrypted** (`docs/RECOVERY-DESIGN.md`, "Trust boundary"). The
  user challenged the premise and was right. The earlier draft required an `age` CLI and a
  stdlib-only exception; that imported a generic default instead of reasoning from this
  project's own recorded principle. Every tier already rides inside a system that authenticates
  — private GitHub repo (`gh`, refuses non-private), the user's sync account, and Tailscale
  (`peer_identity()` rejects devices not owned by the allowed login, and tagged devices) — with
  HTTPS/HTTPS/WireGuard on the wire. Verified in the code, not from memory.
- Three facts closed the gap: captured work is **already plaintext in the working tree on the
  same disk**; remotely, access control is the boundary (same conclusion as
  `knowledge/manifest-privacy.md`); and a key must reach every peer to restore, so losing it
  destroys the work the feature exists to save — while a key beside its ciphertext protects
  nothing. **No new dependency; the stdlib-only runtime rule is intact.**
- Consequences recorded rather than assumed: **secret scanning is now load-bearing**, and
  **capture never inherits the status folder** (that folder may have been chosen while manifests
  were names-free and harmless). `FORMAT`/`format_version` make an encrypted format additive if
  the decision is ever revisited.
- **Built `core/capture.py`**: staged (HEAD->index) and unstaged (index->worktree) patches kept
  **separate** — a lone `git diff HEAD` flattens them and loses staged work the worktree later
  reversed. Binary-capable, opaque repo ids, explicit untracked selection, policy exclusions
  that beat an explicit selection, size limits that refuse rather than truncate, and a
  before/after state comparison that refuses a bundle assembled from two different moments.
  External diff/textconv helpers are disabled: a "read-only" capture must not run user programs.
- **Built `core/secret_scan.py`**: shape-based rules (key blocks, AWS/GitHub/Slack/Google/Stripe/
  JWT, assigned credentials) that refuse the whole snapshot and report **path and rule only** —
  never the matched value, since the refusal message is itself somewhere a secret must not go.
  Placeholders (`changeme`, `${VAULT_...}`) and prose do not cry wolf.
- **Capture remains unavailable to users**, and the capture basket still refuses any value but
  `none`. Store, preview, restore, retirement proof and peer wiring are not built.
- Two test assertions were wrong and the code was right: the unstaged patch legitimately shows
  staged text as a *removal* (it is relative to the index), and file capture is byte-exact
  including Windows CRLF. Both now pin the real behavior. Suite: **22/22 on Windows**.

## 2026-09-12 (later) — recovery: snapshot store and preview

- **Built `core/snapshot_store.py`.** Layout `gitspecops-snapshots/v1/<machine>/bundles/<repo>/
  <version>.json.gz`; each machine writes only beneath its own directory, so no file is ever
  written by two machines and one machine can never delete another's copy. Receivers record
  acknowledgements under *their own* `acks/` tree.
- Durability states are kept apart: `written` (reached this disk) is never promoted to
  `recoverable elsewhere` until another machine has read the bundle back and acknowledged
  *that exact checksum*; a mismatched acknowledgement does not count, nor may a machine
  acknowledge itself.
- Bounded storage never costs a last copy: superseded versions prune by count (reported, not
  silent), retention expires as explicit policy with `expiring()` for advance warning, and a
  full store **refuses** a new capture rather than deleting any repository's newest version.
  Identical recaptures write nothing. User deletion is previewed and executes exactly the plan.
- Everything read back is untrusted: ids validated before becoming paths, bounded
  decompression (a gzip bomb is refused, not allocated), format/checksum verified, and a valid
  bundle found under the wrong machine or repository directory is not believed there.
- `validate_location` **refuses** a capture location overlapping an observed root — writing a
  snapshot raises filesystem events that would trigger capture again, an endless loop — and
  always warns about the status folder and about sharing, which cannot be detected.
- **Built `core/snapshot_preview.py`**, in-memory only (a preview that writes nothing cannot be
  tricked into writing something). Lists staged/unstaged changes (added, deleted, renamed,
  binary) and carried files, and collects every reason a bundle is unsafe: traversal, absolute
  and drive paths, `.git`, Windows reserved names and invalid characters, case-insensitive
  collisions, size/digest mismatch, truncated or malformed hunks, binary changes without
  content. The parser tracks hunk line counts, so a removed line reading `-- comment` is never
  mistaken for a file header. `base_available()` checks a target checkout for the base commit.
- **Real defect found while designing the parser:** capture did not pin diff prefixes, so a
  user's `diff.mnemonicPrefix` produced `c/`/`i/`/`w/` headers — confirmed with a direct git
  probe — that another machine could not parse. Capture now passes `--src-prefix=a/
  --dst-prefix=b/` and `--no-textconv`; a regression test sets both hostile configs.
- Suite: **24/24 on Windows**.

## 2026-09-12 (later still) — recovery: restore, and capture policy toggles

- **Built `core/snapshot_restore.py`.** `prepare_disposable_checkout` clones a repository holding
  the base into a new or empty folder and detaches at the base; the source is only read and
  restore never fetches. `restore` refuses any bundle preview marks unrestorable, and any target
  that is not the top of a checkout, not at the base, not clean (untracked files included), or
  mid-operation. It applies staged (`--index`), then unstaged, then carried files; on any failure
  it resets to the base and removes what it created. **Success is verified**: `git diff --staged`
  and `git diff` in the target must reproduce the captured patches byte for byte, and each
  carried file must match its digest.
- **Carried files never overwrite**, ignored files included — a clean `git status` still permits
  an ignored file sitting under the snapshot's name, which is exactly the trap.
- **Fidelity boundary measured, not assumed** (Windows, Git 2.52; probe across `core.autocrlf`
  unset/true/false/input): Git's staged and unstaged content was exact every time apply
  succeeded; working-tree bytes of patched text files follow the *target's* line-ending settings,
  as any checkout would; carried untracked files are byte-identical. An apparent `autocrlf=false`
  failure was the probe's own artifact (config set after cloning) and re-verified clean.
- **Hazards found by the probes and pinned:** a user's `apply.whitespace=fix` would silently
  rewrite restored content and `error` would refuse it — apply now pins whitespace handling on the
  command line, and the test first proves plain `git apply` is refused by that config. Capture
  decoded git output with replacement, so a non-UTF-8 text file would have been stored lossily —
  it now decodes strictly and refuses. Preview refuses symlink (120000) and submodule (160000)
  modes.
- **Capture policy toggles, at the user's request** (`CapturePolicy`): obey `.gitignore` and
  secret protection, both default on, per repository, local-only, never synced; every
  relaxation is written into the bundle's notes. `allow_paths` was added so that deliberately
  carrying one `.env` does not force switching screening off for everything else. `.git` is
  always excluded — structure, not policy.
- **Screening is now intrinsic** (a caller cannot forget it) and reads only the lines each patch
  section *adds*, plus whole carried files, so rotating a committed secret out is not refused.
  That needed patch parsing moved into `core/patch_parse.py`, breaking what would otherwise have
  been an import cycle (capture → secret_scan → preview → store → capture).
- Two test fixtures were wrong and the code right: re-adding a line already in the committed base
  is diff *context*, not an addition; and an ignored carried file is now excluded by default.
- `fleet/test_git_client.py` failed only while five test processes ran concurrently; alone it
  passed, and the full suite run alone passed **25/25 on Windows**. Hygiene scan of the new
  untracked files: clean.
- **Capture is still not usable**, and the capture basket still refuses. Remaining: retirement
  proof, then peer wiring.

## 2026-09-16 — Notes-only checkpoint

- Read the current notes and preserved the newer September 12 recovery work.
- Located the World Monitor and Agent Prime note locations and prepared the
  user's stop-and-restart decision there for review.
- No product code changed. No tests, fetches, pulls, commits, or pushes ran.

## 2026-09-17 — core path audit: read end to end, seven confirmed defects fixed

The user's goal: every machine shows a tray icon and dashboard answering "which repos have
uncommitted work" and "which repos are out of date". The core path had never been read end to
end. Every defect below was reproduced with synthetic data before fixing.

1. **Permanent false alarm.** Stale threshold was a fixed 120s and the peer never
   heartbeated, so every quiet machine (including your own) needed attention minutes after its
   last edit. Now: the peer re-stamps its report every `heartbeat` seconds, transports re-send
   unchanged state once per slot, and `stale_after()` = two missed deliveries on the slowest
   configured path.
2. **"Behind" was unanswerable.** Nothing fetched. Now a background `git fetch` runs every
   `fetch_minutes` (default 15, 0 = off): remote-tracking refs only, never prompts
   (`GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=never`, `credential.interactive=never`), off the
   observation loop. Fetch stamps survive later refreshes and rescans. Failures are issues.
3. **GitHub API budget.** Every tray poll (5s) and browser refresh (3s) re-read the state repo:
   2,880 calls/hour from the tray alone vs a 5,000/hour account limit. Reads are now cached per
   transport (folder 15s, repo 5 min, failed read retries after 30s).
4. **Unreadable repo reported clean.** A failing `git status` returned zero counts. Now the
   repo is omitted with a "status unreadable" issue, and a refresh keeps the last-known record.
   A repo git refuses to open (e.g. dubious ownership) says so instead of "missing origin".
5. **Settings panel lied.** It read retired v2 keys: always "no folder, no repo", Tailscale
   always on. Now reads the real transport config; adds a scheduled-fetch feature row.
6. **Packaged app never opened the dashboard.** `fleet_desktop.dashboard_url` used retired host
   keys and Tailscale. Now the loopback URL.
7. **No tray / silent failure.** `fleet setup` ran a terminal foreground peer. Now setup offers
   start-at-login and starts the tray. If the app stops unasked, the tray keeps a red icon with
   the reason and log path (`fleet.log`, written even under pythonw).

Also: a Windows watch thread that failed exited silently forever — `wait()` now raises and the
peer restarts watching with a fresh inventory; kernel event overflow (Windows and Linux) forces
an inventory; tailnet polling moved off the observation loop.

New `tests/fleet/test_core_path.py` (11 tests). One existing test encoded bug 1 ("unchanged
state is never re-sent") and was corrected. Windows suite alone: **26/26**.
Not yet done: a live run on the user's real machines.

## 2026-09-19 — Continuation preparation

- Re-read the project brief, current handoff and working notes; regenerated and read the
  repository tree map.
- The user confirmed the product direction: one family of careful Git operations, with
  terminal-first commands and an optional peer fleet service. Fleet-wide visibility and a
  safe suggestion to synchronize unsynced work are the headline outcome.
- Recorded the agreed implementation order: finish safe medium-tier recovery wiring, add
  tier-aware setup preflight, then build terminal-first fleet catch-up and later safe-to-wipe.
- Ran the complete Windows suite alone through the repository virtual environment:
  **26/26 test files passed**. No deployment or Git network/mutation operation occurred.

## 2026-09-19 — fleet setup preflight

- Added read-only `fleet preflight`, which reports whether Git, the optional GitHub and
  Tailscale tiers, and the loopback dashboard port are usable, plus any common existing
  synchronized-folder locations it can find. It creates no configuration and changes no
  repository or external service.
- Verified its command path, the fleet-app and catch-up tests, repository hygiene, and diff
  integrity on Windows. The full suite remains green at 27/27 from the preceding catch-up slice.

## 2026-09-19 — fleet catch-up, first safe group action

- Added terminal-first `fleet catchup`. It freshly, non-interactively fetches every locally
  observed checkout and prints a plan by default. `fleet catchup --apply --yes` fast-forwards
  only clean, behind-only repositories and rechecks the result; every other state remains a
  visible human decision.
- The action cannot commit, push, stash, reset, merge, rebase, prune, or recurse into
  submodules. It refuses to run beside the peer through the existing per-configuration lock.
  A fresh-fetch failure, unreadable status, dirty/untracked work, ahead-only work, divergence,
  detached HEAD, and missing upstream are all surfaced and skipped.
- Added disposable-real-Git tests covering a safe pull plus dirty/ahead/diverged refusals;
  updated the root and fleet documentation and dashboard wording to direct users to the
  terminal operation rather than imply that a dashboard button exists.
- Full Windows suite alone: **27/27 test files passed**.

## 2026-09-19 — medium recovery activated; catch-up surfaced safely

- Completed the medium-tier recovery chain: schema v5 holds a separately confirmed private
  location and local per-repository `CapturePolicy`; capture baskets now require that location;
  the peer captures selected repositories after filesystem quiet periods and peers verify visible
  bundles into independent acknowledgement records.
- Added preview, disposable restore, explicit policy, acknowledgement and retirement CLI paths.
  Retirement reconstructs the exact snapshot tree in disposable Git metadata, freshly fetches
  the upstream and retires only a byte/tree-identical remote result. `safe-to-wipe` accepts a
  dirty checkout only for an exact current snapshot acknowledged by another peer and never for
  unpushed commits.
- Added an authenticated, opt-in Tailscale session join to setup, and a local dashboard
  catch-up preview that invokes the terminal planner's fresh-fetch policy. Applying a pull stays
  `fleet catchup --apply --yes` while the peer is stopped.
- Added terminal-first `fleet audit`, a read-only fleet-scale report of missing origins/upstreams,
  plain-HTTP origins, detached heads, local-only commits, behind state and tracked changes.
- Added `fleet materialize`: a reviewed clone-only plan for the locally observed working set,
  laid out by remote host/owner/repository and protected by `--apply --yes`; existing destination
  directories are never replaced or updated. It validates portable path components and rejects
  destinations that would escape the selected library through an existing symlink.
- Added explicit local `fleet live-buffers` inspection of existing VS Code backup metadata. It is
  root-confined, bounded, content-free in output and does not transmit or continuously watch
  buffers; cross-machine live-buffer recovery remains a separate privacy decision.
- Corrected the PyInstaller recipe's source-root paths and declared every lazily imported action,
  recovery and live-buffer module. Added a read-only `packaging/release_check.py` gate for the
  version/tag, clean tree, desktop recipe/assets and local PyInstaller prerequisite; it correctly
  reports that tagging, publication and a disposable build environment are still operator work.
- Corrected the remaining undefined PyInstaller `tool` path: the recipe now puts both the
  repository root (for `shared/`) and the Sync Suggester root on the analysis path. The recipe
  test asserts that exact boundary so a syntactically valid but unbuildable spec cannot recur.
- Ran the real Windows PyInstaller build under Python 3.14.2 and corrected `SPECPATH` handling:
  it already names the recipe directory, so taking its parent chose `app/fleet_desktop.py` from
  the repository root. The test now pins the correct spec-directory interpretation.
- Corrected the release gate to detect PyInstaller as an import in its own build interpreter,
  matching the documented `python -m PyInstaller` invocation instead of relying on ambient PATH.
- Added a tray catch-up preview menu entry. It invokes the peer's same fresh-fetch plan on a
  worker and shows only the shared plan summary, so it cannot create a tray-specific Git policy
  or block the Windows message loop.
- The final Windows regression run passed all 34 test files. No live machine, remote, commit or
  push was changed.

Append-only record of **completed** work. Newest first. Items that graduate from
[`working-notes.md`](working-notes.md) land here with an absolute date.

## 2026-09-19 (later) — records reconciled with the shipped tree

Audit of the preceding checkpoint: the code is real and green (**34/34 on Windows, re-verified
here**), and the working notes and work log had been tended. The gap was the durable record.

- **Updated the project brief** (`.agents/README.md`), which had not been touched since
  2026-09-11 and described a smaller tool than exists. Added the eight `core/` recovery modules,
  the `fleet` command surface (`preflight`, `audit`, `catchup`, `materialize`, `live-buffers`,
  `safe-to-wipe`), and the not-encrypted decision.
- **Corrected two now-false invariants in the brief.** It claimed the tool never touches an
  observed repository and never clones. `catchup --apply` and `materialize --apply` do both. The
  rules are restated as the boundary that actually holds: observation is read-only, mutation is a
  separate terminal command that refuses to run beside a live peer and that no dashboard, tray, or
  schedule can reach.
- **Corrected `HANDOFF.md`**: it said the recovery work was uncommitted (it is committed, tree
  clean) and gave three different suite counts (27/27, 26/26, 26/26). All now 34/34.
- Reordered the 2026-09-16 entry below 2026-09-17 in this newest-first file, and closed the stale
  "peer wiring and retirement proof remain" bullet in the working notes, which the same commit had
  already contradicted 200 lines above.
- Documentation only. No product code, test, remote, or configuration changed. Repository hygiene
  gate passes over 139 tracked files.

## 2026-09-20 — the "read-only" rule was never a rule; brief realigned to the product goal

The user challenged the claim that Sync Suggester "never pulls, pushes, commits, stashes, or
otherwise touches an observed repository." It is a tool for performing Git operations across many
repositories; the claim could not be true and should never have been an invariant.

**Archaeology.** Both the brief's "never touches an observed repository" and the root README's
"never mutates a repository — including cloning" were written on **2026-09-03**, in
`feat(sync-suggester): complete the first vertical slice`. They accurately described that slice,
which only observed and printed advice — the name *suggester* is from the same era. On the **same
day**, `new-tool-sync-suggester.md` recorded the opposite as the goal: "Convergence is the
product, not just observation." A temporary implementation scope was written into the primary
brief as a permanent safety principle, where it outranked the recorded product goal for 17 days.
On 2026-09-19 a session noticed the conflict and bolted an "Amended:" exception onto the rule
rather than deleting it, which made the document worse.

**Resolution — one principle, replacing the false one.** It is the family model the archive
updater already follows, correctly scoped:

1. **Watching never changes anything.** No mutation may be a side effect of observation or of
   time passing — not from the peer loop, watcher, tray, dashboard, or scheduled fetch. A daemon
   that silently pulls is the real catastrophe the old rule was groping at.
2. **Every mutation is a command the user invoked**, planned, shown and confirmed:
   detect → plan → approve → execute → review.

**Changes.** Added a "What this is for" section at the top of the brief stating the product goal
in the user's own terms, with an explicit precedence rule: if a later rule contradicts it, the
goal wins and the rule is the defect. Replaced the false invariant in the brief and the root
README; left a dated correction note at the Sync Suggester section so the framing is not restored
by a future session. Corrected consequential wording (`sync_suggester.py` is no longer described
as "the read-only CLI"; the fetch section no longer justifies itself as "what keeps a read-only
tool read-only"; live smoke-testing guidance now distinguishes observation commands from mutating
ones). Documentation only; no code changed; hygiene gate passes over 139 tracked files.

**Lesson worth keeping:** the brief had no statement of what the project is *for*, so
implementation detail had nothing to outrank it. Scope descriptions must not be written as
principles, and a document that outranks the goal must state the goal.

## 2026-09-21 — migration phase 1: `Basic/` and `_os/`

**Folder map reviewed first (2026-09-20).** The user revised the target before any file moved:
a root `_os/` folder beneath every layer, present for all three OSes out of the box; `Basic/`
flat (no `git/` subfolder); `App/tray.py` flat; `providers/` → `_providers/`; the archive registry
to the per-user state folder as `gitspecops_managed_archives.json`; merges (`_run`, `_confirm`,
launcher writing) and splits (renderers, `archive_manager`, the version query, `atomic_write_bytes`).
Recorded under "Revisions" in `knowledge/architecture-layers.md`. The four regenerable untracked
folders (`build/`, `dist/`, the egg-info, root `__pycache__/`) went to the Recycle Bin;
`gitArchiveUpdater/` was kept because the scheduled task points into it.

**Landed.** `shared/{console,git_facts,remote_identity,repo_discovery}.py` moved (with `git mv`) to
`Basic/{_console,_facts,_identity,_discovery}.py`. New: `Basic/_run.py` (the one subprocess
wrapper; `run`/`run_git` return flagged results, `run_checked` raises `CommandFailed`/
`CommandTimeout`), `_confirm.py` (the duplicator's prompt machinery plus `confirm_typed`; the
archive tools' `input()` calls and `archive_manager`'s duplicate `prompt_input` now use it),
`_files.py` (`atomic_write_bytes`, out of `folder_transport`), `_paths.py` (`config_home`,
`sync_home`; replaces `config.default_config_dir`), and the commands `status.py`/`discover.py`,
which replace the two useful standalone CLIs that plumbing modules no longer carry. `_os/` has
`current.py`, `_posix.py`, and `paths` + `process` for windows/linux/macos. `gh_common.py` lost
`run_command`, `CommandTimeout`, the prompt machinery and its import-time stream reconfigure;
`shared/gh_cli.run_gh` now runs on `_run`. New tests: `basic/test_run`, `basic/test_confirm`,
`basic/test_identity` (the old module self-test, which only ran by hand), `os/test_os_parity`.

**Found and fixed: a timeout that did not bound anything, on Windows.** The first suite run hung
for over ten minutes on the new timeout test. The venv's `python.exe` — like Git for Windows'
`cmd\git.exe` — is a launcher whose child is the real program. `subprocess.run` on timeout kills
only the direct child; the grandchild keeps the output pipe open, and the read that follows the
kill waits for it. **Both earlier wrappers had this**, so a hung `git fetch` could hang a run
despite its timeout. Why it hid: nothing ever tested a timeout against a real launcher-style
child, and real hangs are rare and look like slow networks. Fix: `_run` uses `Popen` and on
timeout (or Ctrl+C) calls `_os.current.process.kill_tree` — `taskkill /T /F` on Windows, a
process group (`start_new_session` + `killpg`) on POSIX. `test_run` now asserts a timed-out
60-second sleep returns in well under 20 seconds (3.1 s measured).

**Deliberate behavior changes.** Every git call now gets `GIT_TERMINAL_PROMPT=0` (only the
duplicator's did); prior auth is the rule, so a credential prompt failing fast is correct. A
missing binary is exit 127 and an unstartable one 126 (previously 1 from `run_git`); callers test
only for nonzero. The archive tools' yes/no prompts re-ask on garbage instead of treating it as
"no", and end-of-input is a clean stop rather than an `EOFError` traceback. macOS keeps
`~/.config` as its config base, as before; moving to `~/Library/Application Support` waits for a
real Mac.

**Validation (Windows, this checkout, suite alone):** 38/38 test files; hygiene gate green over
the tracked tree including the new files; every entry point answers `--help` when run by path
from a foreign directory; `Basic/status.py` and `Basic/discover.py` run by path.

## 2026-09-21 — migration phase 2: `Basic/_providers/` and the import-direction test

**Landed.** `shared/providers.py` → `Basic/_providers/_registry.py` and
`git-archive-updater/provider_github.py` → `Basic/_providers/github.py` (both `git mv`).
`github.py` now holds **every `gh` invocation**: `run_gh`/`GhError` (ex `shared/gh_cli.py`,
deleted), `GitHubProvider`, and the host operations the duplicator used to run itself (inventory,
LFS probe, namespaces, create/ensure, duplicate comparison) plus the version check's release query
(`latest_release_tag`). They return data or raise; the duplicator's `gh_remote.py` keeps only its
print-and-stop prerequisite checks and the pooled LFS progress. `remote_provider.py` and Sync
Suggester's `_register_providers()` are deleted.

**How registration works now.** `github.py` calls `register_provider()` at import; the registry
imports its built-in provider modules itself (a static import inside `_load_built_in_providers`,
run on the first lookup). No caller has to remember anything, and nothing is loaded dynamically.
Adding a host is one module plus one import line.

**Why this mattered beyond tidiness.** The old arrangement failed silently: a provider existed
only if some caller had imported the archive tool's facade first; forgetting meant "no
providers", which degrades every lookup to host-agnostic behavior without an error. Sync
Suggester's workaround reached the facade by **inserting `git-archive-updater/` into its own
`sys.path` at runtime** — the cross-tool module-shadowing hazard the brief warns about. A fresh
interpreter now resolves github.com with no setup (`tests/basic/test_providers.py`).

**`gh` never prompts.** `run_gh` sets `GH_PROMPT_DISABLED=1`, the `gh` twin of
`GIT_TERMINAL_PROMPT=0`. Every existing call passes complete flags, so nothing relied on a prompt.

**Import-direction test** (`tests/repo/test_import_direction.py`): parses every file in the
stack (function-level imports included) and enforces `_os → Basic → Special → Elaborate → App`;
no sideways command-to-command import within a layer; nothing outside the stack (tool folders,
`shared/`, third-party); no relative imports. Verified it fails on a planted file exhibiting each
of the five violations, then removed the probe.

**Still speaking raw `gh`:** `repo_transport` (Contents API) and `fleet_app` call `run_gh` with
their own arguments; tracked in working notes for phase 3.

**Validation (Windows, suite alone):** 40/40 test files; hygiene green; entry points answer
`--help` by path from a foreign directory.

## 2026-09-22 — migration phase 3a–3b: `Special/`, `Basic/` git commands, `archive_manage`

**3a (two commits).** The archive tools moved to `Special/archive_update.py` and
`Special/archive_sync.py`; `archive_diff.py` became `Special/_archive_plan.py` and absorbed
`git_inspect`'s eligibility check. **Nothing in `archive_diff` was generic** — the HANDOFF
expected a split into `Basic/_facts`, but `RepoRef`/`normalize_owner_name` had already moved to
`Basic/_identity`, and everything left (drift buckets, publish eligibility, approved-remote
checks) is archive judgment, so it all went to `_archive_plan`. New `Basic/` commands, each one
git operation: `fetch`, `pull` (ff-only), `push` (bare, no force option exists), `clone` (never
over an existing folder), pinned by `tests/basic/test_git_ops.py` on disposable repositories. The
org duplicator became `Special/duplicate_org/`; `gh_common.py` dissolved into `Basic/_console`,
`Basic/_confirm`, `_tracking` and `_operations`; its gitignored `runs/` moved with it.

**3b.** `archive_manager.py` → `Elaborate/archive_manage.py`, split three ways: the registry is
`Elaborate/_archive_registry.py`; launcher writing is `_os/*/launcher.py`; scheduling is
`_os/*/schedule.py` (Windows `schtasks`; Linux/macOS report unsupported, as before). A refresh
now calls `archive_sync.main(argv)` **in-process** instead of spawning a second Python — the
layer rule, and one fewer place where interpreter discovery can differ by OS.

**State left the checkout.** The registry is `<per-user config>/gitspecops/
gitspecops_managed_archives.json` (user's choice of name, lowercased by the naming rule); the log
is `archive_manage.log`; the refresh-all launcher `refresh_managed_archives.{bat,ps1|sh}` is
written there too, **so the scheduled task points at a path that no future code move can break**
— the failure that broke the old task. `GITSPECOPS_HOME` overrides the folder for tests.
The three registered archives were copied into it unchanged (verified identical) and the old log
appended; the emptied `git-archive-updater/` went to the Recycle Bin.

**Validated beyond the suite:** both generated launchers were *executed* through `cmd /c` against
a disposable archive whose path contains a space, and each fast-forwarded a real clone.
`tests/elaborate/test_archive_manage.py` pins that automated runs only ever carry `--update` or
`--sync`, never `--publish`/`--reconcile`/`--rename-folders`. Suite 43/43 on Windows, alone.

**Waiting on the user:** replace the scheduled task (it still points at the stale
`gitArchiveUpdater\` launcher, broken since before this work) and reinstall the three archives'
`update_archive` launchers, which still call the pre-migration path. Then delete
`gitArchiveUpdater/`.

## 2026-10-05 — library inventory: export and restore (`Special/`)

Prompted by a real failure: a folder-name map cannot clone a fleet, and the fleet manifests
cannot either, by design (salted ids, no names or URLs). New, in `Special/`:
`_inventory.py` (collection + pure restore planner), `inventory_export.py` (`EFFECT = "none"`),
`inventory_restore.py` (`EFFECT = "local"`, clone-only, plan first, typed `CLONE`),
pinned by `tests/special/test_inventory.py` on disposable repositories.

- **The recorded remote URL is the source of truth for cloning**; `host/owner/name` is derived
  from it for layout and identity. Every remote is recorded, not just origin, and `--layout
  preserve` (recorded relative paths) or `canonical` (`host/owner/name`) is chosen at restore.
- **Labelled roots, no drive letters.** `--root label=path` on export, `--map label=dest` on
  restore, so each root can land on any drive or folder. `source_path` is recorded for the human
  only; restore never reads it.
- **Nothing is dropped.** Repositories with no remote, unpushed commits, uncommitted work or
  stashes are recorded and flagged (`no-remote`, `unpushed-commits`, `uncommitted-work`,
  `stashed`, ...), and restore names, per row, what a clone cannot bring back. A repository with
  no remote still carries readme, project-file metadata, `.git/description`, and candidate origin
  URLs found in them; restore uses a candidate only with `--use-candidates`, since a README link
  is a lead and not evidence.
- **Credentials never enter the file** (http(s) userinfo is stripped and flagged). Submodules and
  linked worktrees are recorded and skipped on restore; nesting is recorded.
- **Why it is separate from `materialize`:** `materialize` plans from a live local scan and
  always lays out `host/owner/name`; this goes through a portable file. Phase 3c should rebuild
  `materialize` on `_inventory.plan_restore` rather than keep two clone planners.
- Default output is the gitignored `.agents/output/`: the file names every private repository.
- **Ask for a file or folder only in a command, never in a function.** `Basic/_pick.py`
  (`pick_open_file`, `pick_save_file`, `pick_directory`) opens a native tkinter dialog when one is
  safe and asks in the terminal otherwise; both commands use it only when the path was not given
  as a flag, and `--answers` / `--no-prompt` / `GITSPECOPS_NO_GUI=1` always keep it in the
  terminal. Higher layers call the importable functions with explicit paths, so an unattended run
  can never meet a dialog.
- **Cause worth keeping: on Windows `isatty()` is True for the `NUL` device**, which is what a
  scheduled or detached run is given, so "is stdin a terminal" would have let a hidden dialog
  open. The test found it only because it ran the real commands with stdin on `NUL`.
  `process.stdin_is_interactive()` is now an `_os/` component (Windows asks for a real console
  mode; POSIX uses `isatty`), with the parity test covering all three OSes.
- **Scattered repositories.** `--root` repeats (bare paths are auto-labelled `projects`,
  `projects-2`, ...; the same folder twice counts once), `--repo PATH` records a single repository
  under the reserved label `loose` with its original location, a root that is itself a repository
  is kept, and a repository reachable two ways is recorded once. Restore takes one `--map` per
  label, or `--dest` for all, or asks per label; `--dest DIR --layout canonical` is the
  one-tidy-tree answer for a haphazard library, and `preserve` into one folder reports collisions.

## 2026-10-19 13:00 — product direction discussion recorded for handoff (no code changed)

A design discussion across three sessions (2026-10-17 to 10-19) re-anchored the product on the
user's vision: Sync Suggester replaces desktop Git clients for daily use, and the user sees at a
glance what is out of sync on every machine. Recorded in `WORKING-NOTES.md` (top section) and
the head of `HANDOFF.md`: decisions taken (a tray on all three OSes; dependencies allowed for the
optional App; one front-door setup; Dropbox, Syncthing and the GitHub state repo to be tested;
publish on sleep/shutdown; a second user's own fleet), recommendations awaiting a yes (one app
named gitSpecOps; rewriting the effect rule, which contradicts the vision and is already broken
by the archive scheduled task; schema v4 with names; an auto-update basket), facts verified by
reading the code (Windows-only tray; macOS lacks tray, file events and scheduler; no by-machine
view; `run_setup` asks nothing; Basic lacks diff/commit/log/branch/stash), a tray-toolkit spike
plan, and a proposed path that begins with auditing the tests. Also recorded: a side-quest idea
for a report-only self-doxxing scan across the user's own fleet.

Lesson worth keeping: a session repeated this file's test pass counts as fact without opening a
test. Pass counts here are claims by the sessions that wrote the code; no audit of what the tests
assert has been done.

## 2026-10-19 12:00 - user (Claude Opus 5.5) - test audit; safe-to-wipe and duplicator fixes; effect rule rewritten

**Audit.** First read of what every test asserts, alongside its source; each confirmed defect was
reproduced on disposable repositories before being written down. Full record:
`knowledge/test-suite-audit.md`. Suite run on Windows 11 / Python 3.14: 44/44 files before the
fixes, 46/46 after (two new files). Not yet run on Linux or macOS.

**Fixed, each pinned by a test that fails on the old code:**

- `fleet safe-to-wipe` printed SAFE over the only copy of work (no remote, side-branch commits,
  a stash, a remote not named `origin`). Cause: it trusted the observer's inventory, which drops
  what it cannot name, and judged only the current branch. It and `fleet audit` now walk the
  roots themselves (`fleet_actions.every_repository`).
- The duplicator deleted a non-repository folder sharing a repository's name (any `config`
  entry passed as "a repository"), could delete its own parent folder, and on Windows could not
  remove a real clone at all (read-only git objects). Existing folders are now refused, never
  deleted.
- `Basic/pull.py` read git's English wording; it now compares HEAD.

**Why it hid:** the unit tests fed the verdict functions hand-picked inputs; the real commands
fed them the observer's inventory. A unit test passing over a broken integration — the pattern
to hunt for next.

**Effect rule rewritten with the user** (three rules in the brief; `architecture-layers.md`):
background observes, or acts only under a standing consent the user configured, within the safe
class; foreground runs the same confirmed command. Also decided: mailboxes; CLI-first via flag
strings and settings, not blanket JSON; the dashboard stays with Sync Suggester; `App/` is the
tray; scheduling stays below `App/`; skins deferred; KDE on the Debian box.

## 2026-10-19 13:03 - user (Claude Opus 5.5) - fleet map sees at-risk work; Security/ tools; history rewrite prepared

- **Observer (manifest v4):** no-remote repositories and side-branch commits now reach the fleet
  map; checkouts sharing an identity are merged so no work hides (see `test-suite-audit.md`).
- **Duplicator:** an empty destination folder is used, a non-empty one refused (user's
  decision); a failed download leaves no half-clone. Default state repo: `gitspecops-state`.
- **`Security/`** (new, between Special and Elaborate): shared detection rules, run-time
  identity seeds (git/gh identity, host, home folder, tailnet names and addresses, GitHub orgs
  online, and a private never-publish list in the per-user folder), `scan_tree`,
  `scan_history`, `rewrite_history` (plan / apply in a bare clone / verify; the forced push is
  the person's). Re-attributes only the runner's own identities; removes generated caches
  rather than editing them; reports signed commits and unreadable binaries — points raised by
  an outside review of the same problem across the user's other repositories.
- **Live leak fixed in place:** two private organization names were in this file's 2026-09
  entry, in the current public tree, invisible to the offline guard (org names need the network).
  They were replaced in that entry directly — a deliberate exception to "never edit a past
  entry", because the alternative was publishing them again with every commit. The org names
  are now on the never-publish list, so the offline hygiene test catches them from here on.
- **History rewrite prepared, not applied:** the plan lives outside the repository. Applying it
  and the forced push are the user's.

## 2026-10-19 13:46 - user (Claude Opus 5.5) - Security output in the repo's ignored folder; handoff

- **Output location (user's decision):** every Security command now writes to this checkout's
  git-ignored `.agents/output/security/<repo>/`, whatever it scanned, so the user and the agents
  in neighbouring windows read results in place; the per-user folder is the fallback. A plan may
  sit inside the scanned repository only where git ignores it. (Correction to the previous
  entry: plans no longer live outside the repository by default.)
- **Reports:** masked on screen, full and unmasked in the report file, which now lists *every*
  author/committer identity found (the user asked whether it reports the emails it finds — it
  previously listed only the problem ones). The scanned repository's own owner name is public
  identity and no longer reported.
- **`Security/scan_secrets.py`:** runs gitleaks when installed; optional, to be offered by the
  front-door setup like the tray. Says how to install it otherwise.
- **The user's first attempt to apply** ran from the home folder, so the scripts were not found
  and nothing happened — instructions now always say "from the repository folder". The rewrite
  is still waiting; a fresh plan must be made after this handoff commit (a plan covers only the
  commits that existed when it was made). Earlier plan folders in the per-user folder and the
  ignored output folder are stale.
- **Handoff pushed** (normal push of 14 commits, checked first: the files pass the hygiene test
  and the commit messages carry no personal data). Next: the user applies the rewrite; then the
  Sb4ssport-Alpha repositories, before they go public.

## 2026-10-19 13:55 - user (Claude Opus 5.5) - first rewrite caught by its own verification

The user ran `apply` on this repository. `verify` refused it: "refs/heads/main: the current files
changed, but they held no planned value". Nothing was pushed. **Cause:** git filter-repo has no
comment syntax in its `--replace-text` file — every line is a rule, and a line without `==>`
replaces that literal text with `***REMOVED***`. The planner wrote a two-line `#` header and a
`# <kind>` label above each rule, so filter-repo rewrote the one file that quotes the header: the
planner's own source, `Security/rewrite_history.py` (current and old versions). **Fix:** the rules
file holds rules only (labels stay in `expected.json`); the plan records every tip file, so a
failed comparison names the files that changed; a test asserts every rule line is a rule. Why it
hid: the gated end-to-end test (which runs filter-repo) had never been run, and the only
non-rule lines in the test fixture's rules file never appeared in its content. The spoiled
clone stays in the ignored output folder; a fresh plan replaces it.

## 2026-10-19 14:21 - user (Claude Opus 5.5) - history rewrite applied and pushed; checkout moved

The user applied the fresh plan (verification: 82 commits, no planned value, no old identity,
current files byte-identical) and ran the printed forced push; GitHub `main` went from the old
history to the rewritten one. The agent then confirmed this checkout had no uncommitted changes
and the same tree id as the new `origin/main`, and moved it with `git reset --keep origin/main`
(no file changed). `scan_history` over what GitHub now serves: no personal identity on any
commit, no tailnet address, machine name, local path or private org name in any file version or
message; only `Sb4ssport-Alpha`, kept on purpose.

The tool's printed next steps had said "re-clone", contradicting the in-place move the agent
had given in chat. Both were safe; the printed text was the cautious general case. It now gives
the in-place `fetch` + `reset --keep` for a clean, verified checkout and keeps "re-clone" for
anything with uncommitted or later work.

## 2026-10-19 16:15 - user (Claude Opus 5.5) - Security tools ready for Sb4ssport-Alpha; follow, relink, scan_folder; safeguards

**Safeguards.** GitHub ruleset on this repository's `main` (no deletion, no force push, linear
history), created 15:21 at the user's request: a clone made before the rewrite can no longer
merge the old history back in and push it. Secret scanning and push protection were already on.
Tested on a stale copy: `git pull` there refuses in every mode (the histories share no commit),
so the earlier note "a pull merges it back" was wrong; corrected.

**New:** `Security/scan_folder.py` (every repository under a folder, one table, `--plan` writes
every plan); `rewrite_history.py follow` (moves a pre-rewrite clone with `reset --keep` only after
proving every commit on the branch has a rewritten counterpart -- same author and committer
times -- and no tracked file is changed; names stale branches and tags); `rewrite_history.py
relink` (commit ids quoted in files, from filter-repo's commit maps, several plans at once since
repositories quote each other; edits only, never commits); `apply`/`verify` take many plans with
one confirmation; `--remove-path`. `Security/_contents.py` opens archives (zip and its Office /
EPUB / jar / wheel kin, tar.*, gz/bz2/xz, nested once; 7z/rar reported as not inspected; bounded
against bombs) and reads image metadata (PNG text chunks, EXIF text incl. Windows' UTF-16 tags,
XMP, and whether EXIF holds a GPS position). `Basic/_facts.shares_history`; the Sync Suggester
observer reports "upstream history was rewritten; move this clone with ... follow" instead of
plain divergence.

**Defects found and fixed on the way (all would have hit the Alpha rewrite):**

- A placeholder with backslashes (`C:\Users\<you>`) is a `re.sub` template: filter-repo crashed
  with "bad escape \U". Found by running the gated end-to-end test, which had last been skipped.
- `--replace-text` never touches file *names*: a value in a path survived and verification
  refused. Now a `--filename-callback` applies the same rules file (no value on a command line).
- The configured address is the noreply one, so an old personal address in history was known to
  no seed: commits under a second name were left as someone else's (86 in one repository), and
  file contents were never searched for it. An address any of your identities used is now yours
  under every name, and is searched for.
- Verification skipped "nothing else changed" entirely once any path was removed. Now per file:
  a current file may differ only if it held a planned value, was removed, or was renamed by a rule.
- Values filter-repo cannot reach (binary files: it skips any blob with a NUL in its first 8 KiB;
  archive members) are named at plan time with the fix (`--remove-path`), instead of surfacing
  as a refused verification.
- `follow` first recognised a rewritten commit by its author and committer times; commits made
  in the same second share both, so a never-pushed commit could pass as published and be hidden
  by the move (the full suite caught it; the focused run was too slow to). It now proves what
  the remote held from the remote-tracking reflog files (old and new value of every line -- a
  fresh clone's cloned-at value survives only there), and refuses when there is no record.
- `--mine` re-attributed only identities already counted as personal data, so another account's
  *noreply* address could not be claimed; now it can (the user's decision for Orbital-Workshop).
- False secrets: 253 `uv.lock` checksums, a download manifest's `"sha256"`, bitmap rows in a game
  file, a key *header* in a scanner's own test, a test fixture assigning "sample-value" as a
  password, `/home/linuxbrew`. The 64-hex rule now looks at context and digit variety; a key
  block needs a key body.

**Alpha status.** Scanned all ten (122 commits including Authority's 15:37 checkpoints): one
personal address on every repository's older commits; in Orbital-Workshop also user paths,
home-folder names and bytecode (removed), and six IOCCC archives that are clean of personal data
once the contest's own magic constant is kept. Rehearsal on Orbital-Workshop: planned, applied in
the mirror, verified clean (74 commits). Real plans wait until the Authority agent stops
committing. The plumbing moved to `Security/_rewrite.py` and `Security/_report.py` (commands
may not import sibling commands). Tests: `tests/security/test_security.py` 81 checks, gated
rewrite included, all pass; full suite 48/48 files on Windows (before the last `--mine` fix,
which the security, hygiene and import-direction tests then re-ran green).

## 2026-10-19 17:20 - user (Claude Opus 5.5) - Sb4ssport-Alpha rewritten and published; follow sweeps folders

- **The run:** the user applied all ten plans (each verified clean: 122 commits, no planned
  value, no old identity, current files byte-identical but for planned changes), force-pushed
  all ten with one PowerShell loop, and ran `finish` (all ten checkouts moved; 64 quoted ids
  relinked). An independent rescan of the rewritten copies with every seed -- including the old
  account name, added to the private never-publish list after planning -- found nothing
  personal; all 244 author/committer fields are the noreply identity (or GitHub's own, on 12
  web commits). The agent checked each relinked id names the same commit as before (four
  distinct: three from Structural-Engineering, one from the site repo, quoted across repos),
  ran Structural-Engineering's tests (11 pass, its fixtures quote one of those ids), then
  committed exactly the relinked files in nine repos and pushed them normally.
- **The user asked why a step remained after `finish`:** nothing had failed; the edits were
  left uncommitted by design. `finish` now commits exactly the files it relinked and pushes them
  (`--no-commit` keeps the old behaviour). The user declined rulesets on the Alpha repos.
- **`follow` sweeps folders:** `follow PATH... [--match TEXT] [--depth N]` assesses every
  checkout found (fetching each), lists the ones it refuses with the reason, asks once, then
  moves the rest. For another machine, one line from a fresh temporary clone, so it works
  however stale that machine's own gitSpecOps is. Smoke-tested here over the whole library:
  11 matching checkouts, all current, nothing moved. Tests: finish commits and pushes only its
  own files (an untracked file stays untracked); a sweep moves a stale clone and leaves current
  ones; a match that names nothing changes nothing. Full suite 48/48 on Windows.

## 2026-10-19 19:45 - user (Claude Opus 5.5) - handoff: other machines' note; Security design unsettled

- **A plain-git note for the other machines,** at the user's request (the temporary-clone
  `follow` line "did not jive"): fetch, "same" if the checkout shares history with
  `origin/main`, else count unpushed commits (against `origin/main` and `origin/main@{1}`) and
  edited tracked files, and `reset --keep` only when both are zero. Tested in PowerShell and sh
  on scratch fixtures in every state, twice each. A first version wrongly held an
  already-current fresh clone (no reflog); fixed with the shared-history check first.
- **The user's feedback on the tools:** no stop between rewriting and pushing (the agent's
  PowerShell loop made that worse); big operations must stop on a typed word and say what to
  inspect; the never-publish list must be shown when loaded and before it is first written.
- **The Security structure was discussed and not settled.** The agent proposed three shapes in
  a row, the last against the architecture (security plumbing in `Basic/`). The user's
  directions are recorded in WORKING-NOTES ("HANDOFF", 19:45). No code changed after 17:20.

## 2026-10-20 18:12 - user (Claude Opus 5.5) - Security rebuild designed; reset_keep; shared/ gone

- **The Security structure is settled** after a discussion with the user:
  [`knowledge/security-design.md`](knowledge/security-design.md). The first `Security/` had the
  wrong shape: it was ranked as a layer, bypassed Basic for its own commits and pushes (under
  `EFFECT = "local"`), asked y/N, and put six verbs in `rewrite_history.py` over an 806-line
  `_rewrite.py` whose rule semantics were written four times (the source of both 2026-10-19
  rewrite bugs). Decided: placement A (no Security layer; `Special/security/`,
  `Elaborate/security/clean_history`, general rewrite machinery in plain `Special/`); rebuild
  rather than move, with the old two files deleted at the cut-over (no tag, no `_archive/`);
  typed `REWRITE` never skippable; typed review stop; `follow_rewrite` presents move now /
  later / by hand. Phased plan in the design document.
- **`Basic/reset_keep.py`** (phase 1 begun): `git reset --keep` on the checked-out branch;
  refuses a detached HEAD, an unknown target, and any move that would overwrite an edit; no
  other reset mode exists in its code (pinned). Six cases in `tests/basic/test_git_ops.py`.
- **`shared/` deleted by the user.** The version number is now written once, in
  `pyproject.toml`, and read by `git-sync-suggester/core/version.py` (with the update check);
  the PyInstaller recipe bundles `pyproject.toml`; the release gate reads it too; the drift test
  became a single-source test plus "unreadable is unknown, not a crash". The planned
  `App/version.py` was wrong: the display contract (Elaborate) needs the number.
- Full suite 48/48 on Windows.

## 2026-10-20 18:22 - user (Claude Opus 5.5) - Security rebuild phase 1: Basic

- **`Basic/commit.py`** -- commits exactly the named paths (`add` then `commit --only`), so
  other staged changes stay staged; refuses no paths, an empty message, a detached HEAD;
  "nothing to commit" when the paths are unchanged. No `-a`, `--amend`, empty commit or hook
  skipping exists in its code (pinned by a test).
- **`Basic/_run.stream()`** -- the wrapper's streaming face. The old history reader called
  `subprocess.Popen` directly, so it had none of the wrapper's care (no process-tree kill on
  Windows, no no-prompt environment). Feeds stdin from a thread (2 MB each way tested), a
  deadline that kills the tree, `CommandFailed` on a nonzero exit, `stop()` and an abandoned
  generator both end the child.
- **`Basic/_objects.py`** -- `file_versions` (every path of every file version, from
  `log --raw -m --root`), `files_at`, `commits` (raw objects: signature present or not, no
  mailmap, no signing tool, a message's own indentation kept), `read_blobs` (streamed; a missing
  id is reported as None; a short answer raises). **Finding:** the old reader took paths from
  `rev-list --objects`, which names each object once -- a file whose content matched another
  file's was never seen under its own name, so a value in that name could not be found. Checked
  on a scratch repository; also checked that the old `%an/%ae` reads were *not* mailmapped.
- **`Basic/_facts`** -- `ref_snapshot` (raises; tags record their own object and the commit),
  `remote_refs` (`ls-remote --refs`; None when unreachable), `would_track` (False only on
  positive evidence), `identity_settings` (value, scope, origin) and `next_commit_identity`.
- Tests: `tests/basic/test_objects.py` (new, a repository built with every case), commit cases
  in `test_git_ops.py`, stream cases in `test_run.py`. Two test-side Windows traps on the way,
  both text-mode pipes writing `\r\n`. A large shell heredoc was blocked by the user's guard
  hook; edits went through the edit tool instead.

## 2026-10-21 12:40 - user (Claude Opus 5.5) - manifest v5: names by default; back to the product

- **Direction (user):** Security parked after its phase 1; back to the product. Order: v5, the
  KDE tray and macOS menu bar (then the first real fleet run), dashboard group actions (fetch
  group/all, ff-pull group/all), phase 3c, remote-everything on demand. Recorded in
  WORKING-NOTES ("2026-10-21 HANDOFF").
- **Manifest v5** (decided 2026-10-19). Records may carry `name` (`{host, owner, name}`),
  `branch` and `head`; the envelope's `carries_names` says so and validation refuses them in a
  manifest that says otherwise. `build_manifest` strips them unless `carries_names=True` (the
  code defaults off; the setting defaults on). Fleet config `share_names` (default true),
  `peer --withhold-names`, and a setup question naming the synced-folder caveat; `describe()`
  prints the choice. Off means off everywhere, the live tier included; the machine's own
  dashboard still names its own repositories. Checkouts that disagree on branch or head publish
  None. v1-v4 manifests are refused with "update it and let that machine publish again".
- **Readers:** a carried name is used where this machine knows none, gathered from every
  manifest *before* rows are built -- otherwise a names-off machine read last would have
  replaced another machine's real name with a placeholder. The detail panel shows each
  machine's branch and short commit ("Not shared" when withheld); the display contract gains
  `facts.branch` / `facts.head` (additive).
- Setup's old text ("identities ... are salted digests") would have become false; rewritten.
  The legacy `check`/`watch` path publishes names-free v5 until phase 3c removes it.
- **Tests:** schema, names-only-when-carried, malformed names refused, the no-remote repository
  named, branch and head carried, paths never; on a machine holding none of the repositories,
  names arrive whatever the reading order; names off leaves nothing named by any route; setup's
  new question. One existing at-risk check had begun passing for the wrong reason (raw records
  now carry names, so validation refused them for that) -- it now tests the published record.
- Full suite 49/49 on Windows; one run before it lost `test_git_client` to a 3 s loopback
  timeout (passed alone 5x; noted as a watch item).

## 2026-10-22 10:00 - user (Claude Opus 5.5) - decisions: remote commands, Qt, the owner's leak rulings

No code changed; decisions recorded where they govern.

- **The effect rule is amended** (brief, "What this is for", rule 2; architecture "Remotely
  attended requests"): a person may command another of their machines. B produces the exact
  plan, a person at A (alone or AI-assisted) approves it with a typed word, the request is bound
  to the plan, B re-checks and acts or refuses. B needs no person or AI. Over the fleet's peer
  protocol with fixed verbs, not SSH (a whole shell, per-OS quoting, and a credential change
  gitSpecOps must not make). Forced / reset / rebase / merge / delete are not verbs at all.
- **The App is Qt via PySide6** (LGPLv3), App only; operations stay standard-library Python. A
  trial (tray + window over the display contract) here and on the Debian 13 KDE box first.
- **The owner's leak rulings** (from cleaning another public repository with the old tools):
  login safe everywhere, real email and home-folder name are leaks, other local paths quiet,
  leak-describing text near a commit id is a leak (this repository checked: none). A safe list
  and `--safe` requested; `scan_tree` and `scan_history` disagree on the owner's login (257 vs
  0 findings in one repository). Recorded in `knowledge/security-design.md`; they replace the
  never / watch levels proposal.

## 2026-10-23 10:15 - user (Claude Opus 5.5) - the working Security suite preserved in _archive/security_v1/

- **Preserved at the user's request** -- asked twice; the agent had twice answered "git history
  has it covered", which was wrong: a usable copy is what was asked for. `_archive/security_v1/`
  holds the suite as it ran on 2026-10-19 and 2026-10-22, plus frozen copies of exactly the
  `Basic/` and `_os/` files it imports (found from its imports, not guessed), so it keeps
  working however the live layers change. Its own test passes from the archive
  (`_archive/security_v1/tests/test_security.py`), and its commands load the archive's copies
  (checked), not the live ones.
- Changed in the copy, nothing else: `_repo.TOOL_ROOT` three folders up (reports still land in
  this checkout's ignored `.agents/output/security/`); the commands it prints name the archive
  folder; the test imports the archive first and drops one block that tested the live observer.
- The Security design now says the archive stays and only the live `Security/` is retired at the
  cut-over. The requested scanner fixes (safe list, `--safe`, owner parity) go into the rebuild;
  the archive is not edited.

## 2026-10-23 10:19 - user (Claude Opus 5.5) - Qt trial: tray and native window over the display contract

- `tests/probes/qt_shell/` (a probe: tracked, never run by the suite): a tray icon (green /
  amber from `summary.attention`) with Open / Refresh / Quit, and a native window -- the fleet
  table, one column per machine, tinted by each cell's tone, and the selected repository's
  per-machine detail (v5 branch and commit). Reads the display contract and refuses an unknown
  version; decides nothing. `--demo` (invented three-machine fleet, one stale) or `--root`
  (a library observed read-only: no fetch, nothing published); `--screenshot`, `--seconds`.
- **Windows 11: works** -- Qt platform `windows`, tray available, native dark theme; checked by
  screenshot on the demo and on a real library (22 repositories, read-only).
- PySide6 6.12 (Essentials) is in the repo's `.venv` only: Windows Application Control here
  blocks any newly created `python.exe`, so a throwaway venv (temp folder, `.agents/output/`)
  could not run. Two empty failed venv folders remain for the user to delete (a guard hook
  rightly blocks `rm -rf`).
- Next: the user runs the probe on the Debian 13 KDE box; instructions and a results table in
  its README.

## 2026-10-26 07:13 - user (Claude Opus 5.5) - Security moved to _archive/Security/; handoff

- **`Security/` moved, unmodified, to `_archive/Security/`** (2026-10-23), the user's explicit
  instruction: preserve the existing manifestation, as a single folder. Before that the agent
  made two wrong versions -- a copy with edits of its own, then a copy with `Basic/`, `_os/` and
  tests added -- and the user had to stop it repeatedly. Lesson recorded in WORKING-NOTES ("How
  to work with this user"): do exactly what is asked, nothing beyond it.
- 12 files, byte-identical to the originals (checked by blob id).
- Left for the user's decision, untouched: the hygiene test and `tests/security/test_security.py`
  import `Security` and fail; the observer's message names `Security/rewrite_history.py`.
  Suite 47/49 on Windows. Run in place, `_archive/Security/` cannot find `Basic`.
- Full handoff: WORKING-NOTES, "2026-10-26 — HANDOFF".

## 2026-10-26 09:48 - user (Codex) - active read-only security scanners

- Added `Special/security/` with shared identity/watch/safe policy, explicit check registry, tree/history readers, bounded archive/image-metadata inspection and masked reports. Full reports require an explicitly chosen, verified ignored destination and exclusive creation.
- History inspection includes annotated tags, detached HEAD, non-commit refs and every path of identical blobs. Missing material, partial clones, shallow history, changed refs and unsupported binary coverage are reported rather than silently passed. Tree scope includes non-ignored untracked files; staged-only bytes are excluded explicitly.
- Fixed quadratic safe-policy matching found during the real scan and closed the shared process reader's stderr pipe after its collector exits. The preserved archive was not edited.
- Focused scanner verification: 21 tests passed; one symlink test skipped because Windows denied test-link creation. Shared process-runner, Basic object-reader and import-direction checks passed, as did whitespace checks. The deferred full suite remains pending.
- Ran tree/history scans and a repeat pass with full results held in private ignored agent output. Compared source refs and worktree status across each scan; no source changes occurred during observation. Candidate classification did not trigger any cleanup or safe-list writes.
- Rewriter execution remains blocked by the guard, including help and the attempted alias-configuration read. No exception, alternate launcher or guard setting change was used. General rewriting/proof and a disposable scan/rewrite/rescan rehearsal remain unfinished. No history rewrite, commit or push was performed.

## 2026-10-26 11:13 - user (Codex) - established-tool review and coordination reconciliation

- At the user's request reviewed established secret-scanning/history-filtering documentation before further implementation. Configuration, custom rules, reviewed exceptions, local/CI checks and an existing rewrite engine are available upstream; evaluating the smallest required orchestration/policy/proof surface is the current recommendation. No replacement, installation or CI change was made.
- Updated open work to distinguish provider credentials, custom publication policy, code/dependency security and repository housekeeping. A large real purge alone does not demonstrate correct detection or preservation; a controlled before/after oracle and independent checks remain necessary.
- Recorded the active/legacy allow-policy gap and block/allow conflict behavior for review. Corrected the earlier test interpretation: the symlink fixture skipped on an OS error, whose exact cause was not retained, so Windows permission attribution remains unverified.
- Reconciled implementation notes with the coordinating mission and target-specific cleanup notes. Kept full private findings outside tracked files. Existing archive and unrelated work remain unchanged; no rewrite, commit, push, guard exception or guard configuration change occurred.

## 2026-10-26 11:37 - user (Codex) - Preserved v1 finishing workflow inventory corrected

- At the user's direction reread the preserved rewrite command, verify/follow/relink/finish implementations and regression-test cases. V1 already performs mirror planning/apply/verification, produces push steps, follows rewritten clones, relinks quoted commit IDs and finishes with an exact-file commit and ordinary push. Earlier descriptions of unimplemented work apply to the active rebuild, not absence of these capabilities.
- Recorded concrete reuse/review boundaries: the archive remains unchanged; moved invocation/import assumptions, rule duplication, source freshness and proof scope remain concerns. The archived finish publishes by default and its printed no-commit instruction is inconsistent with that default, so it was not executed under the current no-commit/no-push direction.
- Connected tool work to a scoped publication/interoperability mission without changing this project's independence. Specific cleanup scopes remain in targets; implementation/regressions stay here. No archived or active rewrite test was run, no new finishing code was written, and no install, history change, commit, push or guard exception occurred.

## 2026-10-26 15:12 - user (Codex) - Canonical product contract and first output repair

- At the user's direction recorded `.agents/knowledge/product-contract.md` as the canonical connection between independently useful operations and one coherent app. It covers optional component setup, remembered machine context and enrollment, selected transports/state/notes integration, output preferences and explicit errors, code/data separation, security advice/action gates, local disclosure and consistent presentation. Linked it from the primary brief and existing architecture/security designs; preserved their layer boundaries and the frozen archive.
- Added an ordered actionable backlog with acceptance criteria in WORKING-NOTES. Current work now explicitly supersedes old handoff priorities. Configuration schema/merge details, notes-integration meaning, scanner engine selection and other unfinished mechanisms remain identified work, not completed features or implicit permission to install/migrate/publish.
- Completed the first bounded plumbing repair: `check --json` now reserves stdout for its manifest and sends fetch/status/publication messages to stderr. Human-mode output, catalog behavior and manifest-publication behavior are unchanged.
- Added three synthetic callable-command regression tests. Before the source change, both JSON cases failed parsing while the human-mode case passed. Afterward all three pass, including a simulated enrolled fetch/publication path; dependencies are mocked, with no real Git, network, config or transport writes. Whitespace checks passed. No deferred full suite, archived regression, guard-blocked command or native OS trial was rerun.
- Only this repository was edited in this step: six agent design/brief/notes/log files, one command and one focused test file. Earlier dirty work remains. No archive edit, setup/install, real history rewrite, commit, push, guard change or publication occurred. Next bounded work is the component settings resolver and its schema/precedence contract.

## 2026-10-26 16:57 - user (Codex) - Reconcile local data, source updates and achievable finish lines

- Clarified that the user-data root is outside the source checkout. Recorded setup-selected/custom storage and deliberate relocation, local logs beside user data by default, and a programmatic locator independent of untracked agent notes. Existing config_home/GITSPECOPS_HOME already support an external default/override; no paths or files were moved.
- Recorded ff-only source updating through one command contract callable from CLI/setup/app, reusing Basic/pull with clean/tracking/fork checks and app/peer restart handling. Existing setup does not implement source updates; frozen bundles need release updates. No updater was written or run.
- Captured intervening discussion: increasing-participation matrix, GUI invoking the same operations headlessly, programmatic LLM disclosure boundaries, hard scope exclusions separate from value lists, explicit whole-machine discovery, shared logging configuration and private state-repo ownership/API-budget work. Existing baskets and transports are groundwork, not completion claims.
- Marked one local configuration with component sections as a simplification proposal pending schema review; the earlier two-main-document arrangement is not a decision. Existing policy files remain supported until reviewed migration; shared-settings replication is optional later capability. No user choice, conflict strategy, log default or storage migration was silently implemented.
- Refined executable notes around three acceptance finish lines: predictable standalone operation/setup/update, proved security/repair behavior, and accurate two-machine fleet suggestions exposed by the same CLI/app operations with native OS evidence. Updated three existing agent design/notes/log documents only. No source change, test rerun, installation, Git update, history rewrite, guard change, commit, push or publication occurred.

## 2026-10-26 17:16 - user (Codex) - Guided setup contract and safe bootstrap selection

- The user accepted one local settings document with component sections. Updated the canonical contract and executable notes to make that decision settled while leaving schema/migration work explicit. Recorded setup as the guided lifecycle front door: guided configuration, selecting setup items, optional private state-repo CREATE/USE, updating only the gitSpecOps checkout, and uninstall/selective component unenrollment. Preserve user repositories and data by default; full lifecycle actions are not implemented by this step.
- Found that setup ignored every argument and unconditionally generated launchers/built an environment, including when asked for help. Extracted the existing bootstrap, added actual argument parsing and explicit bootstrap/launchers/environment/check actions, and an interactive selection menu. Help and cancellation do not run setup; a non-interactive call without an action exits 2 with instructions. Selecting one item does not run the others.
- The PowerShell and POSIX setup wrappers now invoke uv without project discovery/sync or automatic Python downloads before selection. The batch shim already delegates to PowerShell and was unchanged. Existing explicit bootstrap environment-building behavior remains; it was mocked during tests, not executed here.
- Nine focused tests passed, covering safe help, unattended invocation, explicit bootstrap, isolated item selection, environment failure, prerequisite-only checks, guided selection, back/invalid/exit and EOF cancellation. A real Windows PowerShell-wrapper --help invocation returned successfully with offline/cache controls. POSIX execution remains unverified. Whitespace checks passed; no deferred full suite or blocked command was retried.
- Scope: seven files in this repo only (setup script, two wrappers, one test, canonical contract, notes and this log). No real setup, environment creation, launcher generation, enrollment, repository creation, updater, uninstall, history rewrite, commit, push, guard change or publication was executed. Next is the accepted local settings schema/resolver and migration plan supporting the full guided workflow.


## 2026-10-26 17:34 - user (Codex) - Common local settings schema and read-only resolver

- Implemented Special/_settings.py above Basic, with one settings.json under the existing external user-data home. Strict schema v1 covers common scope/output/logging/protected-value settings, component overrides, explicit invocation overrides and per-field provenance. Excluded paths and protected values accumulate rather than being silently cleared. Paths inside settings are home-relative.
- Resolution creates no files or directories. Invalid/unreadable/ambiguous JSON, unsupported fields/versions, bad locations and exact case-insensitive safe/block conflicts produce sanitized errors without fallback. Legacy-only settings require explicit migration; a sync-only legacy home override is not silently ignored or applied to independent components. Existing readers remain unchanged.
- Summary/repr omit paths and private policy values. Raw effective values remain available to trusted operations; presentation masking is not an OS access boundary. Logging preferences resolve without starting handlers. The reader does not itself enforce repository exclusions or perform scan/commit/push actions.
- Documented the v1 schema/API/defaults and migration inventory in .agents/knowledge/settings-schema.md, linked it from the canonical contract and replaced finished definition work with concrete writer/migration/consumer tasks. Identity, transports, recovery and action consent still need explicit mapping before legacy cutover.
- Seventeen synthetic tests passed on this Windows environment. Import-direction verification passed across 60 stack files. Whitespace checks passed. No deferred full suite, archived rewrite regression or blocked command was rerun; native Linux/macOS behavior remains unverified.
- Scope: six files here (resolver, focused tests, schema document, contract, working notes and this log). No actual user settings read/write, migration, installation, enrollment, repository update, history rewrite, commit, push, guard change or publication occurred. Next is the explicit legacy-to-common mapping and validated writer before integrating consumers.


## 2026-10-26 19:44 - user (Codex) - Typed settings migration preview and validated writer

- Extended the common schema to v2 while retaining v1 reads. Typed machine identity, transport definitions and per-component options preserve CLI recursion/freshness/compression and the app's multiple transports, sharing, baskets, recovery, observation and desktop preferences. Shared identity/transport disagreements are named conflicts; distinct component selections stay distinct. Archive preferences are separated from original receipts/last-run state, which remain untouched.
- Added a read-only migration preview with sanitized summary/repr, original-byte snapshots and candidate fingerprinting. Existing targets, unknown/older formats, ambiguous source locations, relative enrollment paths and policy conflicts block instead of silently dropping fields or guessing. Changed/new sources, changed targets and altered candidates invalidate the preview. No source file is edited by previewing.
- Added explicit validated writing through the existing atomic file primitive, expected revisions and a cooperating-writer lock. Initial creation expects no target; replacement requires its exact prior revision. Linked destinations and storage inside this source checkout are refused. Failed replacement preserves the old file; successful save with failed lock cleanup is reported accurately. The lock does not control independent legacy processes, which must be stopped for real migration.
- Thirty-seven focused tests passed (17 resolver, 20 migration/writer), including simultaneous CLI/app preservation, privacy, conflict/staleness, retained receipts, revision/busy-lock refusal, atomic-failure preservation and lock-cleanup failure. Import-direction verification passed across 63 stack files; whitespace checks passed. The deferred full suite and prior blocked invocations were not retried; native Linux/macOS remain unverified.
- Ran a read-only preview of the current default user profile, returning only its safe summary: archive preferences and a protected-value list were found, no conflicts, archive receipts retained, no actions enabled and no legacy files changed. No raw paths, identities, keys or policy values entered these notes or the tool result. No configuration was written or adopted.
- Updated schema/contract and executable work toward guided preview/save, adapters and coordinated reader cutover. Scope is nine repo files (four source files, one focused test and four agent design/notes/log documents). Existing CLI/app readers are still unchanged; the source updater, guided enrollment/uninstall, logger integration and actual settings migration remain open. No installation, enrollment, network/repository mutation, history rewrite, commit, push, guard change or publication occurred.


## 2026-10-27 08:52 - user (Codex) - Visible operation scripts and private plumbing folders

- At the user's direction recorded public operation scripts at layer roots, named as actions, with supporting implementation in private folders. The chosen examples are Special/update_archive.py and Special/duplicate_org.py. Distinguished remaining verb-first naming proposals from those choices and kept all seven current Special entry points visible in the architecture mapping.
- Clarified the roles: the public command offers CLI and importable operation access; internal updater/orchestrator helpers perform the judgment and iteration using Basic. Prefix a private folder once rather than every internal module. The existing layer responsibilities and import direction stay in force.
- Recorded the endorsed single CLI/main-menu front door over the same callable operations, with a static command catalog for discovery/help/menu and structured unattended use. Executable/alias naming is still open; no CLI dispatcher or installation was added.
- Flagged relocation-sensitive behavior before moves: imports/tests/generated and installed entry points, resources and helper-relative runtime storage. The duplicator's runs directory currently follows its helper module, so blindly moving it would lose its existing resume location. Source organization and runtime-data migration remain separate reviewed work.
- Updated four agent documents only: architecture, product contract, working notes and this append-only log. No source move/rename, behavior change, test run, settings migration, setup/install, commit, push, guard change or publication occurred. Next is the complete source/destination/caller map for deliberate adoption.


## 2026-10-27 09:21 - user (Codex) - Source-derived documentation and archive entry-point clarity

- Recorded the user's requirement for essential module-header usage documentation and useful important-function docstrings/type hints. CLI/menu/generated docs should derive from those sources, real parser definitions and effect metadata, with handler references in the catalog instead of another copy of prose. Help/extraction must not execute operations, initialize runtime services or read private settings. Header audit/generation/parity checks remain executable work.
- Read current archive updater/sync headers and manager registration flow. Updater refreshes existing local repositories; sync adds provider-backed discovery/cloning and separately selected reconciliation/publication classes. Their present defaults differ and must remain visible during any consolidation. No behavior or names were changed.
- Confirmed that folder registration currently happens through archive_manage's menu or --install, coupled to launcher creation and registry persistence. Recorded explicit archive selection/registration UX as a design seam to review in guided setup/CLI, preserving one-off --root use. No archive was registered, launcher created or operation executed.
- Updated three agent documents only: product contract, working notes and this append-only log. No source/header sweep, documentation generator, test run, settings migration, file move, commit, push or publication occurred.


## 2026-10-27 09:46 - user (Codex) - Local archive manager is Special; fleet and scheduling remain Elaborate

- Recorded the user's chosen Special/archive_manager.py public entry point for selecting/configuring local archive collections, iterating the updater once per selected archive and returning structured results to CLI/menu/GUI. Its registry helpers must move down with local management; registry persistence alone does not make it Elaborate. Scheduling and fleet/sync-suggester orchestration remain Elaborate and invoke the same manager.
- Mapped current responsibilities into local selection/registration/refresh, explicitly selected per-archive setup, scheduled refresh control and fleet operations. Flagged import/test/launcher/docs, saved component identifiers and external user-data paths for preservation during extraction. No source extraction or runtime-data move was performed.
- Recorded archive recognition separately from update eligibility, with actual Git checkouts including valid .git files, user-selected/discovered candidates, hard exclusions and explicit depth/nesting. The current implementation is stricter: eligible direct children with approved origins. Discovery is not enrollment.
- Clarified the naming question without silently choosing a rename: public archive updating is a common use, but the updater also supports private repositories; existing archive_sync can discover/clone public namespaces the user does not own. Personal cross-machine synchronization is a distinct Elaborate workflow. sync_self.py remains a suggestion, and existing archive-sync capabilities must survive the reviewed mapping.
- Updated four agent documents (architecture, product contract, working notes and this log). Whitespace checks passed. No source move, behavior change, test run, registration, settings migration, setup/install, repository operation, commit, push or publication occurred.


## 2026-10-27 09:50 - user (Codex) - Archive manager exposes both update and sync

- Corrected the current architecture/contract/working notes to the user's clarification: Special/archive_manager.py selects archives and invokes either update or sync per archive. The manager is a pathway into both independently useful operations, not an updater-only interface.
- Effective operation is explicit in request/results. Preserve per-archive configured modes, invocation choices and the direct operations' scope/review/approval boundaries; no implicit repair or publication authority. Shared private helpers support the manager and direct command facades without a sideways import of sibling public commands.
- Updated four agent documents only. No source extraction/rename, settings change, operation execution, test run, commit, push or publication occurred.


## 2026-10-27 10:10 - user (Codex) - Checkpoint disclosure review

- The user authorized a checkpoint scan, necessary disclosure cleanup, one commit and an ordinary push before further architecture work. Reviewed the existing 36 changed files; no source relocation or actual settings migration was added to this checkpoint.
- Used the preserved scanner's callable tree and history readers without their automatic report writer. Included all 225 indexed/non-ignored candidate files, including the new sources and tests. Live organization/tailnet identity seeds and the ten-value protected list were available; raw values remained outside tracked records. Compared findings with the committed baseline rather than confusing previously published material with new disclosures.
- Removed three private coordinator identifiers from uncommitted log headings. Assembled one invented credential assignment at test runtime, preserving its behavior without a source-scan alert. No saved policy exception was added. The current scanner independently reported no coverage gaps for the selected tree checks; two remaining invented fixture candidates were individually reviewed. These checks are not an exhaustive security clearance or a cleanup of existing history.
- Verified staged blobs against the scanned working files. Repository hygiene passed seven checks over 225 files. Settings resolver/migration, setup, sync-output and scanner tests ran 71 cases with one symlink case skipped; process-runner and 63-file import-direction checks passed. The deferred full suite and archived rewrite regression were not retried; Linux/macOS remain unverified.
- The checkpoint preserves the frozen archive, including its legacy output behavior; it does not adopt that fallback for active tools. Guided settings adoption, shared logging, security/action integration and the reviewed architecture moves remain open. Use a public noreply commit identity; no force push or history rewrite is authorized by this checkpoint.


## 2026-10-27 10:32 - user (Codex) - Settings helpers consolidated

- Moved the four settings modules into Special/_settings/: resolver/schema in __init__.py, typed records in records.py, preview in migration.py and writer in store.py. Preserved the Special._settings resolver/schema API and updated internal/test imports. Module headers now state their import/use contracts.
- Adjusted the writer's file-relative source-root calculation for its extra directory level, preserving refusal to store settings anywhere in this checkout. Added a temporary-source regression that checks the root and nested destinations are rejected before directory creation. No actual user settings were read, written, migrated or adopted.
- All 37 pre-move focused tests passed before the move. Afterward all 38 tests passed, including the added boundary regression; the import-direction check passed across 63 files. Compared all four moved modules with their checkpoint versions: differences are limited to declared module-header/import edits and the source-root adjustment. Updated current schema/architecture links and removed completed settings-grouping work from the open task.
- Scope is four module moves, one test file and four agent documents. Archive/duplicator helpers and public commands have not moved in this batch. No settings behavior, persisted format, user-data location or saved policy was changed. No installation, commit or push occurred; native Linux/macOS checks remain pending.


## 2026-10-27 10:45 - user (Codex) - Archive and duplicator helpers grouped

- Moved the archive planner to Special/_archive/plan.py and the five duplicator helpers to Special/_org_duplicator/ (batch, local_repos, operations, remote and tracking). Updated four production callers and six existing test files, including the operations source-path assertion. Public command paths and their CLI behavior remain unchanged in this batch.
- Preserved the existing ignored Special/duplicate_org/runs/ location explicitly from the Special layer. No real resume files were read, moved, cleared or recreated. Added checks for the retained path and the batch flow's shared location, plus temporary-data resume checks for download, scoped download, upload and migration; completed-work lists and logs survive a same-session restart.
- Archive-plan/publish and all four duplicator checks passed before and after the moves. The archive-manager temporary-repository integration test and the import-direction check (63 files) passed. All four affected commands answered --help successfully from outside the checkout. Tests used synthetic local fixtures, with no network operations or real archive enrollment.
- Compared all six moved helpers with their checkpoint source: differences are confined to module headers, imports and the location-preserving tracking expression. Updated the current brief, architecture mapping and open work; historical logs/handoffs remain intact. Scope is six helper moves, four production callers, six test files and four agent documents, preserving the earlier settings batch. Public-operation relocation and local-manager extraction are next. No installation, user-data migration, commit or push occurred; native Linux/macOS remain unverified.


## 2026-10-27 11:04 - user (Codex) - Public operations and local archive manager extracted

- Added the selected Special/duplicate_org.py, Special/update_archive.py and Special/archive_manager.py public entry points. Shared implementations live in _org_duplicator/command.py and _archive/updater.py, sync.py and manager.py. Archive Sync remains at its existing public name. Earlier updater and nested duplicator script paths are thin compatibility wrappers for installed launchers; the duplicator's displayed parser name now matches its public command, with its interrupt/resume handling retained.
- Moved registry plumbing from Elaborate into Special/_archive/registry.py and updated runtime/test imports. The registry filename/format, log/report locations and retained duplicator runs location are unchanged. Local registration/status/forget/refresh and its update/sync paths now live in Special. Elaborate retains scheduling, refresh-all launcher generation and legacy local flags/menu forwarding to the same local functions. Existing scheduled launcher paths remain valid.
- Setup's generated launcher specifications now target the new public Special paths. No real launchers were regenerated. Updated public/current agent documentation and the architecture mapping; older handoffs/logs remain intact. Shared source extraction preserves current validation, report defaults, saved modes and exit-code interfaces. Structured request/results, settings/logging integration, recognition changes and registration without launcher creation remain separate functional work.
- Manager integration passed in a disposable local archive, including registry sharing, real local fast-forward, retained launchers, both saved modes, no import-time state creation, refusal of scheduling flags in Special and mocked monthly-task routing in Elaborate. Publish-safety, duplicator batch/selection/resume, sync configuration, nine setup tests, 38 settings tests and archive-plan checks passed. All seven new/compatibility command paths answered --help from outside the checkout; import direction passed across 70 files. No deferred full suite or native Linux/macOS trial was run.
- Compared the extracted engines with prepared relocation sources, registry logic with its original, and all twenty unchanged manager/scheduling function bodies with their pre-extraction versions. Local menu/parser omit scheduling; legacy menu/parser remain available. Whitespace checks passed. Earlier uncommitted batches remain intact. No real archive operation, OS task installation, enrollment, user-data migration, commit or push occurred.


## 2026-10-27 11:36 - user (Codex) - Standalone updater settings, results and logging integrated

- Connected the standalone updater and its older script alias to the common archive_update settings resolver. Added headless UpdateRequest/UpdateResult/run_update, schema-v1 presentation records, plain-language diagnostics and meaningful exit codes: zero for completed work including deliberate skips, one for failed eligible pulls, two for scope/settings/inspection/required-output failures. Explicit roots replace saved roots; exclusions accumulate and apply before Git inspection. Linked child folders and repositories containing an excluded subtree are skipped. No automatic enrollment or profile fallback was added.
- Added CLI output/format, settings-home, exclusion and logging overrides while retaining legacy report flags. Stdout contains only the chosen result, with progress/diagnostics on stderr. File-only is explicit. Reports follow the selected text/JSON format, reserve unique exclusive files, and never overwrite/fall back; protected values and credential candidates are concealed. Full origin URLs remain opt-in in both formats. Raw result access is an explicit trusted callable option, never an operational-log channel.
- Added the shared Special/_runtime/ logger and destination helpers. Default operational logs use bounded rotating JSON-lines containing only event names, component/run ids, timestamps and counters. They never tee output or include repository/path/branch/origin/settings/diagnostic values. Cooperating processes lock append/rotation and close files before release; busy/stale locks and write failures are visible, with no automatic lock removal or alternate destination. Required sink preparation precedes pulls; mid-run log failures stop further updates. Results retain partial work and incomplete new reports are discarded best-effort.
- Twenty-four new focused cases passed (18 updater, six logging), including real temporary fast-forward and dirty preservation, clean JSON/progress separation, exact stdout/report equality, saved/explicit settings, exclusion before inspection, legacy/malformed-profile refusal, no-profile-write help, redaction, exclusive reports, failures before/after effects, bounded rotation and two-process concurrent rotation. The existing 38 settings cases and manager integration passed; layer imports passed across 75 files. Both script aliases answered help from outside the checkout. No deferred full suite or native Linux/macOS checks were run.
- Updated the current contract/schema/brief and executable work. The standalone updater is the first consumer only; guided preview/save/migration, remaining command adoption, manager result integration, multiple log sinks, source updating and enrollment are still open. Actual user profiles were not read or changed by this batch; validation used invented temporary state and local Git repositories. Earlier batches remain uncommitted. No real archive update, install, enrollment, migration, commit or push occurred.


## 2026-10-27 12:11 - user (Codex) - Reviewed updater settings setup connected

- Added guided updater preference creation/editing plus settings-preview/settings-save and read-only settings-migration-preview to the existing setup menu/CLI. Scope is updater roots/exclusions, output and logging; other fields/components are preserved. Guided save requires typed SAVE; headless save requires the exact preview id. Cancellation/EOF before saving writes nothing, semantic no-ops preserve original bytes, and the existing atomic writer rechecks target/source freshness under its lock. No settings action authenticates, enrolls, installs or runs a repository operation.
- Added private setup plan/presentation helpers. Summaries omit paths/policy/identity/key values; explicit path review reveals selected paths with credential/key concealment. Extracted select_home/resolve_document/legacy_locations so setup uses the same home selection, validation/merge and source-location definitions as readers/migration previews. Existing supported configuration versions remain supported.
- Migration preview now distinguishes valid mapping from safe activation. Fresh-profile saving refuses known legacy sources; no migration-activation action is exposed until active archive/security/fleet readers and savers are coordinated. Editing an existing common profile changes only its already-adopted updater component. Actual legacy files are not copied, rewritten or activated by this batch.
- Corrected setup wrappers to retain the caller's directory and use an absolute setup-script path; bootstrap operations still use explicit checkout paths. A real Windows wrapper preview from a temporary outside folder verified relative-root behavior without saving a profile. The native POSIX branch remains unverified.
- Twenty-two new setup cases passed, including guided save/cancel, exact and stale approval, source/candidate changes, final writer freshness checking, preservation of other components, exclusion ownership, no-op writes, private summaries/path review, legacy refusal and preview-save-updater integration. The existing nine setup, 38 resolver/migration and 18 updater cases passed; import direction passed across 77 files. Validation used invented temporary profiles only. No deferred full suite, actual user-profile read/change, real migration, archive operation, installation, commit or push occurred. Next is coordinated reader/saver adoption before legacy activation.

## 2026-10-27 13:03 - user (Codex) - Archive preference and receipt adapter prepared

- Added one private Special/_settings/archives.py adapter and focused tests. Existing common v2 archive settings are read without legacy/default fallback or implicit version upgrade. Raw preferences/receipts stay private; summaries/repr omit their values. Configured archives/modes/allowed remotes remain authoritative when joined to receipts; empty choices do not enroll historical roots or inherit old permissions. Conversion performs no repository inspection or filesystem alias resolution.
- Explicit preference saves reuse the common revision-checked writer, preserve other settings, and recheck snapshots/targets plus optional source verification under its lock. Semantic no-ops preserve exact bytes. Pure receipt merging preserves inactive/unknown historical records and original installation time, updates only operational fields and cannot write preferences. It performs no receipt persistence or enrollment.
- Found a cutover dependency: generated archive launchers copy mode/remote allowances into arguments. Kept manager/registry/sync-import consumers unchanged so this preparatory adapter does not introduce a competing authority. Recorded the coordinated reader/saver/launcher transition, exclusions, empty-allowance behavior and receipt concurrency/partial-failure work as the next batch. Migration activation remains unavailable.
- Twenty new adapter cases and 38 existing settings cases passed on Windows; import direction passed across 78 files. Tests used invented temporary profiles only, including stale saves, failure/lock handling, other-field preservation, retained receipts and no fallback. No actual user profile was read or changed; no archive operation, launcher rewrite, installation, migration, commit or push occurred.

## 2026-10-27 14:22 - user (Codex) - Manager archive settings and launcher integration

- Connected manager/registry readers and explicit preference/receipt savers to the archive adapter when common v2 settings exist. Legacy-only profiles retain their registry; invalid common settings never fall back. Source snapshots plus an exclusive registry lock reject stale writes, including a copied view losing its revision context. Explicit install/forget uses the common settings writer; unrelated settings and retained historical receipt material survive. New receipt state is format v2 and requires common settings, preventing missing settings from reactivating historical preference copies. The first common install/forget marks receipt ownership before changing choices; partial failures are explicit, without claiming a multi-file transaction.
- Added --settings-home and --refresh ROOT to both manager paths. Newly generated per-archive launchers call the Special manager with root/profile only; refresh-all launchers pin the same profile. Unspecified install mode/remote allowances preserve saved choices. Forgetting common registration keeps receipts/artifacts for ownership review and later single-root runs refuse the unregistered target. Noninteractive calls need an explicit action; irrelevant/conflicting options fail before profile reads. Sync archive-root import now uses the same authority, and invalid hints stop initialization before optional remote creation or a config save.
- Enforced common exclusions and linked root/child refusal before manager Git/report effects. Until partial archive scope is implemented, an intersecting exclusion refuses the whole archive. Empty remote allowances fail without default widening. Manager report/log formats/destinations remain the earlier implementation; full runtime/result adoption is separate work. Existing installed launchers and actual profiles were not touched. Legacy migration activation remains unavailable pending security/fleet adoption and deliberate existing-launcher/writer transition.
- Found and fixed an existing shared-sync selection defect: origin approval was calculated but discarded when building the action set. Local candidates and upstream clone URLs now honor the selected prefixes, rejected candidates produce scope issues, and blank prefix strings cannot authorize everything. Kept update/sync action classes and the separate publish path. A real disposable archive proved an unapproved pull refused, tracked edits preserved and an approved clean checkout fast-forwarded. The first dirty test incorrectly expected unrelated untracked files to prevent a pull; corrected that fixture to modified tracked content without changing the engine's existing untracked-file behavior.
- Twenty-eight new integration cases, 20 archive-adapter, 17 settings and 21 migration/writer cases passed on Windows (86 focused cases). The real manager integration, archive plan/publish and legacy sync-config checks passed; import direction passed across 78 files. Launcher generation was exercised only in temporary fixtures, scheduling was mocked, and native Linux/macOS remain unverified. No deferred full suite, real settings read/change, real archive operation, user launcher rewrite, installation, enrollment, migration, commit or push occurred. Next is security-policy reader/saver adoption, then fleet configuration; common manager output/logging remains open.

## 2026-10-27 15:10 - user (Codex) - Active scanner common policy and explicit save adapter

- Connected active tree/history policy loading to the common security resolver, including an already-resolved caller seam. Saved and component protected values remain effective when explicit watch files are added. Allowances supplement saved policy; exact case-insensitive block/safe conflicts fail before scanning, including conflicts with discovered public identity. Stale default text lists are not competing authorities. Linked roots and intersecting exclusions are refused before Git inspection; missing or unreadable explicitly selected text files remain coverage gaps.
- Added --settings-home and explicit --legacy-policy. Legacy mode reads original text lists without changing them and cannot bypass an existing common settings file, even an invalid one. Normal scans never silently fall back. Masked stdout and explicit full-report behavior remain; JSON errors now declare incomplete coverage without exposing paths or subprocess details. Excluded report destinations fail before scanning. Help does not load profiles. No automatic report/log sink was added.
- Added a private common-policy snapshot/save adapter and guarded existing-document reader. The adapter edits only supplied defaults.security lists through the shared atomic, revision-checked writer, preserving other fields, component policies and original schema version. Conflicts in other components are rejected. No-ops preserve exact bytes; stale/mutated snapshots and busy locks fail explicitly. There is no public policy editor UI, implicit profile creation, identity import or legacy-file write.
- Twenty-four policy/settings cases, 24 scanner cases, 17 resolver, 21 migration/writer and 18 updater cases ran: 103 passed and one native symlink case skipped for unavailable creation privileges. Disposable local Git tests exercised both tree/history command paths with common policy and explicit legacy mode, masked output and unchanged HEAD/index/settings. Import direction passed across 79 files. Native Linux/macOS, the deferred full suite and archived rewrite tests remain unrun.
- Updated current public/agent documentation and open tasks; generated and read a caller-owned depth-three inventory (46 directories, 243 files). Fleet CLI/app settings readers and savers are next. Policy editing/revelation UI, recovery/hygiene/advice/action integration, scan-policy freshness and enrolled-profile settings-loss ownership remain open; archive receipt versioning alone does not prove global cutover. Migration activation stays unavailable. Actual user profiles/policy lists were not read or changed; no real repository scan, rewrite, enrollment, installation, commit or push occurred.

## 2026-10-28 06:43 - user (Codex) - Common fleet CLI and app settings connected

- Added Special/_settings/fleet.py to project existing common enrollment into CLI/app runtime records, preserving CLI root recursion and one transport versus the app's multiple transports, baskets, recovery and observation choices. Invalid/incomplete common enrollment fails; an unenrolled component never falls back to old configuration. Common v1 profiles are not upgraded by component setup. Legacy-only files remain usable without import or common activation; their existing app-version conversion remains separate.
- Connected CLI init/read/save, app setup/settings commands, rescan and startup checks, the packaged entry point and the dashboard's desktop-client saver. --settings-home selects the common profile; --config-dir and the legacy sync-home override select fleet state/legacy inputs independently. New setup/tray/autostart arguments retain both selections. No existing launcher or runtime data moved. Help and capability preflight remain independent of profile reads/locks.
- Common saves require the source snapshot and reuse the atomic revision-checked writer. Stale/mutated snapshots, busy locks and plain-copy bypasses fail; semantic no-ops preserve bytes. Other component/policy/output settings survive. Per-component setup reuses shared identity and refuses replacement; changing a transport selected by another enrolled component requires coordinated review. Clearing a selection retains its shared definition. Relevant setup conflicts are checked before optional remote creation; a remote action and settings save are not a global transaction.
- Common exclusions and linked-root checks precede inventory, including explicit CLI roots on an unenrolled common profile. Partial-root discovery remains unimplemented, so an intersecting exclusion refuses the root. The dashboard now persists only its desktop-client choice rather than accidentally serializing runtime-discovered tailnet identity. A stale failed save preserves the prior runtime choice. Loaded common views cannot redirect a save into old files after settings loss.
- Thirty-seven new integration cases passed, including a real disposable Git check with no publication/catalog save and unchanged settings/HEAD, plus settings commands, runtime profile forwarding, legacy compatibility, write failures, stale/no-op saves, scope refusal and privacy boundaries. Seventeen resolver, 21 migration/writer, 28 archive-manager and three sync-output cases also passed (106 unittest cases total). Existing legacy CLI config, fleet app/peer, tray/autostart, desktop-client and recovery-runtime checks passed. Import direction passed across 80 files. One initial test incorrectly required an explicit null for an already-disabled client; the corrected case selects a client before disabling it, preserving semantic no-op behavior.
- Updated current public/agent documentation and open work. Migration activation remains disabled: existing launchers and independent old writers still need a reviewed transition, settings-loss/cutover ownership needs evidence across enrolled components, and other security consumers/action freshness remain unfinished. Common fleet/manager output and logging, live profile reload, native Linux/macOS and packaged-app validation remain open. Actual user profiles were not read or changed; no real repository operation, remote creation, enrollment, installation, history rewrite, commit or push occurred. Prior uncommitted work was preserved.

## 2026-10-28 06:44 - user (Codex) - Fleet root normalization verification

- Final review found that resolved roots were normalized but recursion-map keys were compared as raw strings. Equivalent absolute spellings could therefore fail on Windows separators or lexical parent segments. Normalize those keys with the same lexical helper, without following filesystem links; duplicate normalized aliases remain an error rather than choosing one permission. Earlier fixtures used canonical temporary paths and missed this case.
- Added the alias/duplicate regression. All 38 fleet integration cases now pass, with the earlier 69 resolver/migration/manager/output cases giving 107 focused unittest cases for this batch. Import direction again passed across 80 files. Generated/read the final depth-three inventory (46 directories, 245 files). User-data and migration boundaries are unchanged.

## 2026-10-28 06:45 - user (Codex) - Supplementary verification left pending after guard block

- DCG blocked the final combined Git/PowerShell whitespace/log-marker check as windows.filesystem:windows-filesystem-semantic-unverified (allow-once 487079). No exception, alternate route or retry was attempted. Earlier whitespace checks passed; the final 38 integration cases and 80-file import check passed after the last functional change. Recorded only this supplementary check as pending, without claiming final whitespace/log-marker verification completed.

## 2026-10-28 07:39 - user (Codex) - Existing-settings switch reviewed without activation

- Clarified that migration means moving existing saved preferences into the agreed shared settings document. Used the existing read-only masked mapping preview, then a caller-owned diagnostic that exposed only counts and launcher classifications. The selected archive/policy inputs map without conflicts. Verified input byte revisions again after inspection; no configuration candidate or private value was emitted into public records.
- Distinguished file-format readiness from operational readiness. Receipt-named launchers can be absent or carry copied allowances; existing refresh wrappers may omit an explicit profile. The preview's generic activation blocker is hardcoded and does not itself identify the remaining work. Recorded an explicit preview/save/recovery workflow with specific prerequisites and a separate launcher artifact plan as open work. An archive/policy-only profile should not require unrelated fleet enrollment; real writer/schedule state and desired artifacts need review before a switch.
- No product source changes, user configuration writes, launcher execution/repair, enrollment, repository operation, commit or push occurred. Machine-specific observations remain outside public records. Maintained open tasks at both knowledge levels; prior deferred guard checks were neither retried nor routed around.

## 2026-10-28 08:42 - user (Codex) - Reviewed archive and policy settings switch prepared

- Added Special/_settings/existing.py and setup actions settings-existing (guided), settings-existing-plan/save/status/resume. The scoped workflow handles archive preferences and protected/allowed-value lists; existing fleet configuration or an alternate sync directory is explicitly unsupported. General mapping remains read-only and now identifies that scope rather than claiming all readers remain unadopted. Help and planning create no state; default records mask paths/values, with a separate path-only review option.
- An exact review id binds the selected home, candidate, original source bytes/absence and named launcher revisions. Guided saving requires separately typed STOPPED, REVIEWED and SAVE; headless saving needs the exact id and both attestations. Independent old jobs/editors must actually be stopped; the flags do not scan or control processes. Invalid formats, duplicate roots, link/source destinations, outside-root named launchers and unencodable receipt metadata fail before activation.
- Approved saving exclusively preserves/flushed original bytes plus candidate/manifest under the selected external user-data home, then marks an existing registry as receipt-only v2 and creates common settings through the existing revision-checked atomic writer. Historical record fields survive and policy originals remain unchanged. Cooperating switch/archive locks are respected and never reclaimed. No cross-file transaction or automatic rollback is claimed. Partial state retains the bundle; status distinguishes saved/resumable/review-needed, and explicit resume refuses newer settings, changed sources/artifacts or damaged originals. Incomplete pre-manifest backups require manual review.
- The launcher plan classifies named files, supplies separate leave/review/repair/retirement choices, and names existing repair commands for per-archive and refresh-all wrappers. It does not execute them or infer desired schedules. Setup menus expose the guided action; CLI help, approvals, cancellation and structured errors share the same operation functions. Updated current public/agent documentation and pruned completed preparation work from the open task.
- Thirty-three new disposable-profile cases passed, covering byte retention, active-reader behavior, allowed values, privacy, approval/staleness, busy locks, backup/flush/receipt/settings failures, post-save exceptions, interruption/status/resume, target loss and tampered/newer-state refusal. Twenty-two existing setup, 21 mapping/writer, 28 archive-manager and nine root-setup cases also passed (113 unittest cases total); import direction passed across 81 files. Native Linux/macOS, actual launcher rollout and broader fleet conversion remain unverified/open. Previously deferred guard verification was not retried.
- On the actual selected profile, ran only the read-only plan, with source/artifact revisions checked; no live save/resume, backup bundle, settings/registry write, launcher operation, enrollment, Git action, install, commit or push occurred. Earlier uncommitted work remains intact. Next review desired launcher treatment and actual old jobs/writers before authorizing a live switch; remaining security editor/action integration stays separate.

## 2026-10-28 08:56 - user (Codex) - Read-only Windows job and launcher review completed

- Inspected visible Windows scheduled-task actions, process command lines and the current-user Run key through a caller-owned diagnostic that emits only counts/classifications. Initial sandbox metadata queries failed; an approved read-only invocation with access to Windows metadata succeeded. Raw task arguments, identities, command lines and machine-specific observations were not copied into public records. Visibility limits remain explicit; inaccessible processes and unknown wrappers/manual writers are not an all-clear.
- Reviewed named launcher references without execution. Prepared inert native replacement text through the existing Windows renderer, with a separate caller-owned plan and expected live-target revisions. Verified every draft's normalized text and unchanged source/target state. The recommendation preserves original bytes before any later replacement and leaves scheduling off; no artifacts are retired merely because they are missing or old.
- No product source edit, test expansion, real settings switch, launcher installation/execution, task/startup mutation, process stop, enrollment, Git action, commit or push occurred. Notes at both knowledge levels now distinguish completed review/preparation from pending approval of live changes. Earlier tests remain the evidence for the source workflow, and deferred guard verification remains pending.

## 2026-10-28 10:28 - user (Codex) - Conversation decisions reconciled with implementation

- Reconstructed the available conversation's product requirements into 60 acceptance rows at the top of WORKING-NOTES.md, with source evidence, implemented/partial/missing/unverified/open/paused distinctions and remaining acceptance. Kept product-contract.md as the canonical design rather than creating a competing design document. Distinguished user decisions from agent-selected schema/receipt/confirmation/logging details and unresolved naming/engine/integration choices.
- Inspected public scripts, settings/setup, archive/duplicator helpers, output/logging, scanners/policy, Basic Git operations, advice/recovery, fleet transports/actions, dashboard/tray and packaging. Confirmed major unfinished seams: universal output/logging, action-gated security, common command front door, full lifecycle, full app coverage and native/multimachine evidence. Recorded tray tee/generated-key output disclosure gaps without exposing any key. Earlier archived fallback assertion and history-proof work remain unresolved rather than inferred passing.
- Fresh existing unittest scripts ran 187 cases: 186 passed, one native symlink case skipped. Duplicator argument/selection/local-repository/operations checks, nine mocked peer checks and the 81-file import-direction check passed. Twelve help invocations from outside the checkout succeeded without creating a profile. These are focused/disposable/mocked results, not full-suite, cross-platform, live fleet or publication-clearance evidence. Previously deferred guard checks were not retried.
- Source/status baseline contained 121 audited Python modules and 85 unstaged worktree file entries (37 modified, 11 deleted, 37 untracked). Verified all 121 source hashes unchanged after record edits. Current connector evidence confirms public repository visibility; HEAD equals locally stored origin/main at bae0217, with no fresh remote-head/history query implied. File counts are not security findings or counts of private local path strings.
- Superseded the older live-settings/launcher next-step recommendation. That preparation remains parked; no product source, live configuration, launcher, schedule, startup, process, enrollment or repository history changed. No installation, commit or push. Only existing agent records and caller-owned ignored audit diagnostics were written; private cross-project scope and identities remain outside these public notes.

## 2026-10-28 13:35 - user (Codex) - Refined product decisions and first integration batches

- Recorded the user's settled direction in the existing product/security/settings/tier designs: stdlib core with optional Gitleaks, Betterleaks, TruffleHog or none; manual and automatic supported-action checks; actionable masked findings and explicit artifact presentation; archive discovery/membership choices; portable master behavior/policy plus additive machine policy; complementary durable Git, synced-folder/notes and direct peer conduits; gitso as launcher name. Removed those items from the undecided list. Live configuration, launcher, installation, history and publication permissions remain separate.
- Batch one added optional selected-material engine adapters and actionable scan record schema v2. Engines receive bounded admitted text through Basic.stream stdin rather than rescanning target paths or creating plaintext input files. They run without provider verification or ambient scanner configuration; returned candidates are mapped to source locations and use the same safe policy. None invokes no scanner; selected failure, missing executable, malformed/oversize/unmapped output is incomplete. Bounded-output refusal occurs after leaving a deliberately stopped stream so a valid JSON prefix cannot be mistaken for a complete report. Current protocols are Gitleaks 8, Betterleaks 1 and TruffleHog 3; newer protocols and actual native binaries remain acceptance work. No selected engine executable was found on PATH and none was installed.
- Added master/machine-only lists to the common resolver/editor and scanner, with accumulated blocks and cross-scope allowance conflicts. Preserved the existing public summary fields while adding safe local/engine metadata. Findings now include report-local ids, severity, masked location/line/object and remedy guidance; repr hides matched values/locations. Successfully requested reports are listed as artifacts. Logs, GUI revelation, private external report directories and automatic action gates remain unfinished.
- Batch two added pure portable settings projection/merge. Explicit private transfer records carry allowlisted behavior and master policy; local roots/exclusions, directories, credentials/fleet identity, transports, archive registrations, capture consent and machine additions stay local. Imports reject local-only injection and incompatible policy. Merge produces a validated candidate only, not a write, enrollment or transport synchronization. Actual shared revision/ownership/conflict coordination and guided transfer remain open.
- Batch three added root gitso.py: one static twelve-command catalog supplies source-derived descriptions/docs, a terminal menu and explicit argv dispatch to existing functions. Discovery/docs do not import operations or read profiles. Duplicator gained optional argv without replacing global sys.argv; direct invocation/resume handling is preserved. Corrected the fleet CLI's obsolete read-only-only module description before using source-derived documentation. Installed aliases, complete structured-operation/GUI integration and richer parser/effect metadata remain open.
- Final focused evidence: 268 unittest cases, 267 passed and one native symlink skip, across engines (18), policy (24), resolver (17), migration (21), existing settings (33), scanners (26), portable settings (9), updater (18), fleet settings (38), archive-manager settings (28), runtime logging (6), gitso (8) and settings setup (22). Gitso's twelve real help routes passed outside the checkout without profile creation. Duplicator argument checks and 83-file import-direction check passed. Engine process boundaries are mocked; scanner integration uses disposable Git repositories. No full-suite/history-clearance or native/multimachine claim. Previously deferred guard checks were not retried.
- Preserved previous dirty work. This turn touched thirteen product Python files, four test files and nine documentation/agent-record files across the product and private coordinator, plus an ignored caller-owned map. No source moves, live settings/launcher/job/startup changes, engine installation, real repository action, commit or push. Source implementation continues toward policy-aware supported actions; this does not complete the app or the publication mission.

## 2026-10-28 14:23 - user (Codex) - Archive publication uses the shared outgoing security gate

- Connected one supported action end to end: Archive Sync publish now captures its planned branch/tip/single endpoint and invokes Special/security/_push.py. The operation loads common or explicitly selected legacy policy before remote action, fetches the selected remote, reads the actual destination base and scans exact base..tip using the existing material/check/optional-engine code. Introduce-then-remove remains visible; simple removal of a prohibited value already at the remote baseline is permitted. Unknown candidates require review, strong patterns/prohibited values block, and coverage/selected-engine failures hold the push. --yes retains action approval semantics and cannot bypass security.
- Added the policy-free Basic.push.push_snapshot primitive while preserving the old plain push API. It sends one immutable full commit id to one branch, with no extra tag/mirror/submodule publication and normal non-force checks/hooks. Rechecks cover source/target/effective policy and ancestry constraints, including settings disappearance during a check. A last-moment local branch advance cannot change the fixed object sent. Remote/policy/config checks remain optimistic, not an atomic lock against arbitrary external writers. Only single matching upstream/push mappings are supported; triangular/multiple endpoints, absent bases and second-stage URL rewriting are refused for review.
- Extended the active reader with outgoing-range material, factoring existing history traversal/coverage checks without changing the standalone history scope. Shared Finding.severity supplies both action and presentation classification. Text summaries now show concise policy counts instead of a large settings/provenance dump; JSON retains the structured details. Outgoing remediation guidance explains why fixing only the working tree does not remove an outgoing historical finding. Raw Git/engine errors do not enter the new result record.
- Real disposable Git tests exposed a version-specific target-metadata case: default simple mode left push:remoteref empty while providing an exact push tracking ref. The reader now cross-checks that tracking ref against upstream rather than guessing a destination. Tests also exercise chained URL rewriting, configured matching/mirror/tag behavior, an existing rejecting hook, partial clones, binary gaps, selected engine failure, stale source/target/policy, policy loss and non-origin remote names.
- Final focused evidence: 110 unittest cases, 109 passed and one existing native symlink skip: push gate 34, scanners 26, engines 18, policy 24, gitso 8. The archive-publish regression, Basic Git operations, archive planning and 84-file import-direction checks also passed. Gitso tests include its twelve outside-checkout help routes, and a disposable publication test proves --yes still holds a blocked push. These results are on this Windows host, with local bare remotes and mocked external engines; no full-suite/history/security-clearance or native Linux/macOS claim. Previously deferred guard checks were not retried.
- Updated the canonical product/security designs, owning acceptance comparison and private coordinator summary. Removed a duplicated introductory launcher/security paragraph while updating README's current supported-action status. Remaining work includes exact named-content commit checks, other publish/advice consumers, common output/logging (including legacy archive path/report presentation), GUI/lifecycle, private transport ownership and repair/native proof.
- Scope: seven production Python files, two tests and seven documentation/agent-record files, plus one ignored generated map. Existing dirty work was preserved; no source moves, user settings/launchers/jobs/startup changes, dependency installation, real repository commit/push or history rewrite. All Git publication in verification stayed in disposable local fixtures.

## 2026-10-28 16:22 - user (Codex) - Checked named-file commits preserve staging and native hooks

- Completed the announced checked-commit slice. Special/commit_repo.py and the thirteenth gitso command call the same headless operation under Special/security/_commit/. Preview is read-only and returns an exact proposal id. Apply requires that current id, checks selected working-tree bytes, message and effective author/committer, then actual selected staged blobs after Git filters and final native hook inputs. Unrelated staged files are neither scanned nor committed; selected partially staged files retain Basic.commit's whole-working-tree semantics. Prohibited/strong findings block, uncertain findings require review and gaps/selected-engine failures hold the action.
- Basic.commit gained optional caller context, an after-add check, literal named paths, verbatim message handling and per-invocation hook routing; its ordinary behavior remains policy-free. A temporary relay delegates the existing pre-commit, prepare-commit-msg, commit-msg and post-commit hooks in order through native Git. It does not permanently install hooks or edit Git configuration. Hook rejection is preserved; hook edits to approved contents/message require a new preview. The guard rechecks policy provenance, including a settings file disappearing during hooks. Native error text stays private backend data, absent from normal text/JSON records.
- Added proposed-material scanning and shared Report.check_status/render_record so commit, archive publication and standalone checking use the same policy/readers/engines and masked presentation. Final commit parent/tree/message/identities are verified; a created commit or uncertain execution is explicitly partial rather than silently treated as absent or rolled back. A test found pretty-log parsing trims message whitespace; final proof now reads the stored commit body directly and preserves the original message.
- Final focused evidence: 150 unittest cases, 149 passed and one existing native symlink skip: commit gate 40, push gate 34, scanners 26, policy 24, engines 18 and gitso 8. Basic Git operations and the 89-file import-direction check passed. Native disposable cases cover additions/modifications/deletions, initial commits, unrelated/partial staging, exact approval and staleness, clean filters, line endings, whitespace, original/custom hook locations and order, rejection/private output, hook edits, policy loss, unsupported states and post-execution uncertainty. All thirteen help routes work outside the checkout without creating a profile.
- Compatibility is deliberately explicit: Git >=2.36, attached/unborn branches, individual regular files/deletions and traditional hooks. Directory/link/submodule selections, merge/rebase states, configured hook chains and custom index/object/pathspec/history environments are refused. Trusted hooks keep their own side effects; optimistic rechecks are not a sandbox or an atomic lock against outside writers. Evidence is Windows/local disposable repositories with mocked optional engines, not native Linux/macOS, full-suite/history clearance or protection in other Git clients. Previously deferred guard checks were not retried.
- Updated canonical product/security contracts, README, owning acceptance comparison and private coordinator summary. Remaining work includes other publishing paths, sync advice, common output/logging/artifact routing, GUI/lifecycle, private transport ownership and disposable rewrite/native proof. Scope: ten production Python files, two tests and seven docs/agent records, plus one ignored caller-owned map. Preserved pre-existing dirty work; no source moves, real repository commit/push/history rewrite, installation or live user settings/hooks/launchers/jobs/startup changes. Test Git commits stayed in disposable fixtures.

## 2026-10-29 07:26 - user (Codex) - Direct checked push and local security advice joined to sync and dashboard

- Continued the agreed implementation after the user authorized building/fixing remaining work. Traced actual publication consumers first: Archive Sync was the only higher-level caller pushing repository history; fleet actions perform observation/catch-up rather than hidden commit/push. Added Special/push_repo.py and the fourteenth gitso route over the existing headless publication gate. Local preview binds scope/profile/policy without network or security clearance. Exact-plan apply rechecks approval before remote access, then scans actual outgoing history and sends the fixed branch snapshot. A race test led to comparing approved policy again on entry into the gate, before fetch.
- Added Special/security/_advice.py: read-only working-tree and cached-outgoing checking with shared policy/readers/engines, masked records, timestamps, explicit gaps and no action clearance. Sync check invokes it for each observed checkout, keeps dirty/ahead/behind facts visible and retains security-alert rows in the fleet exceptions view. Missing upstreams/unsupported mappings do not prevent working-tree findings and cannot imply outgoing clearance. Known common settings snapshots are verified so profile loss before advice cannot become a fresh-default scan; policy loss during checking retains findings and marks incomplete.
- Changed sync check --json from a bare manifest to a versioned local envelope containing manifest/local_security/artifacts. Updated source help, README, fleet docs and consumer tests. Only the original manifest enters transports; masked security findings, paths and policy are not added to shared status. Read-only observation returns its useful sync result with visible security alerts; consumers inspect individual check_status values rather than treating success as action permission. Watch and manifest-only dashboards still do not run advisory scans.
- Added the explicit local-dashboard security-preview action through the existing loopback Origin/token boundary. It accepts a known repository id, checks every local copy through the same function and retains explicit selected-profile context. No browser-supplied path, report persistence or peer action was added. The UI displays timestamped masked findings/coverage in session memory only, without browser storage or notification/log replication. A synthetic UI probe now includes the same button and a real temporary policy/file finding.
- Final focused evidence: 106 unittest cases passed: push gate 40, local advice/UI boundary 17, fleet settings 38, gitso 8 and sync output 3. Fleet peer 10 checks, local dashboard 6 checks, desktop-client checks, sync aggregate freshness rules and the 92-file import-direction check passed. Node syntax checks and direct client checks verify structured security responses, existing message behavior and refusal without a token/known action. A new fixture initially used the wrong settings key; corrected it, then the final full push run passed. Optional scanners remain mocked and native other-OS/two-machine/security-clearance claims remain unproved.
- Attempted visual inspection using the existing temporary probe; browser access host was unavailable. Stopped that owned probe and confirmed its listener closed. No screenshot/native visual acceptance is claimed. Prior guard-deferred checks were not retried. Scope: fifteen production source files, seven test/probe files and eight docs/agent records plus one ignored caller-owned map. No source moves, live configuration/launcher/job/startup changes, dependency installation, actual repository commit/push/history rewrite or publication. All Git commits/pushes in tests stayed in disposable local fixtures.
- Remaining priorities: common output/logging and artifact presentation, especially the existing raw tray tee and automatic new-fleet-key stdout; continuous advisory scheduling/invalidation, complete GUI/attended remote actions, lifecycle/source update, portable policy ownership/transport, disposable rewrite proof and native fleet acceptance. The frozen archive remains unchanged.

## 2026-10-29 07:44 - user (Codex) - Separate tray operational logging from console and fleet-key disclosure

- Continued with the announced logging/privacy batch. Removed the raw stdout/stderr tee to fleet.log. The native tray now resolves common app logging and uses the existing shared event/counter logger (app_tray.log in the selected logging directory), respecting disabled logging, strict destinations and required-sink failure. Legacy-only enrollment has no older logging preferences to import; documented defaults use the selected user-data home without converting enrollment. Invalid common settings cannot choose those defaults. The app passes its known settings snapshot through startup so a disappeared profile cannot become a legacy/default run.
- Console forwarding and logging are independent. The console channel retains only a generic error flag for the icon, never raw error text for notifications or a log. Explicit lifecycle events carry finite names/counters. Stream restoration and logger closure now wrap even native-start failure. Logging setup failure stops startup instead of silently choosing another file. Existing log files/settings are not migrated or deleted. Native lifecycle behavior remains subject to real UI/OS acceptance; tests do not instantiate a real tray or change startup registration.
- New-fleet CLI/app setup no longer prints its generated key. Added fleet-key metadata/default-hidden and explicit fleet-key --show through a shared presentation helper. Raw JSON disclosure is deliberate to the current output/caller, not an isolation boundary for an agent capturing it. These commands do not save reports/logs, modify settings or acquire an app lock. Read-only default and explicit display, generated-key persistence without automatic output, and independent logs/notification text are tested.
- Final logging/disclosure evidence: 63 unittest cases passed (tray logging 8, fleet settings 41, shared logging 6, gitso 8), plus the existing 12 tray checks, Sync Suggester configuration checks and 92-file import-direction check. Combined with the preceding batch there are 123 distinct focused unittest cases passed, plus the recorded script/Node checks. Native tray creation, actual other-OS/multimachine behavior, full suite/history clearance and optional real engine binaries were not run. Previously deferred guard checks remain deferred.
- Updated product contract, user/fleet docs, owning acceptance comparison and private coordinator summary. This batch touched four production files, two test files and seven docs/agent records, preserving earlier work. No live settings/launcher/task/startup/process changes, installation, actual repository commit/push, history rewrite or publication. Broader logger/output adoption, complete log/report artifact UI, multiple sinks, human GUI revelation, lifecycle, portable policy transport ownership, continuous advice and repair/native acceptance remain open; these privacy fixes are not a whole-app completion claim.

## 2026-10-29 08:52 - user (Codex) - Managed refresh shares headless results and explicit output/logging

- Replaced managed refresh's in-process CLI invocation/raw log/latest-report search with Special/_archive/refresh_operation.py. Special/archive_manager.py exports run_refresh for programmatic/GUI use; local and retained Elaborate refresh flags use the same operation and integer-return adapters. Each archive retains its saved update/sync mode and remote allowances. Update delegates to the existing Git-only run_update; sync reuses detect_plan/apply_pull/apply_clone through optional callbacks, with no process-global stdout capture. No publish/reconcile/rename class or scheduling action was added.
- Common archive_manage output/logging preferences and explicit refresh-only flags now select stdout/file/both, text/JSON, aggregate report directory and enabled/disabled log/directory. One optional exclusive report and one counts-only shared log belong to the invocation; returned masked artifacts identify their actual locations. File-only mode announces artifacts on stderr. Empty collections honor selected sinks without creating registrations. Invalid destinations fail before repository actions with no alternate sink. Reports no longer default into managed archives.
- Validated all selected scopes before effects, rechecked authority after preflight and before each repository mutation, bounded clone targets to direct unlinked children and rechecked approved clone URLs. Scan-only leaves run receipts unchanged. Actual run receipts retain status/time through revision-checked saves, with no guessed last-report pointer. Status displays recorded historical metadata instead of globbing archive reports. Changed settings/receipts, required logging failure, receipt/report write failure, interruption and unexpected backend failure preserve partial/uncertain results and stop later work. There is no rollback or atomic transaction against arbitrary outside writers.
- Shared presentation repairs: updater protected values now include machine-local additions as well as master blocks; URI userinfo masking covers SSH/other schemes, not just HTTP/FTP. Manager/updater explicit report/log paths retain lexical spelling until link checks instead of resolving away aliases. ReportSink accepts an internal validated filename prefix, preserving existing updater defaults while naming manager reports separately.
- Final focused evidence: 85 unittest cases, 84 passed and one native symlink skip: refresh 25, manager/settings 28, updater 18, shared logging 6, gitso 8. Real disposable archive-management and publication regressions passed, as did the 93-file import-direction check. Tests cover real fast-forwards in both saved modes, approved clones, unsafe targets held before pulls, masked master/local values, JSON-only stdout, file-only artifact receipts, empty output, scope and authority changes, required I/O failures and uncertain interruption/backend completion. The host could not create the disposable directory symlink, so that native destination test was skipped; no broader OS/security-clearance proof is implied.
- Updated README, canonical product/settings contracts, acceptance comparison and private coordinator notes/log. Scope: nine production source files, three test files and seven docs/agent records plus one ignored caller-owned map. Preserved earlier dirty work; no source moves, actual user repository commit/push/history rewrite, install, live settings conversion, registration, launcher, startup or scheduled-job change. All Git mutations and generated launcher tests stayed in disposable fixtures; scheduling backends remained mocked. Prior guard-deferred checks were not retried.
- Remaining adoption: direct archive-sync CLI still has its older output/report behavior; registration is still coupled to launcher creation and registration/scheduling logs remain legacy. Inventory/duplicator and other sinks, complete artifact GUI presentation, lifecycle/source update, portable policy ownership/transport, repair proof and native fleet acceptance remain open. These results complete this managed-refresh slice, not the whole product or publication mission.

## 2026-10-29 10:00 - user (Codex) - One current archive runner and scheduling boundary

- Recorded the user's no-backward-compatibility ruling in the canonical contract and open acceptance comparison. Consolidated the managed-refresh helper as Special/_archive/operation.py: run_archives executes explicit headless requests and run_refresh selects registered update/sync choices. One parent invocation owns settings, masked results, optional exclusive report and counts-only log; child updater sinks are disabled. Public archive_sync.py and gitso route through sync_cli.py. Added shared CLI output-option helpers; no stdout capture or parallel direct report writer.
- Direct sync now defaults to preview/stdout, honors common output/log preferences, presents actual artifacts (stderr in file-only mode), validates exclusive publication and requires explicit unattended approval. Selected common settings are rechecked without profile fallback, including deletion/configured/schema state. All selected scopes are validated before effects; overlapping roots, links, exclusions, invalid allowances, clone targets and changed action origins are held. Explicit repair and update/sync paths reuse the existing engine. Publication binds local tips/targets and policy before approval, reuses the outgoing-history gate and retains masked findings plus completed pushes on later failure/interruption.
- Removed the obsolete archive_update.py alias, broad public helper reexports, unused argv adapters and old engine CLI/report/render wrappers. The updater now exposes report/log artifacts through the same artifact vocabulary, including file-only delivery, and preserves lexical roots through link checks. Registration no longer calls low-level mutation helpers; it selects/registers a mode and may offer ordinary refresh. Elaborate/archive_manage.py accepts scheduling actions only; new refresh-all launchers point directly to Special/archive_manager.py. Installed launchers, profiles and tasks were not rewritten. Removed-route launchers require separate explicit regeneration before use.
- Focused evidence: 137 unittest cases, 136 passed and one Windows native-symlink skip (direct sync 18, registered refresh 25, manager/settings 28, updater 18, push gate 40, gitso 8). Real disposable archive-management and publication scripts passed; import-direction check passed for 94 stack files. Tests include real pulls/clones/origin-and-folder repairs, real checked publication, no-provider update, declined approval, deleted/changed profile, no-fallback sinks, stream/artifact masking, and interruption after a completed push. Scheduling stayed mocked. Earlier failed intermediate expectations/imports were corrected; these are the final focused outcomes, not full-suite or OS-wide clearance.
- Updated current docs/spec/comparison and coordinator records. All Git writes and generated launchers stayed in temporary fixtures; actual checkout HEAD and locally stored origin/main remain bae0217. No real commit/push, fetch, history rewrite, installation, live enrollment/settings/launchers/startup/tasks or guard setting changed. Prior guard-deferred checks remain pending.
- Remaining: other command-family adapters/common consumers, registration versus automation separation, membership policy, legacy-data/receipt ownership conversion, GUI artifact/actions, lifecycle/source update, portable-policy transport, disposable history-repair proof, actual optional-engine/native/multimachine acceptance. This completes one archive source component, not the full tool or publication mission.

## 2026-10-29 10:11 - user (Codex) - Review accumulated work for authorized checkpoint

- The user explicitly requested one major commit/push checkpoint, followed by discussion of next work. Reviewed the accumulated settings/runtime, CLI, archive/duplicator organization, security/action checks, fleet integration, tests and agent records. Staged changes contain source, tests and documentation, not generated reports, tools, launchers or local state. Remote main matched the existing local base before commit preparation.
- The existing hygiene check identified four synthetic literals in two test files. Constructed the same credential/path fixtures at runtime and renamed a generic protected-value variable; scanner rules and allowlists were not changed. Hygiene now passes all seven checks over 274 tracked files. Fresh affected regressions pass: push gate 40 cases, registered refresh 25 cases with one unavailable native symlink case skipped. The previous bounded archive evidence remains in the preceding entry; the earlier deferred full-suite/extra verification commands were not retried.
- Read existing security text lists explicitly without converting settings. The active working-tree scan completed its selected built-in checks with no coverage gaps or high-confidence secret findings; review candidates are documented examples, generic Git/SSH addresses and synthetic security-test material, inspected against source. This is manual review, not an automatic checked-clean result. Optional external engine/native coverage remains unproved. No broad allowlist or guard exception was added.
- Checkpoint author/committer use the public handle and existing noreply email through a per-command identity override, avoiding the machine-qualified default name without changing saved Git settings. A normal commit and non-force push are authorized for this checkpoint only; no history rewrite, install, live settings/launcher/task change or broader publication is included. The actual commit/push outcome is recorded by Git and the private mission coordinator after completion.
