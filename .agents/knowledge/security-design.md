# Security: the rebuild design

**2026-10-28 user ruling:** the updated product contract takes precedence over this historical
design's deferred-policy and Gitleaks-only wording. Keep the stdlib core; Gitleaks, Betterleaks
and TruffleHog are optional independent adapters, including an explicit none selection. Master
policy plus additive machine-local policy must be portable at the selected owning scope.
Default findings must be actionable without raw values; present produced artifacts explicitly.
Direct scripts, `gitso` and GUI share manual scans and automatic supported-action checks.
Do not treat a reveal flag as agent isolation or faster transport as permission to share content.
This ruling does not authorize installation or actual user-history/settings changes.

**2026-10-29 disposable native repair proof:** general rewrite helpers are grouped under
`Special/_history/`. Basic/_history_read performs bounded raw reads with content-address checks;
native.py builds exact models without log/mailmap message normalization. plan.py explicitly
saves private versioned choices bound to source refs and symbolic HEAD, with a random visible id
and private alteration digest. Existing private JSON storage is reused; there is no fallback.
operation.execute requires typed REWRITE plus the exact plan id, then creates a new independent
mirror through Basic.clone(no_local=True). It never rewrites the source or publishes.

rules.py supplies the same literal transform to fixed callbacks and proof. No raw input becomes
Python code, regex replacement syntax, a rule-file comment or a delimiter. File-info handles
kept object contents and renames; the commit callback separately handles deletions once.
Exact identity pairs preserve other contributors. The child keeps fresh-clone checks, empty
commits and merge topology; it disables automatic commit-message hash substitution. Those choices
follow the [upstream manual](https://github.com/newren/git-filter-repo/blob/main/Documentation/git-filter-repo.txt).
The public clean-history adapter owns attended typed approval; no force option is exposed. Private plan/native-run/proof artifacts
stay in the explicitly selected new workspace; failed workspaces are retained without retries.

The executor runs read-only integrity checks, compares every selected reachable commit, ordered
parent, identity/date, ref/tag and retained historical tree path/mode/blob, then rechecks source
refs/model. Fixed callbacks and content-address-verified independent source/result readers are
now exercised natively, beyond the earlier pure model tests. Real disposable active scans show
archive/GPS/binary removal across renamed former paths and no remaining actionable findings or
gaps from the selected built-in checks. All seven commits/four refs, collaborator/timezone,
messages and retained content remain; purged objects are absent from the resulting object store.
A second native case verifies one-pass rename/deletion and real Git symlink mode/content with
core.symlinks=false, without OS symlink privileges. No publication clearance is granted.

Current native scope is attached branch/tag history with portable UTF-8 records, plus explicitly
included remote-tracking refs and their exact symbolic aliases. Other private ref namespaces,
non-commit targets, signed/unknown headers, gitlinks, shallow/promisor/alternate/grafted
stores and custom repository/config redirects refuse rather than infer or discard. Counted
safe.directory trust settings are preserved, not confused with redirects. Larger histories,
other OSs, nested-tag execution, broader encoding/signature handling and full GUI/finishing
composition remain acceptance work. The archived v1 tools stay frozen. This proof does not
erase external copies or authorize changing actual repository history.

**2026-10-29 public cleanup and remote-ref boundary:** Special/security/clean_history.py and
gitso clean-history share _cleanup.run_cleanup. The plan command accepts a full private history
report and explicit choice JSON: literal path removals, finding-id replacements, whole containing
file/container removals and exact author/committer/tagger identity choices. It rereads the current
material and verifies report refs and selected evidence; it never treats a finding as a purge
instruction. No raw protected value is needed in the choice file. Source scan id, masked choices,
scope counts and actual artifacts are returned, with raw evidence staying in private state.

The saved schema-two plan binds policy revision, selected profile/mode, effective engines and
source refs/symbolic aliases. Apply requires that same selected profile, exact plan id, a new
workspace and attended typed REWRITE; no unattended/confirmation flag bypass. The callable
operation is the GUI seam, but GUI controls are not built here. Missing/changed settings, stale
refs/findings, exclusions and required report/log failures refuse rather than choose defaults
or another destination. Policy is reloaded before/after native execution and after rescan.
Common output/format/report and counts-only logging preferences are honored; help creates none.

Explicit remote inclusion selects all current tracking refs, including commits reachable only
there; no fetch is performed. filter-repo's --partial disables its implicit origin-to-heads
conversion. The rewriter still processes every supported ref; none is silently excluded. Basic
restores planned symbolic aliases after clone/export and checks their exact target identity,
not merely the resolved commit. After full graph/content proof, Basic maintenance disconnects
the private clone's origin configuration without deleting tracking refs, expires only that
mirror's reflogs and prunes its old objects. Integrity/model checks run again. Source config,
refs, working files and index remain untouched. This is not a partial-history publication.

The cleanup rescans the proved mirror under the same policy/selected engines, writes a full
private rescan and returns verified, review-required or incomplete distinctly. A selected
unavailable engine or retained binary coverage gap cannot yield verified. Failed/interrupted
runs present actual created private artifacts; no publication clearance is granted. Scoped
example reviews remain repository/content bound and do not automatically transfer to a mirror.
Following/relinking histories, renaming/removing refs and publication remain separate work.

**2026-10-29 scoped review/report evidence:** the report writer supports explicit private
storage outside Git; inside Git it requires an ignored, untracked target. `_private_files.py`
owns exclusive creation, link/traversal checks, bounded strict JSON and partial-file cleanup.
`review_finding.py` / gitso review-finding preview and explicitly save/revoke one content-bound
example decision through `_review_operation.py` and `_reviews.py`. Decisions never add a
global safe value. Full reasons/evidence and byte digests stay private; accepted findings remain
visible in masked records. The common reader/checks apply these records to exact matching
repository/location/content; policy revision includes decision/revocation changes for commit,
push and advice rechecks. Strong/prohibited findings, external-engine findings and coverage
gaps cannot be waived. Local records are operational state, not shared settings/fleet payloads.
See product-contract.md and settings-schema.md for the current contract; GUI review, deliberate
cross-machine transfer/relocation and native permissions remain separate acceptance work.

**2026-10-28 implementation evidence:** Special/security/_push.py now composes selected policy,
the active outgoing-range reader and optional engines with Basic.fetch and a fixed-tip,
single-branch Basic.push.push_snapshot. Archive Sync publish is the first publishing caller.
Special/commit_repo.py and gitso commit now use the checked named-file operation in _commit/:
read-only exact-plan preview, raw/staged/final-hook checks, preserved unrelated staging and
traditional hooks via a temporary relay, and explicit partial state after uncertain execution.
No persistent hooks/config are installed. As of 2026-10-29, Special/push_repo.py / gitso push
provide the direct publication route through the same gate, with policy-bound local planning.
Sync check and the explicit local dashboard security action share working-tree/cached-outgoing
advice; results stay outside fleet manifests/reports. Continuous advice, recovery/hygiene,
remote attended actions and full GUI commit/push remain unfinished.
High-confidence classification and check_status are shared by reports and both gates.
See product-contract.md for supported mappings, refusal states and concurrency limits;
working notes/log contain the disposable tests rather than a claim of global enforcement.

**2026-10-26 integration direction:** [product-contract.md](product-contract.md) is the newer
contract for remembered output settings, explicit destinations, local revelation and security
alongside sync advice and commit/push actions. The active read-only scanner is a draft; the
phase-one-only status below describes the earlier design checkpoint, not current completion.
Keep this design's layer boundaries and frozen archive. Current executable tasks and remaining
cutover/proof work are in [working notes](../WORKING-NOTES.md).

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
