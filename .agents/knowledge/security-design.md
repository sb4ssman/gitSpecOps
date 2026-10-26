# Security: the rebuild design

**Status:** agreed with the user 2026-10-20. Replaces the `Security/` folder built on 2026-10-19,
which cleaned this repository and ten others successfully but had the wrong shape. Nothing here
is built yet beyond phase 1 (Basic, done 2026-10-20). The plan to get here is at the end.

**The working v1 suite is preserved** (user's decision, 2026-10-23): `_archive/Security/` is
an exact, unmodified copy of the `Security/` folder (12 files, byte-identical, checked). Never
edit it. The *live* `Security/` folder is still retired at the cut-over; the archive stays.

## Why the old shape was wrong

1. **Security was ranked as a layer** (`Basic → Special → Security → Elaborate`). A layer says
   what code is built from; "security" says what it is for. Every other subject sits inside the
   layer of its level (archive across Special and Elaborate, `duplicate_org/` in Special, the
   fleet and recovery in Elaborate).
2. **It bypassed the stack beneath it.** `finish` committed and pushed with raw `run_git`, not
   `Basic/push.py`, under `EFFECT = "local"`; `follow` and `finish` asked y/N.
3. **`rewrite_history.py` was a six-verb monolith** (plan, apply, verify, finish, follow,
   relink) over an 806-line `_rewrite.py` doing four jobs.
4. **Part of it was the fleet's job**: the observer already detects a clone whose upstream was
   rewritten.

And inside `_rewrite.py`, seven root problems -- each fixed by construction below:

| Root problem | Fix |
|---|---|
| Plumbing printed and asked | Components return records; only commands show and ask; `clean_history` owns the stops |
| What a rule does was written four times (filter-repo text, filename callback, joined pattern, verify's rebuild) -- both 2026-10-19 bugs came from this | One `Rule` that renders filter-repo's syntax **and** applies itself in Python |
| The plan was an untyped dict grown by `update()` | A versioned plan record that also names the ref tips it was decided against; the rewriter refuses if the repository moved since |
| Planning scanned (twice), `scan_folder` re-did planning, and `scan_history` imported the rewriter | Scan once; planning is pure over the report; "who you are" lives in its own component |
| Git touched directly (bare clone, refs, reset, commit, push) | Every git act goes through Basic |
| One command spanned every effect, so its `EFFECT` lied | One effect per command |
| No explicit stage; `finish` could not tell whether the forced push happened | `clean_history` records its stage, and reads the remote's tips to confirm the push |

## Three ideas

1. **Material** -- what is looked at. One reader with a range: the current tree, all history, or
   outgoing commits (`@{upstream}..HEAD`). Archives and image metadata are opened inside it.
2. **Checks** -- what is looked for. Each declares the material it needs and returns findings.
   A registry, like the providers: **a new security feature is a new check module and one line.**
3. **Remedies** -- what to do about a finding. Rewriting history is one; fixing a git identity,
   a host setting, or rotating a secret are others. Only the rewrite is built now.

Rewriting history is not itself security: it rewrites a repository by rules. Security decides
the rules. So the rewrite machinery sits in plain `Special/`.

## Where things go (placement A, decided 2026-10-20)

Security lives **inside each layer it occupies**, in a `security/` folder; there is no Security
layer. Decided over a root `Security/` folder because no other subject has one -- the question
"why not `Archive/` and `Fleet/` too?" has no good answer -- and because the App gives the
one-place view of security anyway. Components are in Special either way, so this is cheap to
revisit: only thin command files would move.

```
Basic/      plain git, one operation, no judgment -- no security code
  reset_keep.py        moves a branch; never overwrites an edit; never --hard   (built 2026-10-20)
  commit.py            commit named paths with a message; never -a, never --amend   (decided 10-19)
  clone.py --mirror    exists; makes the rewrite's mirror
  push.py, fetch.py    exist
  _facts               + per-ref snapshot (tip, tree, commit count, files)
                       + remote tips via ls-remote ("did the push land?")
                       + is_ignored, effective user.name / user.email
  _objects             every path, blob and commit record in a range: plain cat-file reads

Special/    one repository, with judgment
  rewriting history -- general, used by security and by the fleet
    _rewrite_rule      ONE rule type: filter-repo syntax and a Python apply
    _rewrite_plan      the plan record: versioned; the ref tips it was decided against
    _history_rewriter  the only place git filter-repo runs: plan -> mirror
    _rewrite_proof     the mirror matches its plan, and nothing else changed
    _commit_map        old ids -> new ids; quoted ids in text
    rewrite_history    mirror, rewrite, prove. Typed REWRITE, once per batch; no --yes
    follow_rewrite     prove nothing unpushed would be lost, then present: move now / later / by hand
    relink_ids         update quoted ids in a moved checkout
  security/
    _me                your values: discovered + your watch list + claimed (--mine); the header
    _material          tree / history / range readers over Basic._objects
    _contents          archive members, image metadata (carried from the old code)
    _checks/           registry + one module per check: secret shapes, personal shapes, your
                       values, commit identities, GPS metadata, gitleaks (external, optional)
    _findings          the report: what was checked, with which checks, at which ref tips, what
                       could not be inspected; masking
    _cleanup           pure: findings + _me + choices -> a rewrite plan
    scan_tree  scan_history (one repository or many)  scan_secrets
    watch_list         show / add / remove / edit (working name)
    plan_cleanup       findings -> plan folder + summary

Elaborate/  across time and machines
  security/clean_history   the top-level operation, below
  (fleet)                  the observer suggests follow_rewrite; catchup and archive_sync can
                           offer it for a clone they now call "diverged"
App/        shows clean_history's stage and the fleet's flags; buttons run the same commands
```

## `clean_history`

Runs the pieces in order, saves its stage after each, and resumes there when run again.

1. Scan, then `plan_cleanup`. **Stop:** names each plan folder, says what to read
   (`summary.txt`; `replacements.txt` holds the real values; Sourcetree, the files, or "have
   your LLM read the folder"), says it will wait, continues only on a typed word.
2. `rewrite_history`. **Typed `REWRITE`**, never skippable by a flag: an agent may prepare
   everything, only a person types it. Names the mirrors to inspect.
3. **Stop: the forced push is the person's.** Prints the commands, waits, then reads the
   remote's tips and continues only when they match the mirrors.
4. This machine: `follow_rewrite`, `relink_ids`, then commit and push through Basic after a
   typed `PUBLISH`.
5. Other machines: the fleet flags each clone; `follow_rewrite` there.

`follow_rewrite` always presents the situation to the person -- it never moves a branch
unasked -- with three choices: move now; leave it (it stays flagged); or do it by hand (it
prints the plain git commands).

## The watch list (today: `never_publish.txt`)

What exists today: nothing creates it. `Security/_seeds.listed_values()` only reads
`%APPDATA%\gitspecops\security\never_publish.txt` (Windows; `$XDG_CONFIG_HOME/gitspecops/...`
elsewhere). The agent wrote it by hand on 2026-10-19. Setup never mentions it, nothing shows its
contents, and the auto-discovered half (git and gh identity, host, home folder, tailnet, orgs)
is gathered fresh each run and never shown either. The hygiene test reads it too.

The rebuild:

- **A command** (`show` lists both halves in full, labelled by source; `add`, `remove`, `edit`).
- **Every scan prints counts**, never values: "discovered: 1 email, 1 login, host, 5 tailnet
  machines ...; your list: 6 values from <path>".
- **It applies backwards too.** Adding a value offers to scan your repositories' histories for
  it now; a hit is a `clean_history` job.
- **No "always publish" list.** The real need is a per-repository exception decided once (the
  Alpha contest constant was retyped as `--keep` every run); it belongs with that repository's
  scan record. gitleaks findings already have `.gitleaksignore`.
- **Stored locally by default.** Syncing it is a later opt-in through the private state
  repository, under the fleet key's rule: private only, re-checked before every write (as the
  peer already does), refused if public. A private repository is access control, not
  encryption: it adds as readers every token and app with access to it, collaborators, and
  GitHub itself -- for a list that is an index of what you consider sensitive.

## What GitHub does better (do not rebuild it)

Test: does the host enforce it server-side, where a machine without gitSpecOps cannot skip it?

- **Delegate:** secret shapes on push (secret scanning, push protection); your email on push
  (Settings → Emails → "Block command line pushes that expose my email"); force-push and branch
  rules (rulesets). gitSpecOps **checks that they are on**, through the provider, and points at
  the setting.
- **Ours, because GitHub cannot:** personal data (machine names, tailnet addresses, local
  paths, private org names, your list); history already published; other hosts; repairing
  history; each machine's git identity.
- Our secret-shape rules stay a small offline backstop for the hygiene test, not a product.

## Setup's security step

1. Identity from the pillars: `gh api user` gives login, numeric id and name; the noreply
   address is `<id>+<login>@users.noreply.github.com`. Show it beside `git config --global
   user.name / user.email`; offer to set it (confirmed). Repositories that override it are
   listed as deliberate, not errors. Only without a logged-in `gh` does it ask for a name and
   email.
2. Optional tools: git-filter-repo, gitleaks.
3. The watch list: show what was discovered, ask for what no lookup finds, show what it will
   write, write on confirmation.
4. The GitHub settings to switch on.

## The plan

Build beside the old code; the old code stays only because the hygiene test imports it. Compare
findings against the old tools on real repositories (this one, the Alpha set) by running them
from a temporary worktree of a pre-cut-over commit -- verification, not compatibility.

0. **Record** -- this document. Done 2026-10-20.
1. **Basic** -- done 2026-10-20: `reset_keep`, `commit`, the `_facts` additions (`ref_snapshot`,
   `remote_refs`, `would_track`, `identity_settings`, `next_commit_identity`), `_objects`
   (`file_versions`, `files_at`, `commits`, `read_blobs`), and `_run.stream` beneath it. One
   finding on the way: the old reader took paths from `rev-list --objects`, which names each
   object once, so a file whose content matched another's was never seen under its own name.
2. **Rewriting history** (Special, general) -- `_rewrite_rule`, `_rewrite_plan`,
   `_history_rewriter`, `_rewrite_proof`, `_commit_map`; `rewrite_history`, `follow_rewrite`,
   `relink_ids`. One gated end-to-end test on a disposable repository seeded with every case
   that broke on 2026-10-19: a `#` line read as a rule; a backslash in a replacement; a value in
   a file name; an old address under a second name; a noreply claim; same-second commits; an
   archive member; a GPS photo; a removed path; "nothing else changed". The observer's message
   then names `follow_rewrite`.
3. **Security components and scans** -- `Special/security/`, the watch list command, setup's
   security step. Findings must match the old scans, differences explained.
4. **`plan_cleanup`** -- same identity maps and rules as the old planner on the same repositories.
5. **`Elaborate/security/clean_history`** -- rehearsed end to end on a disposable copy of a real
   repository, stopping before the forced push.
6. **Cut-over, one commit** -- delete the live `Security/` (including `_rewrite.py` and
   `rewrite_history.py`) and `tests/security/test_security.py` -- never `_archive/Security/`; the hygiene test imports
   `Special/security`; `Security` leaves the import order; this document, the architecture
   document, the brief and the handoff updated.

## The owner's rulings: what counts as a leak (2026-10-22)

Given by the user after cleaning another public repository with the old tools. They answer the
parked "never / watch" question more simply than levels did: each finding is a **leak**, a
**quiet** note, or **safe** -- and these are the defaults the rebuild implements.

- **Safe -- never a finding:** the GitHub login, alone or as `<login>@<HOSTNAME>`. It is the
  public handle: mod headers, `@github` URLs, commit names.
- **Leak:** the real email address. Old commits already carry it and that cannot be undone;
  nothing new may add it. Flag it in files and in commit identities.
- **Leak:** the Windows home-folder name (the `Users\<name>` segment of a home path) -- close
  enough to the email to identify him.
- **Quiet:** other local paths (a library drive's `Github\...` folders) -- report quietly or
  ignore. This repository's own brief still forbids absolute local paths in its tracked files;
  whether the ruling relaxes that is an open question to the user.
- **Leak -- a new kind of check:** text that *describes an open leak*: a support-ticket number,
  "commit X is still served", instructions to go and look at a SHA. It holds no personal value,
  so a value scanner passes it; on 2026-10-22 an agent pushed exactly that to a public
  repository. Rule: in a public repository, flag security-state wording (leak, scrub, purge,
  still served, support ticket) near a commit id. Checked the same day: this repository holds
  none -- only general guidance.

**A safe list**, requested the same day: `<config_home>/security/safe.txt` beside the
never-publish list, one value per line, never a finding in any scanner; `--safe VALUE` for one
run. And **one answer from every scanner**: today `scan_tree` flags the owner's login (257 times
in one repository, all mod headers) while `scan_history` drops the repository owner and flags it
0 times. In the rebuild this is one rule in `_me`, applied by every check.

## Open

- The watch list: superseded by the rulings above -- the never-publish list holds leaks, the
  safe list holds safe values, built-in kinds carry the ruled defaults.
- Syncing the watch list (later, after a machine is enrolled).
- Three plan folders from 2026-10-19 13:01-13:07 remain in the per-user `security/` folder,
  holding real values; they predate the output folder and nothing uses them. Delete on the
  user's word.
