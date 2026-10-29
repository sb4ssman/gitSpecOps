# Local settings: schemas, resolver, migration preview and writer

Status: common v1 plus typed enrollment v2, read-only migration preview and explicit writer
implemented, 2026-10-26; private archive preference/receipt adapters added 2026-10-27.
Product requirements are in
[product-contract.md](product-contract.md). The standalone updater consumes this reader;
the manager/registry adopt archive choices, and active scanners adopt common security policy.
Fleet CLI/app readers and savers adopt existing common enrollment as of 2026-10-28;
an explicit archive/policy-only existing-settings switch is now implemented and tested on temporary
profiles. Broader conversion, remaining output/logging adoption and actual settings switching remain
open. Resolution itself neither enrolls
machines nor configures log handlers. No actual settings migration has run.

Implementation: [`Special/_settings/__init__.py`](../../Special/_settings/__init__.py).
Typed enrollment records: [`records.py`](../../Special/_settings/records.py).
Preview and writer: [`migration.py`](../../Special/_settings/migration.py),
[`store.py`](../../Special/_settings/store.py).
Focused tests: [`test_settings.py`](../../tests/special/test_settings.py),
[`test_settings_migration.py`](../../tests/special/test_settings_migration.py).

The helpers are grouped under `Special/_settings/` as of 2026-10-27. Resolver/schema imports
remain `from Special._settings import ...`; migration and writer imports use
`Special._settings.migration` and `Special._settings.store`. Grouping does not adopt settings,
change their format or move user data. Importing these modules performs no settings I/O.

## Location and read behavior

### Use existing archive/security settings

`Special/_settings/existing.py` and setup provide a deliberately scoped switch for legacy archive
choices and protected/allowed-value lists. Profiles with CLI/app configuration or an alternate
sync-home override are refused here; the broad mapping preview remains read-only. No actual
user profile has been switched by this implementation.

```sh
python3 setup_gitspecops.py settings-existing
python3 setup_gitspecops.py settings-existing-plan --json
python3 setup_gitspecops.py settings-existing-save --approve '<review-id>' --legacy-writers-stopped --launcher-plan-reviewed --json
python3 setup_gitspecops.py settings-existing-status --switch-id '<review-id>' --json
python3 setup_gitspecops.py settings-existing-resume --switch-id '<review-id>' --legacy-writers-stopped --launcher-plan-reviewed --json
```

All accept a selected `--settings-home`. Plan and status create nothing. Default results expose
counts, modes, requirements and launcher classifications only. Plan's explicit `--show-paths`
also reveals the target, preserved-original location and numbered artifacts; it never reveals
policy contents or copied remote allowances. Guided setup requires a terminal and separately
typed STOPPED, REVIEWED and SAVE; cancellation before save creates nothing. Headless saves require
the exact plan id plus the same two attestations. Independent old writers/jobs must actually be
stopped; flags are the caller's attestation, not a process scan or an OS enforcement mechanism.

The plan id binds selected home, candidate settings, exact input bytes including absent sources,
and named launcher revisions. Changed inputs, new settings or changed launchers invalidate approval.
No preference edits, source upgrades, unknown legacy versions or unrelated setup actions are mixed
into this switch. Duplicate archive roots, source destinations, links and unencodable receipt
metadata are refused before writes. Named launchers outside their recorded archive require a
separate review rather than unrestricted filesystem inspection.

An approved save holds cooperating switch/archive locks and uses the shared settings writer:

1. Preserve original file bytes in `settings-switches/<review-id>/originals/` under the selected
   external user-data home. Candidate and manifest are separate operational recovery records.
   Files are exclusively created and flushed before any active change; a preexisting bundle is
   never replaced. These private copies are not runtime configuration or a settings sync export.
2. Mark an existing archive registry as receipt format v2, retaining every original record/field.
   This prevents a missing shared file from reviving old archive preference copies.
3. Create shared settings atomically only if its destination remains absent and all source checks
   still match. Policy text files remain unchanged. Other tools read the shared settings normally.

The files do not form an OS-wide transaction. Failure is explicit and retains the bundle; there
is no silent rollback or automatic deletion. Status validates originals/candidate/manifest against
the approval and reports saved, interrupted/resumable or needs-review. Explicit resume finishes
only unchanged original/receipt-only state with an absent target, or reports an exact completed
switch unchanged. It refuses newer settings, changed sources/artifacts or damaged backups. A
bundle interrupted before its manifest exists requires manual review; it is never reclaimed.

Launchers are a separate plan: each named artifact has leave/review/repair/retirement choices,
format, role and the existing command to prepare a repair. Per-archive repair goes through
`Special/archive_manager.py --install`; refresh-all through
`Elaborate/archive_manage.py --write-refresh-all-script`, using the selected profile. Neither
command is executed by the switch. Retirement needs ownership/caller review and separate consent;
archives and settings remain outside that artifact choice. Native launcher rollout, scheduling
review, general fleet conversion and global enrolled-profile settings-loss ownership remain work.

One `settings.json` lives under the selected gitSpecOps user-data home, outside the source
checkout. Selection is explicit caller `home`, then `GITSPECOPS_HOME`, then the established
`Basic._paths.config_home()` OS default. An explicit relative home is caller-relative; an
environment home must be nonempty and absolute. Existing OS defaults are preserved, including
the established XDG-style macOS path; no location migration occurred.

Paths inside settings are anchored to that selected home, never to the current source checkout.
They are returned as absolute Path objects. This is normalization, not an access grant or
filesystem usability check. The eventual operation still checks access, exclusions, destinations
and file-write policy. Reading settings creates no directory, report, log, key or enrollment.

An absent settings file on first use produces in-memory defaults only. A malformed, unreadable,
ambiguous JSON document, unsupported version or unknown field produces SettingsError; values
and paths are not echoed. Existing legacy configuration/policy at that home without settings.json
produces an explicit migration-required error, rather than fresh defaults that conceal it.
The new resolver never imports legacy settings automatically. Coordinated fleet adapters retain
legacy-only readers when no common document exists. `GITSPECOPS_SYNC_HOME` selects only fleet
state/legacy inputs, independently of the common profile; the adapter handles both explicitly.
The low-level resolver still refuses that legacy override unless its caller supplies an explicit
home. Other independent components are not redirected by a sync-only override.

## Document

```json
{
  "schema_version": 2,
  "defaults": {
    "scope": {"roots": [], "exclude_paths": []},
    "output": {"mode": "stdout", "format": "text", "directory": "reports"},
    "logging": {
      "enabled": true,
      "directory": "logs",
      "level": "INFO",
      "max_bytes": 10485760,
      "backup_count": 3
    },
    "security": {"never_publish": [], "safe_values": [], "local_never_publish": [],
                 "local_safe_values": [], "engines": []}
  },
  "components": {
    "archive_update": {
      "output": {"mode": "both"}
    }
  }
}
```

`schema_version` is required; common v1 remains readable without rewriting it. New previews
produce v2. Defaults/components/individual fields may be omitted. Known component identifiers
are archive_update, archive_sync, archive_manage, duplicate_org, inventory, security, sync and
app. Sections and fields are strict; a misspelling does not
silently behave like a default. Even an unselected component is validated.

| Section | Fields and meaning |
|---|---|
| scope | roots and exclude_paths: lists of paths; empty roots do not request a machine scan |
| output | mode: stdout/file/both; format: text/json; directory: report storage when enabled |
| logging | enabled: boolean; directory; level: DEBUG/INFO/WARNING/ERROR/CRITICAL; max_bytes: positive integer; backup_count: nonnegative integer |
| security | never_publish/safe_values: portable master lists; local_never_publish/local_safe_values: machine-only additions; engines: distinct gitleaks/betterleaks/trufflehog selections, empty means none |

The example shows complete built-in defaults plus one illustrative component override. Report
files are off by default. Local operational logging is the default preference, with 10 MiB
rotation and three backups; no logger is started by this reader. The standalone updater now
uses the shared logging seam described below; remaining component adoption/routing is open.
Reporting directory preferences do not themselves request file output or create directories.
There are no raw-value disclosure settings yet: channel-specific revelation remains separate
work. Security policy values belong in private local configuration, not tracked examples.

## Resolution and privacy

`resolve_settings(component=None, *, home=None, overrides=None)` applies:

1. Built-in defaults.
2. Saved defaults.
3. The selected component's saved settings.
4. Explicit invocation overrides supplied by the calling CLI/app operation.

Fields replace earlier fields except excluded paths and both never-publish lists, which accumulate.
An invocation can add exclusions/protected values but cannot clear inherited ones with an empty
list. Removing them requires an intentional change to their owning saved settings. Lists of
roots replace rather than accumulate, so selecting a narrower operation stays possible.
Exact case-insensitive overlap between safe and never-publish values is rejected as a conflict;
the reader does not silently choose precedence. Broader detector-specific exception semantics
still require the security-policy integration work.

### Portable master preferences and machine additions (2026-10-28)

`Special/_settings/portable.py` provides a pure projection and merge candidate over these
documents. `portable_settings(document)` returns a private carrier: summary/repr hide policy
values; `raw_record()` explicitly returns transfer data for a selected private conduit.
`merge_portable(local, record)` validates an incoming projection and preserves local fields.
Neither function reads/writes settings, enrolls anything or activates a transport. Actual
transport revision/ownership/conflict checks and guided export/import remain integration work.

The allowlist carries output mode/format, logging behavior/rotation, master security lists,
engine selections and selected path-free sync/app behavior. It excludes output/log directories,
scope roots/exclusions, machine identity/fleet key, transport credentials/locations, installed
tool/client bindings, archive registrations, recovery/capture consent and machine-local policy.
Incoming local-only keys are refused, not silently imported. Adding more portable options
requires deliberate classification, not exporting every future field by default.

Master blocks plus local blocks form the effective prohibited list. Allowances from either
scope cannot override a block from the other scope. Removing a master block changes its owner;
an imported candidate can express that removal but does not save it or claim approval. The
operation presenting/saving it must show that effect and use the existing revision-checked
writer. No automatic last-writer-wins synchronization or live profile conversion is implied.

### Optional credential engines and actionable scan presentation (2026-10-28)

Saved `security.engines` or repeatable scanner `--engine` selects integrations. None is the
default; `--engine none` explicitly overrides saved selection. A selected missing/failed engine
is incomplete coverage (exit 2), while no engine selected is valid built-in-only checking.
The current adapters cover the Gitleaks 8 / Betterleaks 1 stdin JSON and TruffleHog 3 stdin
JSON-lines protocols. Unsupported CLI/report versions are incomplete; native binary/platform
acceptance is not established by mocked protocol tests. Newer Betterleaks report/CLI versions
need their own protocol adaptation before being claimed supported.

Engines receive bounded batches of text already admitted by the material reader, including
selected metadata/archive text, through `Basic.stream` stdin. No raw input temporary files,
shell pipes, target-directory rescan or credential-provider validation. Errors/raw engine
stderr do not enter presentation records. A transformed/unmappable engine result is a gap.

Scan record schema v2 adds report-local finding ids, severity, remediation guidance, selected
engine states and explicit produced artifacts. Masked locations/line/object ids provide useful
agent context without full values; ids are not raw-secret hashes or cross-run authorization.
The trusted full-record/report path remains separate. Requested reports are listed after
successful creation; no implicit report/log/config is created by a scan. Wiring these records
to automatic action gates, the common `gitso` launcher and GUI remains executable backlog.

The result includes effective values and per-field source labels. It does not mutate input,
defaults or another result. Raw values are for trusted operations; summary() returns counts and
non-sensitive preferences/source labels without local paths or policy values. The dataclass repr
also omits paths and values. These presentation protections do not replace tool/OS access
controls, and callers must not dump raw values into logs or LLM-facing output.

## Typed v2 enrollment and component options

V2 adds optional top-level machine and transports records, plus typed options in selected
components. V1 rejects those fields instead of silently accepting an extension. Raw machine,
transport and option records are for trusted operations; the resolver summary shows only their
presence, transport names and option field names, never their values.

| Record | Preserved fields |
|---|---|
| machine | id, label, fleet_secret; all required when present |
| transports | folder: path, optional seconds; repo: name, optional seconds; tailnet: port, optional allowed_login |
| sync options | root_recursion, transport_names, stale_hours, expired_days, compress_manifests |
| app options | transport_names, fetch_minutes, share_names, baskets, recovery, observation_mode, debounce_seconds, heartbeat, inventory_notice_acknowledged, local_port, git_client |
| archive_manage options | archives: root, mode, approved_remote_prefixes per managed archive |

Machine identifiers/keys, transport definitions/selections, intervals, namespace baskets,
recovery confirmation/policies and desktop-client records are validated structurally. Selected
transports require definitions and a machine identity. CLI selection remains at most one
folder/repo transport; the app can select several from the same definitions. Per-component
roots remain in scope.roots, with CLI recursion retained in options.root_recursion. App roots
retain their existing recursive-observation meaning. No enrollment is inferred or activated.
Path availability, storage topology, authentication and host privacy must still be checked
when a component is actually started; schema validation is not permission to execute.

## Migration preview

`preview_migration(home, *, sync_directory=None)` reads only the explicitly located legacy
settings/policy files. It produces a private candidate, original byte fingerprints, a summary
and named conflicts. It never writes. An existing target settings.json blocks rather than
being merged or overwritten. A legacy sync-home environment override requires an explicit
sync_directory choice. Older/unknown source formats block; they are not silently truncated.

| Existing source | Required treatment |
|---|---|
| sync-suggester/config.json, version 1 | Identity into machine; transport definition plus sync selection; roots/recursion, freshness and compression into sync component |
| sync-suggester/fleet-app.json, version 5 | Identity into machine; multiple transport definitions plus app selection; roots, baskets, recovery, sharing, observation and UI preferences into app component |
| gitspecops_managed_archives.json, version 1 | Copy only archive preferences into archive_manage options; retain original installation receipts and last-run state untouched |
| security/never_publish.txt and safe.txt | Nonempty non-comment lines into common security policy; exact case-insensitive block/safe overlap is a conflict |
| catalog.json, fleet.sqlite3, manifests, snapshots, logs | Keep as operational state, not fields copied into settings.json |

Matching machine/transport records combine; disagreements block with field names but no raw
values. Distinct CLI/app roots and transport selections remain distinct; neither is silently
widened. Relative enrollment paths require review rather than being reinterpreted at a new cwd.
All source files remain unchanged. preview.verify() rejects changed/missing/new inputs, a changed
target or a modified candidate. Summary/repr omit candidate values and source paths.

## Explicit writer and remaining cutover

`write_settings(document, *, home, expected_revision=None, check_sources=None)` validates before
creating anything, uses the existing atomic-write primitive and locks cooperating settings
writers. None expects no target; replacing a file requires its exact previous byte revision.
Linked destinations/parents and storage inside this source checkout are refused. Errors do
not change destination. A failed replacement preserves the old file and cleans temporary state.
Successful save with failed lock cleanup is reported explicitly as saved-but-needing-review.
The returned revision identifies the bytes written. POSIX files use the atomic helper's private
temporary-file permissions; Windows permissions inherit from the chosen user's directory.

For a reviewed migration, stop legacy writers, show the candidate/conflicts through an
appropriately privileged interface and obtain the user's choice before invoking the writer.
Use preview.verify as check_sources for the last input check under the new writer's lock.
That lock does not control unrelated legacy processes; the source check is not an OS-wide
transaction or protection against a malicious directory writer. Existing old configuration is
not deleted, renamed or adopted automatically. The standalone updater consumes common settings;
the manager/registry adopt common archive choices when present. Active scanners now use common
security policy; fleet CLI/app readers and savers now adopt common enrollment. Other security-policy
consumers still await coordinated adoption.

Still open: general legacy activation/conflict UI, remaining record adapters and coordinated reader cutover,
explicit conflict choices, action-consent review, storage relocation/locator, remaining logging integration
and native OS validation. New settings preservation does not enable unattended actions or
complete source updating, enrollment or uninstall. Tests use temporary, invented fixtures;
no actual user settings were read or changed during this implementation.

## Archive preference/receipt adapter (2026-10-27)

`Special/_settings/archives.py` is an internal callable seam used by the manager/registry,
not a migration action. `load_archive_settings(home)` requires an existing common v2 profile;
missing/invalid/ambiguous/unsupported settings fail rather than falling back to legacy
registry preferences or upgrading v1. Selection and resolution reuse the common rules.
Duplicate lexical roots are rejected; path matching is platform-aware and does not inspect
repositories or resolve filesystem aliases. Operations still must enforce effective exclusions
and verify actual targets before inspection or action. Raw records stay in trusted callers;
`summary()` and the snapshot repr omit local paths, remotes, identities, keys and policy values.

`manager_view(snapshot, registry)` joins receipts onto the authoritative configured archives,
in configured order. Old receipt mode/prefix copies cannot override choices, empty allowed
prefix lists stay empty, and inactive receipt roots never enroll themselves. An absent/empty
archive preference list means none. Receipt formats/duplicates fail explicitly. Conversion
returns independent copies without reading/writing files or starting a logger.

`merge_archive_receipts(snapshot, registry, updates)` prepares operational fields only. It
retains inactive receipts, old preference copies and unknown historical metadata, preserves
first installation time, and adds no preference copies to new receipts. Unchanged unknown
metadata may round-trip; new/changed unknown fields and inactive/duplicate updates fail.
Registry persistence now uses this merge behind its cooperating-writer lock and source checks.

`save_archive_preferences(snapshot, archives, check_sources=...)` explicitly replaces only
archive choices using the common revision-checked atomic writer. It preserves other settings,
schema, receipts and launchers. Changed snapshots/targets fail, a semantic no-op preserves exact
original bytes, and an optional final source check runs under the settings writer lock for a
real write. The caller obtains approval; this helper grants no action consent or migration.

`Special/_archive/registry.py` selects common settings when present, with no fallback from an
invalid common profile. Legacy-only profiles retain their registry. Common receipt saves use
format version 2: saved state cannot become legacy preferences if settings.json later goes
missing. The first common install/forget marks retained receipt state before changing choices;
read-only calls never upgrade state. Unknown receipt fields and historical preference copies
remain retained, not authoritative. Common v1 settings require an explicit schema upgrade.
The scoped existing-settings action establishes receipt-only ownership as part of its switch;
simply hand-placing/removing common settings beside untouched legacy state is not that protocol.

Registry snapshots retain exact source revisions. Registry writers use an exclusive lock,
recheck both sources, then atomically save one file. Explicit installs can save preferences
and receipts separately; failures identify partial state rather than claiming a cross-file
transaction. A failed preference save may leave the receipt format advanced, with all receipt
fields and preferences preserved. Locks are never automatically reclaimed. Older independent
writers/processes still require a deliberate stop/transition before actual migration.

Both manager paths expose --settings-home and --refresh ROOT. A single refresh refuses an
unregistered root and shares refresh-all's engine. New per-archive launchers invoke the Special
manager with root/home only; new refresh-all launchers pin home too. Current choices are read
when run, not copied into launcher arguments. Reinstalling without mode/prefix flags preserves
those choices. Forgetting common registration preserves receipts/artifacts for ownership review.
Existing generated launchers are not silently rewritten; they require reviewed regeneration.

Managed refresh now resolves `archive_manage` output/logging preferences once per invocation.
It runs a headless per-archive update/sync operation and produces one aggregate result, one
optional exclusive report and one shared event/counter log. Direct update remains the lower
Git-only updater; sync reuses the existing detect/pull/clone functions without terminal output
capture. Per-archive mode and remote allowances remain authoritative, with invocation-only
force-sync and no preference rewrite. Legacy-only registration is read without migration;
runtime output/logging uses documented defaults in that selected home, never another profile.

`--json`/`--format`, `--output-mode`, `--output-dir`, `--no-report`, `--log`/`--no-log` and
`--log-dir` are accepted only for refresh actions on both local and retained scheduling entry
points. Conflicting options fail before reading profiles. Required destinations are checked
before Git actions and never fall back. Explicit report/log paths are checked for links before
physical resolution. Results enumerate actual artifact destinations, including file-only
receipts on stderr; an empty collection still honors selected sinks.

Scan-only creates no installation/run receipts. Actual refresh saves run status/time with CAS
checks, without storing a guessed latest report. Existing historical metadata can still be
displayed; new reports are invocation artifacts. Changed authority, logging/report/receipt
failure and interruption retain partial/uncertain results and stop later work. Registration,
launcher creation and scheduling state/logging are separate remaining adoption work.

Common exclusions and linked root/child paths are checked before manager Git/report effects.
An exclusion within an archive currently refuses that whole archive: the shared sync engine
does not yet support partial path scope. Empty remote allowances fail before execution, without
built-in widening. The shared engine now filters local action targets and upstream clone URLs
by the supplied prefixes and reports rejected candidates; its old selection discarded the
calculated local approval result. Blank prefix strings are rejected. Sync CLI import hints use
common roots, with invalid settings failing before sync initialization; legacy-only hints keep
their earlier tolerant behavior. The GUI's enrollment reader now uses the common fleet adapter below.

This is archive-choice/receipt adoption only. The manager retains its existing report/log
format and destinations; full common output/logging/structured-result integration remains
open. Remaining security consumers, existing-launcher/writer review and explicit user approval still
precede any real switch. The scoped archive/policy existing-settings action above is available;
broader conversion remains unavailable.

## Fleet CLI/app settings adoption (2026-10-28)

`Special/_settings/fleet.py` projects existing common v2 enrollment into the current CLI v1
and app v5 runtime records. The CLI selects at most one folder/repo transport; the app keeps
its independent multiple-transport selection, baskets, recovery choices and observation settings.
Shared definitions and machine identity are not independent copies. An existing common document
is authoritative: invalid/incomplete enrollment fails; an unenrolled component never reads old
configuration as a fallback. A v1 common document is not upgraded by component setup.

`--settings-home` on either front door selects the common profile; otherwise `GITSPECOPS_HOME`
and the OS user-data default apply. `--config-dir` selects local fleet state/catalogs and legacy
inputs only. Its default is the selected home's sync-suggester child; GITSPECOPS_SYNC_HOME can
override that state directory without relocating common settings. Tray, guided setup and newly
configured autostart arguments preserve both selections. No existing launcher or environment
variable was changed. The packaged entry point checks common enrollment instead of requiring
fleet-app.json. Help and capability preflight do not read profiles or create locks.

Without a common document, existing CLI/app legacy files remain usable in place. The app retains
its existing legacy-version conversion on resume; it does not convert those files into common
settings. Common setup can add an explicitly selected missing component to an existing v2
profile; it reuses a saved machine identity/key, never generates a replacement for that owner.
Per-component identity changes are refused. Changing a transport selected by another enrolled
component is refused before optional remote creation; clearing a selection retains the shared
definition. Such coordinated changes need a separate reviewed interface.

Common edits use source-bound views and the existing revision-checked atomic writer. Plain dict
copies cannot overwrite a common profile. No-ops keep exact bytes, stale/mutated snapshots and
busy writers fail, and other components/security/output choices survive. Bound saves cannot
fall back to legacy after losing settings. The dashboard saves only its explicit desktop-client
choice, without persisting runtime-discovered tailnet identity. Recovery/basket/transport/client
commands and rescan/startup checks use the same authority. No runtime data moves into settings.

Common exclusions and linked-root checks precede fleet inventory, including explicit CLI roots
on an unenrolled common profile. An intersecting exclusion currently refuses the whole root;
partial-root discovery remains separate work. Common output/log routing, live profile reload,
native packaging/OS validation and generic lifecycle setup still remain open. The startup and
runtime-location paths are tested with invented temporary profiles, not actual enrollment.

General fleet conversion remains unavailable. Existing launchers and independent legacy writers
must be transitioned deliberately. Enrollment/cutover ownership evidence must prevent a deleted
common file from reviving old copies on a later fresh load; archive receipt v2 alone is not
global proof. Other security consumers and action-policy freshness also remain unfinished.

## Active security-policy settings (2026-10-27)

`Special/security/_me.load_policy` uses the shared resolver for the selected security component.
It accepts `home` or caller-resolved `settings`, not both. The resolved seam performs no settings
lookup; the caller owns that snapshot. Default first use has in-memory defaults and no writes.
Known legacy state without common settings produces the resolver's migration-required error.
Malformed/ambiguous/unsupported common settings fail before identity or material inspection.

Tree/history commands expose --settings-home and --legacy-policy. Legacy mode explicitly reads
the selected home's original text lists (or explicitly selected files) and retains their earlier
safe precedence. It refuses any existing common settings file, including an invalid one. It
does not migrate/edit/delete lists or grant a common-policy override. No silent legacy fallback.

With common policy, saved protected values accumulate across common/component settings and
additional --never-publish input. Explicit --safe-file/--safe values supplement effective saved
allowances. Exact case-insensitive block/safe conflicts fail; discovery of an overlapping safe
public handle/noreply identity also fails rather than hiding the block. The existing enclosing
safe-value matching semantics remain; broader exception design is still separate work.
Missing/unreadable/linked/excluded explicit policy files preserve incomplete coverage. Common
policy does not consult stale default text copies. Policy summary/repr omit literal values,
local paths, discovered identities and keys; raw Policy fields remain trusted callable data.

Effective exclusions and linked scan-root ancestry are checked before Git identity discovery.
An excluded subtree currently refuses the whole repository instead of pretending a partial scan
is complete. Reading this source checkout remains permitted; runtime write-path protection is
not reused to forbid source auditing. Excluded report destinations fail before material scans.
Errors with --json are a JSON error record with incomplete coverage, never a false clean result.
Report/storage/logging preferences have not otherwise been adopted: scans still print masked
stdout and write no automatic reports/logs; --out explicitly requests the existing full-report
writer. Full report contents/paths remain private and its current Git-ignored destination
restriction remains separate work.

`Special/_settings/security.py` supplies a private editor snapshot and explicit save helper.
It reads an existing v1/v2 document using `store.read_settings_document`, retaining exact bytes'
revision and all fields. `save_security_settings(snapshot, updates, check_sources=...)` replaces
only supplied defaults.security lists through the existing writer. Other components, source
formats and original text files remain intact. Per-component blocks still accumulate: editing
common lists does not clear blocks owned elsewhere. All saved components are conflict-validated.
Source/candidate changes refuse saves; optional verification runs under the writer lock on real
writes. No-ops retain exact bytes. The invoking interface must obtain approval for removals or
expanded allowances. This is not a show/add/remove UI, import, enrollment or migration action.

Remaining: fleet/recovery/hygiene policy adoption, policy editor/revelation UI, action-gate
freshness and scan-policy revision binding, and broader enrolled-profile loss-recovery protocols. An
unenrolled empty profile intentionally permits default scans; detecting a formerly configured
policy-only profile after its settings file disappears needs enrollment/cutover ownership
evidence. The archive receipt-v2 guard is not a global settings-loss solution. Do not enable
broader conversion merely because these reader/editor adapters exist. The scoped archive/policy
switch above has its own approvals/recovery; archived scanner code is frozen.

## Reviewed updater setup (2026-10-27)

The root setup menu offers guided updater preferences plus settings-preview/settings-save for
noninteractive use and settings-migration-preview for read-only legacy mapping. Existing
bootstrap, launcher/environment and prerequisite actions remain separate. Settings actions
perform no repository operation, enrollment, installation or runtime report/log creation.

Special/_settings/setup.py prepares a private SetupPlan and safe summary. Only archive_update
scope/output/logging fields may change; other fields/components are preserved. Roots replace;
exclusions add unless explicitly cleared at component level, with common exclusions retained.
Empty stored roots keep the documented cwd behavior, explained by the preview. Candidate
resolution reuses resolve_document; readers/previews/setup share legacy_locations.

Preview writes nothing. Its review id binds candidate, selected home and source revisions;
this is freshness checking, not authentication. Headless saving requires that exact id and
the same options; guided save requires typed SAVE. Cancellation/EOF before saving writes
nothing. The existing atomic writer checks revisions and SetupPlan.verify under its lock.
Changed/new sources, changed targets and altered candidates invalidate review. A semantic
no-op preserves exact original bytes. Post-save lock cleanup failure remains explicitly
reported as saved-but-needing-review. User authorization is separate from the review id.

Summaries contain counts and field names only. --show-paths explicitly reveals target/root/
exclusion/runtime paths, or legacy source paths for migration preview; it never prints policy,
identity, transport or fleet-key values. JSON requires an explicit action and contains no menu
or prompts. Wrappers preserve caller-relative paths and invoke setup by absolute script path;
bootstrap still uses explicit checkout paths. Native POSIX wrapper evidence remains pending.

Fresh-profile saving refuses legacy sources in that selected profile. Migration preview
distinguishes mapping_ready from activation_ready; general activation remains unavailable and
the summary now points archive/policy-only users to settings-existing-plan. The scoped action
above has its own explicit approvals and recovery path; this broad preview still never saves.
Existing common profiles may edit their already-adopted updater component without adopting
legacy-owned fields. Known legacy-file snapshots are checked for freshness; operational
receipt changes can require a new preview until adapters separate their ownership. Fresh
profiles use schema v2 and supported existing versions are preserved. Actual user profiles
were not changed or migrated during implementation.

## Standalone updater: first integrated consumer (2026-10-27)

`Special/update_archive.py` uses component `archive_update`. Public callable
API: `run_update(resolved_settings, UpdateRequest(...)) -> UpdateResult`. It performs no profile
lookup and prints nothing. Requested report/log sinks are local; no fleet or gh is required.
Omitted request roots select saved roots, otherwise cwd; an explicit empty scope is an error.
CLI roots replace saved roots and exclusions accumulate. Excluded roots are refused; linked
child folders and checkouts containing an excluded subtree are skipped before Git inspection.
Scope remains direct-child scanning. Exclusions also guard conflicting runtime destinations.

The CLI exposes --settings-home, --root, --exclude-path, --output-mode stdout/file/both,
--format text/json (or --json), --log/--no-log, --log-dir and --log-level. CLI paths are
cwd-relative; saved paths are settings-home-relative. --output-dir implies both channels unless
an explicit mode selects file-only; --default-output-dir is relative to one effective root.
--no-report forces stdout and does not disable logging. Conflicting options fail explicitly.
Legacy profiles still require explicit migration; this consumer never bypasses that refusal.

Results use schema_version 1, operation `archive_update`, mode/status/exit_code/errors,
completed_roots/effects_possible/elapsed_seconds/artifacts, and per-root scan/summary records.
Exit 0 means work finished, including deliberate skips; 1 means an eligible pull failed;
2 means settings/scope/inspection or required sink failure. Possible effects followed by a
required failure are marked partial, retaining completed and unprocessed repository records.
Configuration/parser errors are stderr diagnostics before execution, without a success record.

Enabled stdout gets one result; JSON contains no progress/banner text. Progress and diagnostics
use stderr. File-only mode presents actual artifact destinations on stderr, with no stdout result.
Files use the selected format
and unique exclusive filenames, without overwriting. The --output-dir flag follows
the selected format instead of always forcing JSON. Protected literals and offline credential
candidates are concealed in both channels. Full origin URLs require --show-remote-urls and still
conceal credentials. Trusted callers may explicitly request record(redacted=False); raw values
never enter operational logs.

`Special/_runtime/logger.py` configures named invocation/component loggers from resolved settings.
JSON-line logs accept only event names, ids, timestamps and numeric counts, never stdout/stderr,
paths, repository/branch names, origins, raw settings or diagnostics at any level. Default
rotation is 10 MiB/three backups; zero backups retains only the rotating current file. Each
append/rotation takes a cooperating-process lock and closes the file before release. A busy or
stale lock fails after a bounded wait and is not deleted automatically. Failure events are ERROR
severity. The execution-finished event covers repository processing before report delivery.
Other consumers and multiple logging sinks remain open work.

Enabled destinations may be created deliberately, but not in this source checkout or through
existing links/reparse points. Reports reserve a new file and logging is probed before pulls.
Failures never choose another destination. Mid-run logging failure stops further updates;
report-write failure returns an error with in-memory results retained. Incomplete new reports
are removed best-effort and never advertised as valid. Existing permissions still apply; this
is not an OS privacy boundary. Tests use invented temporary settings and repositories only.

## Shared archive runner and direct sync

`Special/_archive/operation.py` owns `run_archives(settings, requests, ...)` and
`run_refresh(...)`. One invocation owns one masked result, optional exclusive report and
counts-only log. UpdateRequest/UpdateResult use the same artifacts list for actual report and
operational-log paths. No default archive-relative reports or guessed latest-report pointer.

Each explicit request supplies root, mode and nonempty approved_remote_prefixes. Modes are
scan, update, sync, repair or publish; repair selections are explicit booleans. Roots must not
overlap, traverse links, or conflict with exclusions. All selected scopes and required sinks
are checked before effects. The runner defaults to preview; actions require an approval
callback receiving masked plans. Caller-owned state is rechecked through before_action.

Direct archive-sync resolves one selected common profile without legacy-policy flags. It
rechecks that same resolved profile (including configured/schema state) before mutations;
deletion cannot become fresh defaults. CLI choices override saved archive_sync preferences.
It uses the common output switches, sends interactive plans/prompts to stderr, and requires
--yes for unattended mutations. --dry-run previews every selected action class.

Update uses the shared updater; sync updates/clones using the provider plan; repair changes
only explicitly selected origins/folders, with target/origin/cleanliness rechecks. Publish is
exclusive: local immutable tips/targets and policy are bound before approval; the security gate
rechecks each snapshot and policy, fetches its actual destination base and checks outgoing
history before a non-force push. Masked security findings remain in the publication result.
Completed push records survive a later backend failure/interruption. Exit 130 means interrupted.

Manager refresh selects registered update/sync choices and supplies state-revision guards and
receipt saving to the same runner. Preview never changes receipts. Registration only registers
and optionally offers a normal refresh; it has no separate mutation pipeline. Elaborate accepts
scheduling actions only; newly generated refresh-all launchers call the Special manager.
Saved profiles, installed launchers and OS tasks are not rewritten by source cleanup. A launcher
using a removed command route needs separate explicit regeneration before it can run.

