# Test suite audit — 2026-10-19

The first time anyone read the suite for **what it asserts** rather than whether it exits 0.
Until this, every pass count in these notes was a claim by the session that wrote the code.

**Run, not just read:** `python tests/run_all.py` on Windows 11, Python 3.14, neither
`PYTHONUTF8` nor `PYTHONIOENCODING` set: 44/44 files passed in 53 s, nothing skipped. Not yet run
on Linux or macOS.

**Method.** Every test file was read in full alongside the source it covers. A name-reference
map (which top-level functions no test mentions) located the gaps, and each suspected defect
was then **reproduced on disposable repositories** before being written down here. "Confirmed"
below means reproduced. "Plausible" means read in the code but not reproduced.

## Verdict

The suite is honest where it exists. The recovery chain (`sync/test_capture`,
`test_snapshot_*`, `test_retirement`) is the strongest part: real git, hostile bundles, rollback
partway through a failed restore. Aggregation and freshness (`test_sync_aggregate`) pin exact
boundaries. The peer regressions (`fleet/test_core_path`) are each tied to a defect that actually
happened. The import-direction and hygiene guards are real enforcement.

It is **not comprehensive**, and the gaps sit exactly where the product makes its promises:

1. **The verdict commands were never tested end to end.** `audit_repositories` is unit-tested
   with a repository that has no origin, but the real command only ever feeds it what the
   observer kept, and the observer drops such repositories. A unit test passing over a broken
   integration is the pattern to hunt for.
2. **Observation is tested against hand-built dicts, rarely against git.** Classification is
   excellent given a record. The code that turns a real repository into that record (porcelain
   v2 parsing, renames, conflicts, other branches) is barely exercised.
3. **The mutating verbs with the widest blast radius have no test at all:** `archive_update`
   (the scheduled updater), `archive_sync --reconcile` and `--rename-folders`, and the
   duplicator's download, upload and migrate operations.

## Confirmed defects

| # | Severity | Where | What happens |
|---|---|---|---|
| 1 | **critical** | `fleet safe-to-wipe` | Prints **SAFE, exit 0** when the machine holds the only copy of real work. Reproduced for each case alone: a repository with no remote; unpushed commits on a non-current branch; a stash; unpushed commits where the remote is not named `origin`. Causes: the observer drops repositories without a parseable `origin` and the command never reads `observer.issues`; ahead/behind is the current branch only; `git status` does not show stashes; repositories excluded by a basket or with unreadable status are also silently absent. |
| 2 | **high** | `Special/duplicate_org/_local_repos.safe_cleanup_directory` | Treats any folder containing a `config` (file *or* folder) or `HEAD` as a git repository and `rmtree`s it. The batch download skips only folders `scan_local_git_repos` recognizes as repositories, so a plain project folder that shares a repository's name and has a `config/` subfolder is **not** skipped, then deleted. Reproduced: the scan reported no repository, cleanup returned True, folder and untracked file gone. |
| 3 | high | Sync Suggester observer | Same root cause as #1, visible everywhere: no-remote repositories — the most at-risk work there is — never appear in the fleet view, only as an issue line. Unpushed work on other branches is invisible. See [`at-risk-work.md`](at-risk-work.md), which designed for this and is unbuilt. |
| 4 | medium | `fleet audit` | Its "no origin" finding is dead code in the real command (fed only repositories that have one). |

**Fixed 2026-10-19 (same day), each pinned by a test that fails on the old code:**

- #1 and #4: `safe-to-wipe` and `audit` walk the configured roots themselves
  (`fleet_actions.every_repository`) instead of trusting the observer, with hidden folders
  included, nothing skipped but `.git` internals, and each root itself checked. Wipe safety is
  now "is anything here on no remote": commits on any branch, tag or HEAD missing from every
  remote-tracking ref (all remotes fetched), stashes, operations in progress, dirt, bare
  repositories, missing roots. SAFE now states what it did not check.
  `tests/fleet/test_safe_to_wipe.py` builds 13 at-risk cases, each alone.
- #2: download and migrate refuse a folder that already exists instead of deleting it as a
  "leftover"; cleanup deletes only what discovery's own `classify()` calls a repository, strictly
  inside its parent. `tests/duplicator/test_operations.py`.
- `Basic/pull.py` reads HEAD before and after instead of git's English wording.

**Found while fixing:** the cleanup also deleted *its own parent folder* when that folder was a
repository; and on Windows it could not remove a real clone at all (git writes object files
read-only, and a plain `rmtree` stops on them) — the retry cleanup had never worked there. Both
fixed and pinned. Shared discovery (`Basic/_discovery.find_repos`) never checks the root itself
and skips hidden, `env`, `Library`, `node_modules`-like folders; right for a live view, wrong for
any verdict about losing work — #3 (the observer and the fleet map) is still open.

## Plausible defects (read, not reproduced)

- ~~`Basic/pull.py` detects "already current" by the English phrase `up to date`.~~ Fixed (see
  above); not reproducible on this Windows build, which ships no translations.
- **`archive_sync --reconcile` rewrites a stale origin to the provider's HTTPS URL** even when
  the clone used SSH; a user with only SSH keys can no longer pull.
- **`archive_sync --rename-folders` cannot do a case-only rename on Windows/macOS**: `dest.exists()`
  is true on a case-insensitive filesystem, so `foo` → `Foo` is always skipped as "target exists".
- **`GitHubProvider.list_repos` caps at 1000 with no warning.** The listing is treated as
  authoritative, so a namespace past 1000 reports the remainder as local-only orphans and never
  offers to clone what lies beyond.
- **`compare_repos` lists branches without `--paginate`** (GitHub returns 30 per page), so two
  repositories with more than 30 branches can compare as identical on the first 30.
- **Identity collision:** `parse_remote_url` keeps the first and last path segments, so
  `group/a/repo` and `group/b/repo` (GitLab subgroups) are one identity. `test_identity` pins
  this as correct.
- **`approved_remote` is a bare `startswith`.** The defaults end in `/` or `:` and are safe; a
  user-supplied prefix without a trailing separator over-matches (`…/my-org` approves
  `…/my-org-evil`).
- **The file-event ignore list applies inside repositories:** edits under a real source folder
  named `env/`, `Library/` or `AppData/` never trigger a refresh.
- **`Basic/_facts` dirtiness ignores untracked files** (`git diff --quiet`). Pulls stay safe
  because git itself refuses to overwrite an untracked file, but the fact named `dirty_work_tree`
  is narrower than its name.

## Weak or misleading assertions

- `archive/test_archive_publish`: `"their work" not in moved_log or …` can never fail (that
  string is file content, never a log line). `"is its own apply class…" in sync_source` proves a
  sentence exists, not that combining `--publish` with pull verbs is refused.
- `fleet/test_fleet_tray`: `labels[0] == "offline-box" or labels[0] == "quiet-box"` cannot
  fail after the preceding set check; "serving hosts first" is never exercised.
- `fleet/test_audit`: a dead line, `git(clean, "branch", …) if False else None`.
- `special/test_inventory`: the fixture comment promises "a stash on top" but never stashes, so
  the `stashed` flag is untested.
- `fleet/test_packaging_spec`: string matches on the build recipe; breaks on a harmless refactor
  and cannot detect a broken build.
- `os/test_os_parity`: compares function *names* only. macOS is mostly "unsupported" stubs, so
  parity passes and says nothing about behavior there.
- `repo/test_repo_hygiene`: a match is skipped if **anything on the same line** is allowed, and
  `<[a-z-]+>` matches every HTML tag. It also cannot know the owner's real names: a real account
  name sits in a `test_repo_transport` fixture today. **Fixed 2026-10-19.** Reproduced first on
  invented files: a path beside an HTML tag or a placeholder, an address and even a GitHub token
  beside `example.com` all passed; so did anything past column 500 (lines were truncated). Now the
  allowlist judges the matched text only, whole files are scanned, and a new check seeds
  patterns at run time from the git identity, the `gh` login (read offline from gh's config),
  the host name and the home folder's name — held in memory, reported as *kind* and location,
  never value. Only the owner of the project's public repositories and the authorship files are
  excused. It caught the fixture at once (now `example-owner/…`). A self-test runs the scanner on
  invented files and was shown to fail against the old logic.

## Tests that pin code slated for deletion

`sync/test_sync_watch` (the polling `watch`, dissolved by the architecture) and the v1/v2 → v3
config migration in `fleet/test_fleet_app` and `test_fleet_peer` (HANDOFF: "hard break", old
formats deleted). Delete with the code in phase 3c, not before.

## Structural problems

- **Three harness styles** (a `check()` list, bare `assert`, a hand-written `main()` that calls
  each test). Bare `assert` vanishes under `python -O`; a hand-listed `main()` silently skips a
  test someone forgets to list (none are skipped today — checked mechanically). Move to stdlib
  `unittest` (`TestCase`, discovery, one report) as files are touched; no third-party runner.
- **Nothing runs the suite on Linux or macOS**, against the brief's "validate on the platform
  you claim". macOS has never run it at all.
- **One real-time sleep** (`test_core_path` heartbeat, 1.2 s) — the only timing-dependent test.
- **No end-to-end CLI tests** of `sync_suggester.py` or `fleet_app.py` subcommands beyond
  `inventory_*` and `archive_manage`.
- `tests/repo/test_import_direction` rejects any third-party import, including in `App/`; the
  user has since allowed the App a dependency, so it needs an `App/`-only allowance.

## What is untested, by area (names no test mentions)

- **Basic:** `_facts` and `status` (no test imports them), `_pick`, most of `github.py`
  (`_ref_from_json`, `compare_repos`, `list_my_orgs`, `latest_release_tag` — all testable with a
  fake `run_gh`), `prompt_for_directory` / `resolve_directory`.
- **Special:** all of `archive_update`; `archive_sync` detect/pull/clone/reconcile/rename;
  `duplicate_org/_operations` (download/upload/migrate), `_remote`, `_tracking`.
- **Elaborate:** `install_monthly_task` / `remove_task`, the interactive menu.
- **`_os/`:** launcher text (quoting a path with spaces), `kill_tree`, `stdin_is_interactive`
  on POSIX, every `schedule` and `paths` function.
- **Sync Suggester:** `_status_counts` (porcelain v2 parsing), `patch_parse`, the Linux/Windows
  event backends beyond one creation event, the real autostart writers (`.desktop`, LaunchAgent
  plist, registry value), `fleet_net` client/server, every `fleet_app` command except setup.

## Order of repair (proposed)

1. Red tests for #1 and #2 (they reproduce today), then fix: safe-to-wipe discovers repositories
   independently and counts anything it cannot prove as unsafe; cleanup uses the scan's own
   classification and never deletes a folder that existed before the run.
2. Observation of no-remote repositories and all-branch unpushed work (#3), which the fleet map
   needs anyway.
3. Tests for the untested mutating verbs, on disposable repositories.
4. The weak assertions above; the hygiene loophole.
5. Harness convergence on `unittest`; the suite on Debian and a Mac.
