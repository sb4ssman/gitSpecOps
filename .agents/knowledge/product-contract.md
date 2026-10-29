# gitSpecOps: one application, useful individual operations

Status: product direction agreed with the user, 2026-10-26. This is the canonical contract
connecting the existing [layer architecture](architecture-layers.md),
[security design](security-design.md) and executable work in [working notes](../WORKING-NOTES.md).
It describes required behavior; it does not claim the unfinished pieces already work.

## Decisions refined with the user, 2026-10-28

These decisions supersede older open-choice and deferral wording in this document and the
supporting security/tier designs. Record implementation evidence in working notes and the log.

- **Simple core, optional integrations.** Keep understandable Python blocks, stdlib wherever
  possible, using already available/authenticated Git and host CLIs. Credential engines are
  independent optional integrations: Gitleaks, Betterleaks, TruffleHog, any selected combination,
  or none. None is a valid configuration, not an installation error. Built-in privacy/policy
  checks remain useful. An explicitly selected unavailable/failed engine is incomplete checking,
  not an excuse to fall back silently or declare equivalent coverage. Never install an engine
  merely because help, scanning or an agent discovers it. Validation against credential
  providers is separately selected; ordinary checks do not test captured credentials online.
- **Three equivalent entry routes.** Direct operation scripts, the common `gitso` launcher/menu,
  and GUI buttons invoke the same callable operations and policy. `gitso` is the selected name;
  gitSpecOps remains the product name. Direct scripts remain supported.
- **Manual and automatic security.** Users may explicitly scan through any route. Supported
  commit/push actions automatically invoke the same policy checks over exact proposed/outgoing
  material. Explicitly prohibited values/high-confidence credentials block supported publishing
  actions; uncertain findings warn and require the appropriate reviewed choice. Required check
  failures/incomplete results cannot authorize publishing. Read-only advice remains available
  with visible alerts. Removal and rotation are distinguished from introducing prohibited values.
- **Actionable without raw values.** Default records include finding id, check/reason, severity,
  masked location, line/object/reference where available, coverage and useful remedy guidance.
  A human or agent can locate/review/prepare remediation without copying the secret. Do not put
  a raw-value hash into public records as a substitute for masking. Human local revelation is
  deliberate and independent of log/report/fleet disclosure; a reveal command captured by an
  agent is not an isolation boundary. Present actual artifacts produced: text interfaces show
  their destinations and purpose, structured results list artifacts, GUI offers appropriate
  local open/view actions. Sensitive artifact paths also obey presentation policy. No silent
  report/log creation or raw report content in a notification.
- **Archive membership choice.** Registration is separate from launchers/schedules. Default
  discovery considers direct children; recursive/nested discovery is explicit and previewed,
  recognizes .git files/directories and respects exclusions. A registered collection can service
  only its recorded repositories or watch for new additions. Detection presents candidates;
  automatic membership requires a separately configured standing choice. New membership does
  not itself permit capture, publication or mutation beyond existing action consent.
- **Portable behavior and shared policy now.** Portable gitSpecOps behavior/security preferences
  are part of the supported design immediately, not an indefinitely deferred convenience.
  Maintain a fleet/shared master policy plus additive machine-local policy in the one local
  settings document. Effective blocks accumulate; local exceptions cannot silently weaken
  master blocks. Conflicts require explicit resolution at the owning scope. Discovered local
  identities supplement policy. Machine paths, executable locations and installation bindings
  stay local. Shared policy can contain sensitive values: transport only explicitly selected
  sections over the user's selected private conduit, with revision/ownership/conflict checks;
  never publish credentials, full findings or the entire local profile as shared preferences.
- **Complementary conduits.** A controlled private Git state repository provides durable
  coordination; a selected private synced folder/notes location (for example an existing file
  sync service) can exchange status more promptly without per-update Git pushes/pulls. Keep
  human-readable status notes clean, concise and derived from the same structured state; no
  second editable authority. Users may choose either or both. Tailscale supplies a separate
  optional direct peer conduit and supported command protocol, not arbitrary shell execution.
  Explain latency, availability, access and content-sharing tradeoffs. Faster transport does
  not silently enable recovery/content capture or unsaved-buffer access. No provider SDK,
  notes application or sync daemon is installed as a side effect.

The accepted direction authorizes source implementation and disposable verification in bounded
batches, preserving existing work. Actual user settings/launcher changes, engine installation,
history replacement, commits, pushes and publication retain their separate execution boundaries.

## Purpose and composition

**Support policy (2026-10-29):** the user chose one current design, without backward-
compatibility requirements for old commands/implementation paths. Replace superseded code,
remove obsolete adapters/fallbacks and document current behavior directly. Preserve saved
data/live configuration; any necessary data conversion is explicit setup work, not permanent
runtime guessing. This is source cleanup, not a request to rewrite Git history or activate
installation/migration. Apply it to each operation family as its current implementation is proved.

The primary outcome is seeing which repositories are out of sync across the user's machines
and putting them in order. The org duplicator came first, followed by archive updating and
cross-machine observation. Security scanning and history repair serve those operations and
remain useful operations themselves. They belong to one coherent product, not separate silos.

Keep Basic -> Special -> Elaborate -> App and the existing import direction. Basic performs
plain Git/host operations. Policy and composition live above it. The optional app assembles
the same callable operations available to terminal users; it must not have a second engine.
Each Special operation remains usable independently. No dependency on a shelf, agent shape,
shared agent toolbox or fleet enrollment is imposed on the product.

## Participation and interfaces

The app invokes the same importable operations headlessly and renders their structured
results/progress; CLI scripts are adapters over those operations. Do not build a second GUI
engine or require parsing interactive output. Human and LLM use share the same explicit scope,
plans, effects and result vocabulary. Ordinary pulls/pushes stay easy; rare operations have
especially clear prerequisites, review, resumption and proof.

The user endorsed a single CLI/main-menu front door as well as the GUI. It dispatches the
same headless functions, with interactive selection only in an interactive terminal and
explicit commands/structured output for automation. One static command catalog should supply
discovery, help and menu metadata without executing operations. The selected launcher name is
`gitso`; this is not a claim it is already implemented or installed. The dispatcher does not become a
second settings/policy engine. Direct operation scripts remain supported.

Source documentation is required, not a separate hand-maintained description of each tool.
Every script/module begins with essential purpose/usage documentation. Public commands cover
prerequisites, inputs/options, output/state locations, effects/approval, examples and meaningful
failure/exit behavior. Private modules document their internal role rather than invent a CLI.
Important callable functions document inputs/results, preconditions, side effects and errors,
with type hints where useful. Keep those descriptions true when behavior or paths change.

CLI help, menu descriptions and generated documentation should derive from these module/function
docstrings, real parser definitions and declared effect metadata. The command catalog maps names
to real handlers/parsers; do not duplicate long descriptions in a second registry. Extraction
must not execute operations, read private settings, initialize logging, authenticate or install
anything merely to build help/docs. Check public command discoverability and metadata/doc parity
as an interface contract. The documentation generator/header audit is not implemented yet.

The [2026-10-27 architecture ruling](architecture-layers.md#2026-10-27-ruling-operations-visible-plumbing-in-private-folders)
keeps action-named public scripts at layer roots and implementation in private folders. It
revises the physical organization without changing the layers; exact migration stays reviewable.

The user's local archive-management front door is Special/archive_manager.py: select/register
collections, invoke the selected update or sync operation once per archive and return results through the
same callable entry point used by CLI/GUI. Plain local management is Special; scheduled and
cross-machine coordination remain Elaborate and call it. Registration recognizes valid Git
collections separately from whether each checkout is currently eligible for an update. Public
versus private ownership is not an operation selector. Personal fleet synchronization remains
distinct from maintaining an archive's upstream repository set; the `sync_self.py` name is open.
The manager is a pathway to both direct archive operations. Its request/results identify the
effective operation; per-archive settings and explicit invocation choices preserve the same
scope and approval requirements as direct use.

| Participation | Capabilities added | Required context |
|---|---|---|
| Basic | Repository facts and individual Git operations | Explicit target, Python/Git for source use |
| Special | Local archive management/updating, duplication, inventory and security scans | Optional component preferences; selected operation's prerequisites |
| Elaborate: configured machine | Remembered machine scope and scheduled work | Local identity, paths, exclusions and accepted permissions |
| Elaborate: durable fleet | Cross-machine status and suggestions when peers are offline | Chosen private state-repo or folder transport |
| Elaborate: selected live/recovery features | Live peer state, approved remote actions, recovery capture | Chosen connectivity and separately accepted storage/access |
| App | Tray/menu bar, dashboard and notifications over the same capabilities | Desktop installation and capability detection |

This is increasing participation, not a compulsory ladder. A local-only app remains useful.
Transport/recovery choices have distinct access, data-sharing and freshness tradeoffs, which
setup must explain. A repository-local agent workspace remains self-sufficient. Do not infer
extra authority from opening that workspace: access controls, permitted tools and deliberate
data exposure enforce isolation. Sensitive policy can be consumed programmatically without
returning its raw values to an LLM; local human revelation is a separate channel.

## Setup, enrollment and remembered context

- A person may casually update public archives using Git alone. Do not require a state repo,
  GitHub CLI, SSH, Tailscale, notes integration or the app unless their selected operation needs it.
- Component setup can save roots, output preferences and other relevant defaults independently.
  Machine enrollment adds only the ecosystem capabilities the person selects. These are
  capabilities to combine, not compulsory onboarding tiers.
- Enrollment establishes machine identity, local path bindings, available runtimes/authentication,
  selected transports and integrations. Show what is configured and what remains unavailable.
  Git/gh/SSH authentication stays with the user's existing tools; do not store credentials here.
  Checking or guiding setup does not authorize installing software or changing authentication.
- An optional private state repo can carry selected shared configuration, status and coordination
  records. Private storage is not permission to replicate raw findings or credentials. Distinguish
  portable ecosystem preferences from machine-specific bindings and local sensitive records.
- Tailscale and SSH are selected capabilities, not universal prerequisites. SSH availability
  does not replace the agreed fleet peer protocol with arbitrary remote shell execution.
- Optional notes integration means a selected private synced-file conduit and readable fleet
  status notes as defined above. Reuse existing transports; do not invent a mandatory service.
- CLI options override saved preferences; saved preferences override documented defaults.
  Specify the shared/component/machine preference merge and versioned schema before implementing
  them. A configured user should not repeatedly supply the same paths or choices.
- Setup is repeatable and preferences remain editable from CLI and app. Clones, forks, moved
  checkouts and eventual installed builds keep code location separate from runtime data.
  Existing same-account checkouts share the current user config unless explicitly separated;
  do not silently create or migrate profiles. Code updates must preserve user settings.

### Guided setup and lifecycle

Setup is the guided front door, with an explanation of the participation matrix and these
actions: guided setup, select a setup item, update gitSpecOps itself, and uninstall. Each
component remains selectable independently. Explain prerequisites, paths, data sharing and
changes before acting, offer cancellation and keep preferences editable afterward. CLI
actions must also be explicit/non-interactive where requested, so an LLM can assist without
driving prompts. Help and an unattended invocation without a selected action must not perform
setup. Bootstrap selection plus guided/reviewed standalone updater preferences are implemented.
Legacy mapping has a read-only preview. An explicit archive/policy-only use-existing-settings
action now preserves originals and supports reviewed save/status/resume with a separate launcher
plan. General fleet conversion remains unavailable. Fleet/state enrollment, source updating and
uninstall remain separate work.

Enrollment includes guided optional creation or selection of a private gitSpecOps state repo:
use existing gh authentication, show the account/name and purpose, obtain the explicit choice,
verify privacy/access and configure only that selected repo. Reuse existing fleet setup's
create/use flow through the common settings contract rather than create a competing wizard.
Update targets only the gitSpecOps code checkout, never registered archives or user repositories.
Uninstall supports individual component unenrollment as well as app removal. Show what will
stop watching/publishing/running at login and remove only owned installation artifacts, with
receipts and a reviewed plan. Preserve repositories, settings, logs and recovery data by default;
deleting a state repo or user data requires a separate explicit choice. These full lifecycle
actions remain implementation work; no install/update/removal is authorized merely by launch.

### Local data and settings layout

User data belongs in an obvious per-user directory outside the source checkout. The earlier
phrase "user gitSpecOps root" meant that directory, never an org container or Git checkout.
Keep local logs with that data by default. Setup may select a different location and support
a later deliberate move; it must not leave competing active copies or silently migrate data.
The existing `Basic._paths.config_home()` and `GITSPECOPS_HOME` already provide an external
default/override; reconcile component-specific overrides without breaking existing setups.
Untracked agent notes may describe the chosen location, but CLI and app need a programmatic
locator independent of those notes. Decide any persisted GUI locator before implementing it.

**Settled by the user, 2026-10-26:** use one local configuration document with component
sections, including scope, output/logging and security preferences where appropriate. Its exact
schema and migrations remain work. Separate a policy file only for a concrete access/lifecycle/import reason; the
existing never-publish/safe files must remain readable until a reviewed migration. The previous
two-main-documents/two-policy-files suggestion is superseded. Initially the
private state repo can carry status and explicitly shared portable behavior/security preferences.
The 2026-10-28 ruling requires portability as part of the product, with revision, ownership,
conflict and privilege rules. It does not require fleet enrollment for local settings. Do not
synchronize the whole local data directory as configuration.

The implemented [settings schemas/resolver](settings-schema.md) preserve common v1 and add typed
v2 machine/transport/component records, a read-only migration preview and explicit validated
writer. Common/component/explicit preferences retain provenance. The standalone Archive Updater
consumes resolved settings; the manager/registry use common archive choices when present,
with receipts kept separate and new launchers resolving current choices. Manager refresh now
uses a headless aggregate result and common output/logging; registration/scheduling and direct
legacy sync output remain separate adoption work. Active scanners consume common security policy; fleet CLI/app readers and savers
now use common enrollment while retaining legacy-only profiles. Other policy consumers,
cutover ownership and live migration remain open. No actual machine/
fleet settings were migrated and no enrollment capabilities were activated.
That document records strict validation, privacy, revision checks and remaining cutover work.

### Updating the source and installed app

The user wants source checkouts updated through Git fast-forward-only, invocable from CLI,
setup or app. Keep settings/logs/recovery data outside the checkout so updates do not compete
with runtime writes. `Basic/pull.py` already supplies the plain Git operation; setup currently
has no source-update action, and version checking only reports availability.

The product updater must verify the selected checkout, clean state, attached/tracking branch
and chosen remote before execution, preserving fork tracking choices. Refuse divergence or
dirty state; never stash, reset, switch remotes or resolve conflicts automatically. Define how
the app/peer stops and restarts so running code is not mixed across revisions. Platform shell
wrappers may bootstrap the update, but share one operation/contract with setup and app rather
than three implementations. A frozen desktop bundle needs its platform release-update path;
pulling a source clone alone does not replace that bundle. No updater has been implemented.

## Output and file writes

**2026-10-29 archive evidence:** Special/archive_manager.py and direct archive-sync use
Special/_archive/operation.py. Each saved manager update/sync mode runs through the shared
runner; update is Git-only and sync can discover/clone approved missing repositories. Direct
requests also support explicit origin/folder repairs and exclusive policy-gated publication.
Registration has no separate mutation pipeline. Elaborate handles scheduling only, with newly
generated launchers invoking the Special manager.

The runner returns one masked result with per-archive operation/exit/effects, plans, actionable
security findings where applicable and actual artifacts, without printing or replacing process
stdout. Updater results also list actual report/log artifacts. Optional exclusive reports and
shared event/counter logs honor settings/CLI choices; file-only CLI output announces artifacts
on stderr. Direct archive-sync defaults to preview/stdout; unattended mutations need --yes.
Required sinks fail without fallback. All selected scope is checked before effects; state,
origins and targets are rechecked before mutation. Interrupted publication retains completed
push records. No automatic rollback, setup conversion or live launcher/task regeneration.

Scan-only makes no receipt writes. Actual run receipts retain status/time but do not guess
report pointers; report/log locations belong to the returned invocation artifacts. The status
view reads saved historical report metadata rather than scanning for a latest filename. File-
only output announces actual artifacts on stderr. Empty selections still honor requested
output/logging without creating registration receipts. Master and machine-local blocked
values both protect updater/manager presentation; URI userinfo masking covers SSH and other
schemes as well as HTTP. Explicit output/log paths retain lexical spelling until link checks,
instead of resolving away aliases first. Native symlink creation was unavailable in the
Windows trial; that test is explicitly skipped, not a cross-platform proof.

Registration/launcher coupling and registration/scheduling lifecycle logging, other consumers
and full GUI/native acceptance remain unfinished.

- Without a saved output preference or explicit output option, inspection/report commands print
  to stdout without creating report files. This does not change the Git effects of an updater
  or other operation the person invoked.
- A user may configure stdout, file output or both, including a directory in their account.
  A saved choice is intentional behavior, not a fallback. A command can override the saved choice.
- Machine-readable stdout contains only the promised record/stream, without banners, progress,
  trailing summaries or prompts. Diagnostics and progress go to stderr. Interactive presentation
  remains readable. Results have a documented schema and exit status.
- A configured destination that is missing required setup, unwritable or otherwise invalid
  produces an error. Never silently switch to another directory or output mode. Define directory
  creation, filename generation, overwrite/append and partial-result behavior explicitly.
- Full security reports may use an explicitly selected private directory outside Git. Inside
  a repository they must remain untracked and ignored. A dot-folder or external path alone is
  not proof of privacy. The writer now supports explicit external storage, refuses links,
  traversal/bare repositories/tracked or unignored targets, and exclusively creates complete
  reports with actual artifact records. New POSIX files/directories use owner-only modes;
  Windows uses the selected directory's existing ACLs. No permission changes or fallback.
- Settings, fleet manifests/catalogs, recovery bundles, resumable operation records, approved
  rewrite plans and requested installers/launchers are operational state, not optional reports.
  Give each explicit ownership, location, lifecycle and visibility; do not remove required state
  in the name of stdout-only output. Do not write runtime state beside installed source code.
- User-controlled operational logging is distinct from a full report. The old raw tray tee
  was removed on 2026-10-29: console output is forwarded only to its original display, with
  a generic error flag for the icon. Explicit local disclosure must never automatically copy
  values into logs, shared state or notifications.
- Use Python's existing logging infrastructure with one configuration seam and named component
  loggers. Entry points resolve settings and configure destinations/levels/rotation; lower
  operations emit events without independently rediscovering settings. Support selected
  multiple sinks, per-component routing and no-log overrides. Handle concurrent CLI/app writers.
  The standalone updater and native tray now use the shared event/counter logger. Tray logging
  uses common app preferences and app_tray.log under the selected logging directory, respects
  disabled logging and errors instead of choosing another sink. Legacy-only profiles have no
  old logging preferences to convert: documented defaults use the selected user-data home,
  without converting enrollment. Invalid common settings cannot select those defaults.
  Neither consumer captures stdout. Other consumers, multiple sinks and complete artifact/UI
  presentation remain adoption work; native tray lifecycle changes still need visual/OS proof.
- Unconfigured, unavailable, stale, failed and checked are different states. An unenrolled
  standalone user has no missing-fleet error. Offline peer information may coexist with useful
  local results, visibly stale/unavailable. Never represent failed checking as a clean result.

## Security in the normal workflow

**Current supported action slice (2026-10-28):** Archive Sync's explicit publish action captures
the planned branch/tip/single destination, loads common or explicitly selected legacy security
policy, fetches the selected remote, queries the actual destination base and checks exact
base..tip material. It reuses the active reader/checks/optional engines, including history that
introduced then removed a finding. Master/machine prohibited values and strong credential
patterns block; uncertain candidates require review; gaps/failures hold publication. Quiet
notes alone do not block. Resolve policy at its owning scope and rerun; action approval such
as --yes is not a security override.

**Scoped example reviews (2026-10-29):** review-finding previews one candidate from an explicit
full private report. The exact current plan id is required to save/revoke a decision under the
selected profile; preview writes nothing. Built-in uncertain findings can be accepted as
examples for one repository/check/location/line/value/occurrence and complete checked content.
Context kinds distinguish content, paths and metadata; Git metadata also binds its object id.
Path reviews bind their file bytes; archived findings bind the complete archive bytes. Binding
digests and reasons remain private; finding ids stay report-local, while scan/review ids are
random. Plan ids bind the whole proposed decision/report/profile/policy, not just a raw value.
Accepted findings remain visible and do not enter global safe-values lists. Complete byte
changes, including invalid-UTF-8 changes with identical decoded text, invalidate acceptance.
Reverting to exact accepted content can reuse that decision. Prohibited identities, strong
credentials, unsupported external-engine findings and coverage gaps cannot be waived.
Explicit never-publish matches also take precedence over a larger enclosing safe value;
global allowances cannot hide a prohibited substring.

The common scanner annotates matching reviews for tree/index/history/proposed/outgoing material;
commit/push/advice reuse that result. Decision and revocation changes participate in the
shared policy revision, so old action approvals cannot silently reuse changed review state.
Unreadable/corrupt/unbounded records are incomplete, never absent defaults. Excluded report
inputs are refused before reading; excluded review storage is neither read nor written.
Immutable private decisions/revocations contain UTC time and reasons, never ordinary logs or
fleet state. This is local operational evidence; GUI review, deliberate cross-machine transfer
and repository relocation/import remain separate acceptance work.

An explicit scan-tree --staged reads changed-file index bytes without staging, filters or
working-file writes. Its private report can supply a separate review when line-ending or clean
filter conversion changes previously reviewed working bytes. Re-preview the checked commit
after review; changed/unmerged index snapshots and coverage gaps still hold actions. Deletions
and historical versions are not scanned by this staged view.

The headless operation is Special/security/_push.py; the policy-free primitive is
Basic.push.push_snapshot. It pins the commit id and branch, suppresses extra tags/mirror/
submodule pushes for that invocation, and preserves normal non-force Git checks and hooks.
Source, target and effective policy are rechecked before execution. A removed settings file
during checking cannot silently turn the action into a defaults-only pass. These rechecks are
optimistic, not an atomic lock against arbitrary external config/policy/remote writers.

Supported mapping is one endpoint whose upstream and push destination agree. Triangular or
multiple endpoints, absent remote branches/bases, transformed ancestry/partial coverage and
second-stage URL rewriting require review rather than a guess. A dry-run local plan performs
no security checking. Masked records/text explain actual outgoing findings and coverage; the
archive adapter retains its existing aggregate exit/report interface. Other publishing paths,
sync advice, universal output/logging and installed hooks remain integration work. Do not claim
system-wide prevention or full publication clearance from these supported actions.

**Checked commit slice (2026-10-28):** Special/commit_repo.py and `gitso commit` call the same
headless commit_checked operation. Preview is read-only, returns masked checking and a plan id,
and creates no Git objects/index, reports, logs or profile. Apply requires the exact current
plan id, binding named working-tree file bytes/modes, message, effective author/committer,
HEAD, staged manifest, policy provenance and traditional hook revisions. Basic.commit retains
named-file semantics: whole selected working-tree files, preserving unrelated staged work.
No amend, all-files, empty-commit, push or rollback behavior is added.

Raw inputs are checked before staging. Apply then checks actual selected staged blobs after
Git filters and rechecks through the native commit-msg point after existing hooks. A temporary
per-invocation relay preserves traditional hook order/rejection and the active native index;
no persistent hook/config change is made. Safe hook edits still invalidate approved contents
or message and require a fresh preview. The final stored tree, parent, message and identities
are verified. Refusal after staging retains selected staging; uncertain post-execution state
is explicitly partial with committed true/false/unknown rather than hidden or rolled back.
Raw native error output is private backend data, absent from normal text/JSON records.

Initial compatibility is Git >=2.36, an attached/unborn branch, explicit individual regular
files/deletions and traditional hooks. Directory/link/submodule selection, in-progress merge/
rebase, custom index/object/pathspec/history environments and configured hook chains require
review and are refused. Trusted hooks retain their own side effects; optimistic rechecks are
not a sandbox or an atomic lock against arbitrary external writers. Common logging/artifact
routing, complete GUI action integration and protection in other Git clients remain separate work.

**Local advice/direct push slice (2026-10-29):** Special/push_repo.py and `gitso push` call
push_checked over the existing publication gate. Local preview binds tip/branch/single target,
profile and effective policy without contacting a remote or claiming outgoing checking. Apply
needs the exact current id; policy is also compared at entry into the publication gate, before
fetch. Actual base..tip checking and fixed-snapshot publication remain the shared action.

Special/security/_advice.py provides local working-tree plus cached-outgoing advice, with
explicit timestamps, incomplete states and no action clearance. Sync `check` runs it for each
observed checkout without additional network access or saved reports/logs. Its JSON is now a
versioned local envelope (schema_version, manifest, local_security, artifacts), not the former
bare manifest. Only manifest goes to transports. Text retains all sync facts and adds security
status; a quiet Git row with a security alert must remain visible in the exceptions view.
Known common-profile snapshots are verified before/after advice; losing an enrolled profile
cannot turn checking into a fresh-default pass. These are optimistic checks, not atomic file
snapshots or proof that cached upstream refs match the remote.

The local peer dashboard's explicit security-preview action invokes that same function for all
locally observed copies of a selected repo id. It uses the existing loopback Origin/token
boundary, accepts no client-supplied path, presents masked records in session memory and
stores/shares no findings. Peer report/schema, watch publication and manifest-only views stay
separate from local advice. Automatic continuous advisory scheduling/invalidation, full GUI
commit/push, common output/logging and native visual/multimachine acceptance remain open.

- Separate protected-value policy from scope exclusions. Enrollment needs explicit roots plus
  hard path/repository exclusions applied before inspection, and distinct observe/publish/
  capture/action selections. Existing namespace baskets are not a universal no-inspection
  boundary. Explicit whole-machine discovery should support selected drives, depth, mounts,
  exclusions, cancellation and visible gaps; discovering a repository does not enroll it.
- Present security findings alongside sync facts. Dirty/ahead/behind status must not hide a
  security alert, and security alerts must not hide unfinished work. Include scope and freshness.
- The supported commit action checks the exact proposed file contents, message and identity
  before creating a commit. A push checks outgoing history, including a secret introduced and
  removed before the tip. The executing machine rechecks approved remote actions against current
  contents and policy. Cached dashboard results are not execution proof.
- Prevent introducing prohibited values; distinguish removal/rotation from introduction so a
  cleanup is not blocked merely because the old material contains the value. Define actionable
  block/warn/quiet outcomes, reviewed exceptions and incomplete-scan behavior explicitly.
- Reuse callable detection and policy across standalone scans, advice, action gates, recovery
  capture and repository hygiene. Recovery already has a credential screen; the active scanner,
  archived rules and hygiene guard are currently separate. Consolidation requires explained
  behavior differences and tests, not a silent rule replacement.
- Integrating checks in gitSpecOps covers its actions. Protection through other clients needs
  explicitly configured Git hooks and/or host controls; do not claim system-wide enforcement.
- Reuse established detection/filtering engines where appropriate; engine choice is settled
  as independent optional adapters or none. Native/version acceptance remains open.
  Personal-publication policy and orchestration remain product responsibilities.
  Detection does not rotate credentials or erase external copies of published history.
- Preserve `_archive/Security/` unchanged. Reuse its reviewed behavior and regressions through
  the agreed layered rebuild. History repair retains plan/review/approve/execute/verify stages,
  explicit destructive/publishing boundaries and disposable scan/rewrite/rescan proof first.

Current bounded repair implementation is `clean-history plan/apply`, shared by the direct
script, gitso and callable operation. A full private report plus explicit finding-id/path/
identity choices produces an exact private plan. Apply revalidates the same selected profile,
policy, refs and plan id and requires attended typed REWRITE into a new independent mirror.
Explicit tracking-ref inclusion preserves names, remote-only commits and symbolic aliases
without fetching. The source repository is retained; no follow/relink/publication is implied.
Common masked output/report and counts-only log preferences are honored, with no fallback;
all actual private artifacts are presented. After native proof, rescan gaps or unresolved
findings hold the result. No raw finding value is required in an agent's choice file. Full
GUI controls, unsupported ref/object handling and native other-OS acceptance remain open.

## Disclosure and consistent presentation

The person must be able to see exactly what is at risk. Show location, reason and useful
context, and support intentional local revelation in terminal and app without requiring a
report file. Masking changes presentation, never the source or what the detector checks.
Disclosure for local display, LLM-readable output, saved reports, logs and fleet notifications
is controlled separately; a reveal choice must not leak into another channel implicitly.

New-fleet CLI/app setup now hides its generated key. Both configuration routes provide
fleet-key (metadata/hidden key) and fleet-key --show (explicit raw JSON output here), through
one presentation helper with no logging or file writes. This is deliberate disclosure, not
agent isolation: an agent capturing that output receives the key. Carry it through the chosen
private joining channel, never public state. Independent local human GUI revelation remains
unfinished. The native tray does not tee even intentionally displayed console values to disk.

CLI, app and agent-facing records use the same results, status vocabulary, severity and action
plans. Reuse the existing console and app presentation infrastructure; standardize help,
progress, errors, output options and actionable explanations. Themes may change appearance,
not semantics or capabilities. Keep product UX free of internal agent scaffolding details.

## Delivery and evidence

Three finish lines guide the work: (1) an independent operation uses predictable local data,
output/logging and repeatable setup, with a source-update rehearsal preserving user state;
(2) useful security scans and action checks have known positive/negative evidence, with a
disposable scan/rewrite/rescan proving approved removal and retained content; (3) two machines
produce accurate fresh/stale fleet suggestions through the chosen transport, exposed through
the same CLI/app operations and then validated natively on each supported OS. These are
acceptance outcomes, not permission to execute previously deferred or destructive commands.

The ordered backlog and acceptance criteria live in working notes, not a parallel task list
here. Finish one bounded component at a time with focused evidence, then connect it upward.
Keep synthetic fixtures separate from real findings and validate on each claimed OS. Completing
this design does not complete the implementation or authorize installation, history mutation,
commits, pushes, guard changes or publication. Existing deferred verification remains deferred.
