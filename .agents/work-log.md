# Work log

Append-only record of **completed** work. Newest first. Items that graduate from
[`working-notes.md`](working-notes.md) land here with an absolute date.

## 2026-09-04

- **Fixed the Windows discovery bug reported in the outside fleet review — the tool found nothing
  at all on a Windows drive.** A `check` against `T:\Github\...` returned an empty fleet. The
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
  - Not yet confirmed on the real Windows machine; that run is still wanted.

- **Compound facts are no longer hidden by precedence** (also from the review). `classify_repository`
  returns one headline state, which severity ordering needs but which necessarily buries everything
  behind it — a repository that was both dirty and ahead reported only "dirty", and the unpushed
  commits vanished. The headline is now documented as ordering-only, and everything that renders or
  advises uses the new `repository_flags` / `describe_repository` / `secondary_facts`. Live result
  on this repository: `STOP: uncommitted work on cbox (also ahead 9)`. Tests cover dirty+ahead,
  behind+stash, diverged+dirty, missing-upstream+dirty, and that a clean repository invents no
  extras. 12/12 suite files pass.

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
