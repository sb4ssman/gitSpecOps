# External review, 2026-11-17 (GPT "Astra", medium effort, read-only)

A static read of the code from four seats: senior engineer, teacher, recruiter, end user. Nothing
was run. Kept here, apart from WORKING-NOTES, as a backlog to pull from. Each finding carries a
status; "unverified" means nobody has yet confirmed it against the code.

Overall: "a capable development preview for an experienced Git user"; the strongest parts reason
carefully about Git state, partial failure, privacy and recovery; the weakness is unevenness:
newer integrations do not always keep the guarantees of the older core.

## Findings, in the reviewer's order

| # | Severity | Finding | Where | Status |
|---|---|---|---|---|
| 1 | High | Basic push runs a bare `git push`, so Git configuration (a force refspec, a mirror remote) decides what leaves; "never forced" is not enforced. Pin the destination and an explicit non-force refspec, as `push_snapshot()` does; test with unusual configuration. | Basic/push.py | **fixed 2026-11-17**: the remote and one plain refspec are named; mirror, tags and submodule pushes off; tests with a force refspec, a mirror remote and push.default |
| 2 | High | safe-to-wipe can say SAFE over an unreadable subfolder: `find_repos()` swallows directory errors, so `every_repository()` cannot report the gap. Return coverage gaps; a proof needs full coverage. | Basic/_discovery.py, Special/_sync/actions.py | **fixed 2026-11-17**: `find_repos(gaps=)`; an unentered folder is a `not_checked` row that blocks the verdict |
| 3 | High | The page's commit and push did not pass the app's settings profile to secure-commit / secure-push. | Special/_sync/resolve.py | **fixed 2026-11-17** (`--settings-home`); still wants a test with a non-default profile holding its own prohibition |
| 4 | High | Materialize validates a rebuilt path, not the real target, and creates the parent first; planner and request path lay folders out differently. One destination check, on the real target and its existing ancestors, before creating anything. | Special/_sync/actions.py `apply_materialize` | **fixed 2026-11-17**: `target_inside_library` judges the real target before anything is created and again before the clone |
| 5 | Medium | A request loses the chosen library (only repo_id, host, owner, name, folder are copied), so a clone goes to the first library and a pull touches every local copy. Bind the action to the chosen copy end to end. | Elaborate/_fleet/peer.py, requests.py | **fixed 2026-11-17**: `library` travels with each item; a pull moves only that library's copy |
| 6 | High | Org upload and migration push refs directly, without the outgoing-history check; they send every ref except `refs/pull/`. Conflicts with the README's "every publication is checked". Check them, or label them unchecked; list the exported namespaces. | Special/_org_duplicator/operations.py | **changed 2026-11-17** by the user's decision: setup asks; No is an exact copy, Yes holds a repository with high findings and points to `history clean`. Exports branches, tags and notes only |
| 7 | Medium | Request results can carry raw Git diagnostics (paths, endpoints) to other machines; truncated, not redacted. Use public error codes, keep diagnostics private. | Special/_sync/actions.py `_message`, Elaborate/_fleet/requests.py | **fixed 2026-11-17**: other machines get fixed sentences by outcome; Git's words stay in this machine's tasks.log |
| 8 | Medium | `gh repo list --limit 1000` is treated as the whole namespace. Page to the end, or report an incomplete inventory. | Basic/_providers/github.py | **fixed 2026-11-17**: limit 20,000, and a list that fills it is an error, never the whole namespace |
| 9 | Medium | Newer code ran subprocesses outside the shared runner; `resolve._git()` ignored a failed exit, so "could not inspect" looked like "no changes". Recovery has its own runners too. | Special/_sync/resolve.py, Elaborate/_recovery | **resolve.py fixed 2026-11-17** (Basic's runner; a failed read raises, with a test); recovery unverified |
| 9b | — | Archive eligibility checks the approved origin, but `fast_forward()` runs `git pull --ff-only` with no explicit remote: a branch tracking another remote pulls from there. | Basic/pull.py | **fixed 2026-11-17**: the remote and branch are named; a branch tracking another remote is refused (also in catch-up) |

## Wider points

- **One operation boundary.** CLI and page should be adapters over one callable carrying: the
  profile and target, the exact plan and approval id, progress and cancel, and a structured
  outcome (success, refusal, partial, private diagnostics). Subprocess hops hide dependencies
  from the layer tests and lose profile and scope (findings 3, 5, 9).
- **"Protected" means different things** in checked publication, org migration, recovery's own
  scanner (skips binary patches, different patterns) and raw result text. Wanted: a short
  data-flow table per transport: what leaves, who can read it, what is optional, masked,
  unencrypted, and how to withdraw.
- **Absolute claims with real exceptions**: "never file contents" (recovery, when enabled) and
  "no reset --hard" (inside a disposable recovery checkout). Say the exception.
- **Tests**: strong on security cases; thin at the user-action boundary. Wanted: whole journeys
  (non-default profile, two libraries, choose one copy, preview, apply, assert profile, target,
  effects, result), and failure cases: unreadable folders, malformed peer records, stale requests,
  interruptions, odd Git configuration, names that need quoting. Source-inspection tests are for
  conventions; behaviour tests for guarantees.
- **Large files**: setup walkthrough (1,600+ lines), fleet CLI and peer (about 1,000 each); the
  peer mixes action handlers, the observation loop, networking, settings and lifecycle.
- **Docs**: history and present behaviour are interleaved; a newcomer needs a current-tense
  edition: what works today, one operation end to end, where its policy lives, how it is tested,
  what is incomplete. Suggested worked example: "commit these two files from the page".
- **Product**: make "Needs attention" the fastest route to work; label every count (repositories,
  copies, machines, findings); separate delivered / approved / completed / partly failed for
  requests (one can read "done" over a failure); show the target library and copy in every
  approval; readable plan summaries instead of raw JSON; say what Withdraw does not undo; check
  keyboard, focus, contrast and narrow screens; state what "duplicate an org" does not copy
  (issues, pull requests, releases, permissions, settings, LFS).
- **Portfolio**: three case studies (evidence of work on machines that are off; checking exact
  outgoing history; restoring work and proving a snapshot redundant), each as problem, failed
  assumption, design, test, remaining limit. A capability matrix: built, exercised, tested,
  accepted per platform, planned.

## The reviewer's order of work

1. Safety and scope defects: 1, 2, 3, 4, 5.
2. One operation boundary for app, CLI, schedules and requests.
3. One meaning of "protected": 6, 7, recovery's scanner.
4. Prove three whole workflows (org copy with a completeness report; an archive with mixed
   states; resolving one chosen copy with a non-default profile).
5. Publish the capability matrix.
6. Polish resolution: previews, true completion states, recovery after failure, an attention queue.
7. Only then expand (native window, richer remote actions).
