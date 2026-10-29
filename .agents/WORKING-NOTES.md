# Working notes

Living todo / scratch pad. Add items freely; **prune regularly**. When something is done, move it
into [`WORK-LOG.md`](WORK-LOG.md) (appended at the bottom, `YYYY-MM-DD HH:MM`) and delete it here.
Dates are always absolute.

_Last tended: 2026-10-29 (archive commands share headless output/logging; obsolete archive routes removed)_

## Open

### Conversation decisions versus actual implementation — 2026-10-28

**Current controlling task: implement the reconciled product decisions in bounded batches.**
After the conversation-wide review, the user settled optional engines, actionable disclosure,
archive membership choices, portable master/local policy, complementary conduits and the
`gitso` name, then explicitly said proceed. These choices are canonical in product-contract.md.
Source implementation/disposable verification is now authorized, preserving existing work;
live settings conversion, launcher/job/startup changes, installation, history replacement,
commit, push and publication remain separate and are not authorized by source work.

**Current support ruling, 2026-10-29:** backward compatibility is not required. Build the
intended current behavior, remove obsolete command adapters/fallbacks as each family is
replaced, and keep current documentation simple. Saved data and live setup stay intact;
necessary conversions are explicit setup operations, never automatic runtime guesses.

**Remaining archive acceptance:** direct sync and registered refresh now share the headless
runner; the updater lists actual artifacts; obsolete updater aliases/direct report writers and
Elaborate local-command forwarding are removed. Registration no longer calls mutation helpers.
Keep installed launcher/job changes parked: a launcher using a removed route needs separate
explicit regeneration before use. Remaining work includes GUI use of these results, complete
registration/membership policy, receipt/legacy-data ownership conversion, native symlink and
OS scheduling proof. Other command families still need their own adapter cleanup; this batch
does not complete the global one-current-interface policy or the product acceptance matrix.

#### Current remaining acceptance after the first implementation batches

- **Optional engines:** adapters and selected-material integration exist for Gitleaks 8,
  Betterleaks 1 and TruffleHog 3 stdin protocols, individually/combined/none. Selected failures
  are gaps, never fallback. No executable was found on this host's PATH; no scanner was installed.
  Real binary/version/platform acceptance, newer Betterleaks protocol adaptation, guided local
  executable bindings and optional provider validation remain open. Mocked adapters are not
  equivalent to a native engine trial or full publication scan.
- **Shared policy:** master plus additive machine-local lists and conflict checks are in the
  resolver/scanner/editor. Pure portable projection/merge preserves local bindings and excludes
  keys, paths, recovery consent and machine additions. Guided transfer and actual folder/repo/
  peer exchange still need revision/ownership/conflict handling, presentation and setup wiring.
  Do not defer portability as a product decision; its remaining work is implementation.
- **Actionable presentation:** scan schema v2 has report-local finding ids, severity, masked
  locations/line/object, remedy guidance, engine states and successfully produced report artifacts.
  These ids are not execution permission or persistent secret fingerprints. GUI human reveal,
  independent logs/notifications, external-private-directory report support and common logging
  across operations remain unfinished. No raw value is required for normal agent triage.
- **Common front door:** `python gitso.py` now provides a static 14-command catalog, source-derived
  docs/help, terminal menu and dispatch to existing operations. Direct scripts remain supported.
  Duplicator receives explicit argv without global argv replacement. Existing command effect,
  consent, results and output differences remain; listing is not a new common operation engine.
  Installed aliases/wrappers, complete GUI/callable structured-result integration, richer parser/
  effect metadata and generated-doc parity remain open.
- **Remaining action integration:** checked named-file commits, direct/Archive Sync publication
  and local sync-check/dashboard advice now share active policy/readers/engines. Complete common
  logging/artifact routing, continuous advisory scheduling/invalidation, GUI commit/push and the
  attended remote-action protocol. Local security stays outside fleet manifests/reports. Sync
  check JSON is an envelope with manifest/local_security/artifacts; only manifest is shared.
  Browser automation was unavailable for visual acceptance; HTTP/scope/JS checks are not a
  substitute for a screenshot/native UI trial. The checked commit preserves Basic's named whole
  working-tree files, unrelated staging and traditional hooks; compatibility beyond its explicit
  first scope still needs native proof. Broader
  archive registration/new-member policy, lifecycle, readable synced notes, transport scale,
  security repair proof and native/multimachine acceptance stay in the comparison/backlog. Do
  not resume live settings activation or launcher repair as an incidental prerequisite.

The canonical design remains [product-contract.md](knowledge/product-contract.md), alongside
[architecture-layers.md](knowledge/architecture-layers.md),
[settings-schema.md](knowledge/settings-schema.md) and
[security-design.md](knowledge/security-design.md). Those describe requirements, not proof of
completion. This is one open acceptance review: retain the implemented portions here only to
make the comparison complete until the review is resolved, then graduate accepted evidence to
the log and retain only remaining work. The later detailed backlog is supporting material,
not an instruction to resume the formerly proposed live switch.

**Reading the comparison:** Implemented means the named behavior exists with bounded evidence;
Partial means only some of the requirement exists; Missing means no implementation was found;
Unverified means the required real-world proof is absent; Open means the user has not settled
the choice; Paused means do not execute it. Source references are relative to this repository.
Private mission coordination and unrelated repository purge scope remain outside these public
notes. No claim below means all historical secrets, all platforms or all user workflows passed.

#### A. Purpose, architecture and public interfaces

| ID | User decision / required outcome | Actual state and remaining acceptance |
|---|---|---|
| A1 | The primary purpose is seeing out-of-sync repositories across the user's machines and helping put them in order. | **Partial.** Fleet observation, manifests, peer aggregation, advice and dashboard exist in `git-sync-suggester/`. Fresh mocked peer checks pass. A real two-machine acceptance journey is not proved. |
| A2 | One coherent app at the top; each individual operation remains useful on its own. No shelf, shape, fleet or shared helper dependency for casual archive updating. | **Partial.** Direct scripts and plain Python/Git operation paths exist. Fourteen public `--help` commands work outside the checkout without creating a profile. Common settings/results/logging and app integration are not universal. |
| A3 | Preserve Basic -> Special -> Elaborate -> App, with plumbing in private helper folders and operations visible at layer roots. | **Partial.** `_settings`, `_archive`, `_org_duplicator`, `_runtime` and security `_commit` group helpers. Archive aliases/CLI forwarding are removed; other families still need cleanup. Fleet/app largely remain in their earlier tree. The 94-file layer check passes; this is not complete physical reorganization. |
| A4 | Move `duplicate_org.py`, `update_archive.py` and local `archive_manager.py` into Special; scheduling and fleet coordination remain Elaborate. | **Implemented for the selected source split.** All three public scripts are in Special. `Elaborate/archive_manage.py` retains scheduling/compatibility. Functionality and defaults beyond that source move remain separately reviewable. |
| A5 | An action-named updater invokes reusable updater plumbing; avoid underscore/helper clutter among public commands. | **Partial.** `Special/update_archive.py` is the public adapter; `_archive/update_operation.py` owns its callable operation, with supporting helpers grouped privately. Other families still need consistent public/private mapping. Exact helper basenames are implementation choices, not user-mandated renames. |
| A6 | One CLI/main menu exposes operations to terminal users and LLMs; direct scripts still work. | **Partial.** User selected `gitso`. Source launcher/catalog/menu and source-derived docs now dispatch fourteen operations; direct scripts remain. Installed wrappers, richer shared metadata/results and full GUI integration remain unfinished. |
| A7 | CLI and GUI invoke the same headless functions, with structured results, explicit effects and no automation prompts. | **Partial.** The standalone updater has a headless request/result contract; duplicator batch/single modes and fleet functions exist. There is no universal result schema or GUI coverage for all Special operations. Some paths still assume interaction. |
| A8 | Every script has essential purpose/usage documentation; important functions document contracts; CLI/menu/generated docs derive from source. | **Partial.** The earlier 121-module audit found module docstrings, and new modules carry purpose/usage contracts. Source catalog, terminal menu and source-derived docs/help now exist. Presence is not correctness or complete usage coverage; full generated-doc/parser parity and older header accuracy remain acceptance work. |
| A9 | Consistent appearance, status vocabulary, help, errors and progress across the tool. | **Partial.** Console/app infrastructure exists, but separate script parsers/output and app paths remain. Documentation/help checks do not establish consistent operational presentation. |

#### B. Independent operations and archive management

| ID | User decision / required outcome | Actual state and remaining acceptance |
|---|---|---|
| B1 | Keep the original org duplicator a discoverable, independent Special operation. | **Implemented direct entry; partial common integration.** `Special/duplicate_org.py` delegates to `_org_duplicator/`; batch arguments, local-repository safety, selection and operations checks pass. Resume records remain at their established ignored source-adjacent location; common output/settings/logging are incomplete. |
| B2 | Distinguish updating existing archive checkouts from discovery/cloning/reconciliation; manager offers both. | **Implemented local distinction.** Updater changes eligible existing checkouts; sync additionally discovers/clones and supports explicit repairs. Both manager pathways use shared headless results/settings/logging. Public/private ownership is not the selector; broader app/native acceptance remains open. |
| B3 | Do not confuse archive synchronization with the user's cross-machine synchronization. | **Recorded and reflected in separate operations.** Personal fleet coordination remains above local archive management. `sync_self.py` was discussed but never selected; no rename is authorized by that suggestion. |
| B4 | Archive manager is the real local front door, calling the relevant operation once per selected archive, then returning. Scheduling stays above it. | **Refresh implemented, broader acceptance partial.** Shared run_archives/run_refresh preserve saved update/sync choices and return actual artifacts. Registration offers normal refresh without direct mutation helpers. Elaborate is scheduling-only; new launchers call Special. Registration/launcher coupling, membership choices and GUI/native acceptance remain unfinished. |
| B5 | Let the user add/list/remove archives independently of installing automation. A chosen folder with Git repositories is a candidate. | **Partial.** Registry and one-off `--root` exist, but registration remains coupled to `archive_manager.py --install` and launcher creation. Recognition still checks eligible direct children, conflating collection identity with update eligibility. No complete independent registration journey. |
| B6 | Support pointed discovery and explicit broader-machine discovery, actual `.git` directories/files, exclusions and bounded scope; never silently enroll discoveries. | **Partial.** `Basic/discover.py` and `_discovery.py` recognize worktrees and bare repositories with no-follow/depth/mount controls. Integration with enrollment scope, universal exclusions, selected-drive/cancellation UX and clear coverage gaps is unfinished. |
| B7 | Ordinary pulls/pushes remain useful and safe; higher-level security/consent orchestration composes them. | **Partial.** Basic operations remain policy-free. Checked commit and direct/Archive Sync publication now compose shared policy above Basic. Observation/advice is not action permission; full GUI/remote-action parity remains open. |

#### C. Settings, setup, enrollment and installation

| ID | User decision / required outcome | Actual state and remaining acceptance |
|---|---|---|
| C1 | One local settings document with component sections, in the user's account directory outside the source checkout. | **Implemented foundation.** `Special/_settings/` resolves external home/defaults and versioned common/component settings, with provenance and validated writes. This is not proof every command has adopted it. Actual audited local profile has not been converted. |
| C2 | Explicit command choices override saved choices; configured machines remember paths/options. Invalid configured destinations/settings error instead of silently falling back. | **Implemented resolver; partial consumers.** Resolver errors and focused tests support strict loading and precedence. Components retaining independent paths/report defaults still need adoption. An unenrolled fresh profile is distinct from loss/corruption of an enrolled profile. |
| C3 | Setup may select another settings location and later move it deliberately; CLI and app must locate the same authority. Agent notes may point there but are not runtime configuration. | **Partial.** `GITSPECOPS_HOME` and explicit settings-home routing work; old component overrides remain. A complete relocation/GUI locator/ownership journey is missing. No symlink is required or selected by this decision. |
| C4 | Logs default locally beside user data; keep code checkouts easy to update and usable after clone/fork/move/install. | **Partial.** Common home, updater and native tray logging are external. Duplicator run state is still source-adjacent and some reports default into archives. Installed/forked/moved-checkout lifecycle is not fully proved. |
| C5 | Setup holds the user's hand: explain participation matrix, guided setup, choose one item, update only gitSpecOps, uninstall and selective unenroll. | **Partial.** Bootstrap and updater preferences plus narrow use-existing-settings actions exist in `setup_gitspecops.py` and `_settings/setup.py`. Full lifecycle/menu coverage and capability/tradeoff presentation are unfinished. |
| C6 | Participation is optional: basic operations -> selected special tools -> remembered machine -> durable/live fleet -> optional app. No mandatory state repo/SSH/Tailscale/gh for plain archive use. | **Partial.** Standalone paths and several optional transports exist; matrix is canonical in the product contract. One guided adaptive capability flow through all these combinations is not finished. |
| C7 | Enrollment establishes machine identity, scoped roots/exclusions, selected transports/integrations and accepted permissions using existing authentication. | **Partial.** Common typed machine/transport records and fleet readers/savers are connected. Machine CLI and app selections retain their different capabilities. General setup enrollment and a consistent capability inventory are unfinished. Git/gh credentials are not to be copied into settings. |
| C8 | Guided optional creation/selection of a private state repository using existing gh authentication. | **Partial.** Older fleet setup has create/use and privacy/access checks. Reuse through the common setup lifecycle remains unfinished; this feature is not wholly absent or a reason to build another independent wizard. |
| C9 | Distinguish portable shared preferences, machine bindings and sensitive local data. Do not replicate the whole profile just because transports are private. | **Partial implementation, direction settled.** User requires portable behavior/security master policy plus machine additions now. Pure projection/merge and local/master conflict handling exist; guided transport revision/ownership/conflict integration is unfinished. No competing active profile copies or whole-profile replication. |
| C10 | Optional notes integration may accompany enrollment. | **Defined, integration open.** User means a private synced-folder/notes conduit and readable fleet text, complementary to durable private Git state and direct tailnet peers. Existing folder transport is useful; readable-note/shared-policy setup and lifecycle remain unfinished. No mandatory notes-provider SDK. |
| C11 | Update gitSpecOps itself by fast-forwarding its selected source checkout, callable from CLI/setup/app; never update the user's archive as a side effect. | **Missing product updater.** `Basic/pull.py` supplies the primitive; version checks only report. Checkout/branch/remote/fork/dirty/divergence checks and app stop/restart are not composed into an updater. A frozen bundle also needs a distinct release-update path. |
| C12 | App installation adapts to the OS; uninstall can remove owned components while preserving repositories and data by default. | **Partial packaging, missing complete lifecycle.** Optional PyInstaller recipe exists. General install/update/uninstall/selective unenrollment and native three-OS receipts/cleanup are not proved. Current packaging is not the separately approved retired historical packaging purge. |
| C13 | Handle existing settings without competing authorities, silent loss or implicit changes to consent. | **Partial, live work paused.** `_settings/existing.py` has tested archive/policy-only plan/save/status/resume, original-byte retention and receipt ownership. Broader fleet conversion/settings-loss proof is incomplete. Real settings and launchers remain unchanged; conversion is not the next mission milestone. |

#### D. Output, logs and programmatic use

| ID | User decision / required outcome | Actual state and remaining acceptance |
|---|---|---|
| D1 | Inspection/report output goes to stdout by default unless explicit flags or saved preferences request a file or both. | **Partial.** Updater, direct archive sync, manager refresh and active scans support stdout-first routing. Direct sync no longer has implicit archive reports. Inventory export still chooses/writes a file; registration/scheduling logging and remaining consumers need adoption. |
| D2 | File output destinations and no-fallback behavior must be intentional, predictable and testable. | **Partial.** Updater/direct-sync/manager tests cover explicit routing, actual artifacts and no fallback; linked paths retain lexical input through checks. One native symlink case is skipped because host link creation was unavailable. Active security full-report support for private directories outside Git remains missing. |
| D3 | Automation gets clean machine-readable stdout; diagnostics/progress go to stderr; operations expose useful status/results and errors. | **Partial.** Archive commands use headless results with masked text/JSON and actual artifacts; direct scripts and gitso share these operations. Common cross-operation stream/status/schema acceptance beyond this family and full GUI presentation remain unfinished. |
| D4 | Use Python logging through one shared configuration seam; allow local defaults, no-log, per-component routing and selected multiple destinations. | **Partial.** Updater, direct archive sync, managed refresh and native tray use Special/_runtime/logger.py. Archive results list actual report/log artifacts; scopes/policies are rechecked before actions. Registration/scheduling historical logging, other consumers and selected multiple sinks remain unfinished. |
| D5 | Human revelation, LLM output, saved reports, logs and fleet notifications have independent disclosure choices. No accidental stdout tee of a revealed secret. | **Partial, concrete channels repaired.** Raw tray tee removed; events/counters are separate and notification errors are generic. New-fleet setup hides generated keys; fleet-key defaults to hidden metadata and --show deliberately returns raw JSON through one helper without writes/logging. Captured explicit output is not agent isolation. Full human GUI revelation, cross-operation sinks and native acceptance remain open. |
| D6 | Treat operational state separately from optional reports: settings, catalogs/manifests, resume records, plans, receipts, recovery and requested installers have lifecycles. | **Partial.** These state types exist, often with validation/atomic writes, but locations/ownership are inconsistent. Stdout-first is not permission to remove needed resume or fleet records. |
| D7 | Missing, unavailable, stale, failed and checked-clean are distinct; unavailable work must never look clean. | **Partial.** Fleet freshness and strict settings paths exist. Common result semantics, complete coverage reporting and required logging/output failure behavior remain uneven. Full acceptance needs failure-path journeys beyond one component. |
| D8 | Tests must reject an unintended per-user report fallback instead of passing when the requested destination failed. | **Partially covered; original regression still open.** Fresh updater/settings tests explicitly exercise no-fallback errors. The earlier archived report test/assertion needs reconciliation with the active writer contract; its deferred full regression was not rerun here. Passing the newer focused tests does not prove that original issue resolved. Keep archived code frozen while defining the active acceptance test. |

#### E. Security, privacy and history repair

| ID | User decision / required outcome | Actual state and remaining acceptance |
|---|---|---|
| E1 | Security checks are part of sync advice and supported commit/push actions, not an unrelated scanner users must remember. | **Partial.** Checked commits, direct/Archive Sync publication, sync check and explicit local dashboard advice share policy/readers/engines. Basic remains policy-free. Continuous advice and complete GUI/remote commit/push remain unfinished; manifest-only/watch views do not check security. |
| E2 | Commit checks exact proposed bytes/message/identity; push checks outgoing history, including introduce-then-remove; remote execution rechecks current state. | **Partial.** Archive publication binds the planned immutable tip and target, scans actual destination base..tip and rechecks policy/source/destination before a fixed non-force push. Named-file commits check raw inputs, actual filtered staging and final native hook inputs against an exact plan; final tree/parent/message/identities are verified and uncertain execution is partial. Other staged work and traditional hooks are preserved. Remote action protocol, broader compatibility and other consumers remain unfinished; cached advice is not action proof. |
| E3 | User blocklist plus allowed generic values; conflicts explicit; protect private publication values as well as credentials. | **Implemented scanner foundation, partial management.** Common/legacy policies and per-run safe values work; block/allow conflicts error and inherited blocks are protected. A private programmatic membership check confirms the requested private email is already in the local blocklist without recording its value here. Policy show/add/remove CLI/app UI is missing. Hygiene/recovery do not yet share this full policy. |
| E4 | Enrollment exclusions define what the tool must never inspect/manage, separately from strings prohibited in publication. | **Partial.** Discovery controls and scoped fleet selections exist, but namespace baskets are not a universal hard no-inspection boundary. Cross-consumer exclusion enforcement and discovery/enrollment UX remain unfinished. |
| E5 | A human can deliberately read what is at risk; agents normally receive useful masked context, not the underlying secrets. | **Partial.** Active scanner masks stdout by default and can explicitly write full reports. There is no equivalent intentional stdout/app reveal flow yet. Do not solve this by always exposing values or by preventing human inspection. |
| E6 | Reuse scanner/policy behavior across standalone checking, sync advice, action gates, recovery and repository hygiene. | **Partial.** Standalone scans, checked commits, direct/archive publication and local advice share material/check/policy/engine code, severity and check_status. Recovery, archived rules and hygiene remain separate; reconcile behavior before replacing them. These callers are not universal cross-consumer equivalence. |
| E7 | Distinguish introducing a prohibited value from removing it; reviewed exceptions and incomplete scans are explicit. | **Partial.** Archive gate checks outgoing versions, allowing simple baseline removal while blocking introduce-then-remove. Checked commits inspect new selected bytes/paths/message/identity, allowing removal of an old prohibited path. Gaps/selected failures hold actions; uncertain candidates require policy review and rerun. State/policy rechecks include settings loss during checking. General exceptions, remaining action consumers, shared policy ownership and installed outside-client hooks remain open. |
| E8 | Assess established security tools before extending custom detection; privacy policy and orchestration still belong here. | **Choice settled, partial implementation.** User requires optional Gitleaks/Betterleaks/TruffleHog or none. Three versioned stdin adapters now run over already selected material with masked results and explicit gaps. No actual engine is installed/selected here; native/version acceptance remains open. Detection is distinct from dependency security and historical-clutter removal. |
| E9 | Security coverage must state its gaps, including symlinks and binary/container material. | **Partial.** Archive/nested compression, OOXML/EPUB and selected image metadata are handled with bounds. PDF, 7z/RAR, LFS content, submodules, unsupported/oversize/binary material and external-engine coverage remain gaps. The native symlink case is skipped on this Windows run; its precise OS cause is not captured. This is a scan coverage issue, not a requirement to symlink settings or copy tool installations. |
| E10 | Reviewed test fixtures and public contest constants are explained exceptions, not an unexplained all-clear. | **Partial recorded review.** Older notes distinguish synthetic fixtures and a public contest value. Such findings need scoped, reviewable policy justification; a past decision is not universal suppression for similar-looking real credentials. Current allow policy is not yet shared by hygiene/recovery/action gates. |
| E11 | Reuse existing history-repair/finishing behavior; prove scan -> rewrite -> scan on disposable repositories before real approved purges. | **Partial legacy capability, active rebuild/proof unfinished.** Frozen `_archive/Security/` retains plan/apply/verify/follow/relink/finish. Its finish can commit/push and is not authorized now. Active layered rewrite workflow, disposable end-to-end proof and fresh full-history clearance are not established by this review. |
| E12 | Purge only explicitly approved obsolete material; avoid erasing project history or deleting current packaging by inference. | **Paused pending scoped execution/proof.** The affected repository owns concrete purge manifests/former aliases; private mission notes preserve the conversation's scope. A new repository was considered, not selected. Tree absence and dated cleanup reports are not fresh history proof, nor proof external copies vanished. |
| E13 | Full reports/private findings cannot leak via tracked notes, generated diagnostics, shared state or app notifications. | **Partial safeguards.** Ignored report validation, masking and local-only advice exist; raw tray tee and automatic generated-key output are repaired. Audit notes remain generic. Other raw diagnostic/result channels and native end-to-end disclosure acceptance still need review. Private storage alone does not make every replication/disclosure safe. |

#### F. Fleet, app and scalable transport

| ID | User decision / required outcome | Actual state and remaining acceptance |
|---|---|---|
| F1 | Optional transports support offline durability and selected live connectivity using tools already authenticated. | **Partial.** Folder, private repository and tailnet paths exist; mocked peer tests pass. Actual two-machine behavior, stale/offline interactions and native transport trials remain unverified. |
| F2 | The app is a simple UI over the same underlying headless tools, with a tray/menu-bar component and adaptive capability discovery. | **Partial.** Dashboard, local services and callable fleet actions exist. Catch-up preview and explicit local security advice call shared headless operations; complete Special/commit/push GUI coverage remains open. The new security button has HTTP/scope/JS checks, with visual acceptance pending because browser access was unavailable. Windows has a native tray; Linux/macOS currently use foreground/autostart fallback rather than equivalent native tray/menu-bar behavior. |
| F3 | Consent, explicit planning and rechecking govern supported actions; ordinary observation must not mutate. | **Partial.** Catch-up planning/apply code, audits and consent paths exist. Common action/policy/result integration and attended remote-approval protocol are unfinished. Several fleet paths call Git directly instead of one shared operation engine. |
| F4 | Private state repository has an explicit organization/ownership contract and does not abuse GitHub at large fleet/repository counts. | **Partial.** Per-machine manifests, transport intervals, semantic heartbeat and a limited SHA-conflict retry exist. Fleet-wide request budgets, batching/backoff, retention and large-scale acceptance for extreme counts are not complete. |
| F5 | Programmatic use protects secrets from LLMs; repository-local agents remain self-sufficient without assuming access to every other project. | **Partial.** Local settings can be consumed without displaying values; masked/actionable checking and default-hidden key metadata exist. Explicit --show discloses to its caller, including an agent; it is not isolation. Tray logs/notifications no longer copy raw console text. Tool/access scope and remaining channel/native acceptance still matter. |

#### G. Delivery discipline and the current review boundary

| ID | User decision / required outcome | Actual state and remaining acceptance |
|---|---|---|
| G1 | Singular deliberate batches: exact scope first, preserve existing work, focused checks, objective per-repo agent notes/logs. No unsolicited broad edits. | **Controlling boundary.** This audit changes agent records and ignored audit diagnostics only. Subsequent implementation must be proposed from this comparison, not inferred from older priority paragraphs. |
| G2 | Work with DCG; do not bypass blocks, silently change settings or reroute rejected commands. | **Paused checks retained.** Previously declined supplemental/full-suite checks remain pending; none is represented as passing. Read-only source inspection and fresh separate focused test scripts here are not a retry of the rejected combined Git/PowerShell verification. |
| G3 | No commit/push without the current explicit instruction; one checkpoint permission is not standing publication permission. | **Paused.** Current GitHub repository is public. Local HEAD equals locally stored `origin/main` at `bae0217`; no fresh remote-head fetch was made. There are substantial unstaged changes. No new commit/push occurred during this audit. |
| G4 | Prove behavior on Windows, Linux and macOS and across machines before claiming complete/sharable application readiness. | **Unverified overall.** Fresh focused tests support selected components on this Windows host; no native Linux/macOS or real two-machine run occurred. Current source includes useful tools, not a fully accepted coherent app. |
| G5 | Keep a knowledge waterfall: implementation and open work in this repo's `.agents/`; higher-level coordination holds summaries/dependencies; generic shapes carry reusable guidance. | **Review restored here.** Canonical design already existed; missing reliable decision/source/evidence comparison allowed the work to drift. Do not put LLM handoffs or private machine details into product-root informational documents. |

#### What the tool actually does now

- A source user can run individual Special scripts. The standalone archive updater is the
  strongest common-infrastructure example: resolved settings, headless results, explicit
  output routing and compact logging. It is not evidence that the manager and other scripts
  use the same contract.
- A configured fleet can observe repositories, publish/aggregate selected manifests and show
  advice/dashboard information. Some callable actions exist, but the GUI is not a complete
  front door to the Special operations, nor a security-gated commit/push interface.
- Security scans consume common or explicitly selected legacy policy and now gate checked
  named-file commits and direct/Archive Sync publication. Sync check and explicit local dashboard
  advice share the reader, with local-only findings. Continuous advice and complete GUI/remote
  actions remain unfinished. No full repository/history/shelf clearance follows from this
  disposable-repository action proof.
- Common settings exist in code; the inspected real profile has not been converted. The
  prepared conversion/launcher proposal is parked. Startup, registry, schedules, live
  launchers and user settings were not changed in this audit.

#### Evidence from the preceding read-only review (2026-10-28 10:28)

- Source/status inventory before note edits: 121 Python modules across Basic, Special,
  Elaborate, OS adapters, fleet/app and root setup. All have a module docstring. AST/source
  review found only the standalone updater operation imports the shared runtime logger.
  Frozen archive and tests are outside that module count.
- Worktree baseline: **85 file entries: 37 tracked modified, 11 tracked deleted, 37 untracked;
  none staged.** These are actual changed/new/deleted files, including source moves and tests,
  not a count of personal machine paths or security findings. Earlier status counts are dated.
  The global-ignore read warning prevents treating this inventory as comprehensive hygiene proof.
- Fresh unittest scripts: updater 18; archive-manager settings 28; fleet settings 38;
  security-policy settings 24; existing-settings conversion 33; settings setup 22;
  active scanners 24 (23 passed, one native symlink skip). **187 cases total: 186 passed,
  one skipped.** These are disposable/mocked component tests, not a full suite or live rollout.
- Duplicator argument, selection, local-repository and operations checks passed; peer checks
  passed (nine checks); import-direction check passed (81 files). Twelve public `--help`
  invocations from outside the checkout succeeded without creating a settings profile.
- Product source hashes are retained only in caller-owned ignored audit output; verify against
  that baseline after note edits. GitHub connector confirms public visibility, but no fresh
  remote refs/history scan or fork/dependency/security-alert inventory is implied.

#### Distinguish user decisions from implementation choices and unresolved questions

The user selected one external local settings document, optional enrollment, predictable
output/logging and a coherent common product. The exact v1/v2 field layout, conversion receipt
format, backup layout, typed confirmation words, local launcher drafts and log rotation sizes
are agent implementation choices. Review them against those requirements; they are not new
user requirements or permission to activate them. A conversion workflow is supporting work,
not the central purpose of the app.

The later user discussion settled `gitso`, all three optional engines/none, portable master plus
local policy, complementary private Git/folder/tailnet conduits, and explicit recursive/archive
membership choices. Their remaining implementation is not another product-choice question.
Detailed shared revision ownership, provider/version adaptation, archive setup UX and a persisted
relocation locator remain engineering/design work. `sync_self.py` is a naming suggestion only.
The earlier multiple-active-settings and
org/source-root storage suggestions were superseded by the single external local document.
Update versus archive sync is a behavior distinction, not a public/private repository rule.

**Execution direction after user approval:** source work proceeds in named bounded batches,
with focused verification and notes/log updates. Connect one policy-aware operation end to end,
then extend the common contract. Preserve the five-stage architecture plan and the remaining
acceptance comparison; do not replace product work with a settings/launcher rollout detour.

- **Deferred final fleet verification (2026-10-28).** DCG blocked the supplementary combined
  Git/PowerShell whitespace/log-marker check (windows.filesystem:windows-filesystem-semantic-unverified,
  allow-once 487079). No reroute or exception was attempted. Earlier whitespace checks passed;
  the final 38-case integration suite and 80-file import check passed after the root-normalization
  fix. This remaining supplementary batch needs explicit user direction before retrying.

### 2026-10-27 — Finish the reviewed layer reorganization

- Apply the new ruling in knowledge/architecture-layers.md to the remaining operation families.
  The selected update_archive, duplicate_org and archive_manager public paths/source split
  are complete. Review remaining entry-point names/helper grouping before further moves;
  inventory/security names and presentation diagrams are still separate review work.
- Produce the full source/destination/caller map, including all current Special entry points,
  the legacy fleet/app tree, tests, launchers, packaging and documentation. Preserve agreed
  roles/dependencies, direct script use and callable APIs. Settings, archive-planner and
  duplicator-helper grouping and the selected public-command/local-manager split are complete.
  Thin older-script compatibility wrappers remain for existing launchers. Do not combine source
  moves with policy changes or actual settings migration. Preserve retained resume, registry,
  report and launcher locations. No real user launchers were regenerated.
- Extend the implemented `gitso.py` source catalog/dispatcher/menu with shared declared effects,
  prerequisites and structured results. Reuse it for GUI discovery while invoking the same
  callable operations; no execution during discovery and no duplicate authorization engine.
  Installed source/bundle entry wrappers and full GUI integration remain open. Naming is settled.
- Build command documentation from source: essential top-of-file module docstrings for every
  script/helper, useful docstrings/type hints on important functions, and shared parser/effect
  metadata for help/menu/generated docs. Audit current headers against actual names/behavior
  before trusting generation. Keep the catalog as handler/parser references, not copied prose.
  Help/documentation extraction must not execute tools or read private configuration. Add
  discoverability/doc parity checks when the catalog and extraction path are implemented.
- Review archive front-door behavior during functional integration: update_archive refreshes existing checkouts;
  archive_sync additionally offers upstream discovery/cloning and separately selected apply
  classes. Current defaults differ (updater acts unless scan-only; sync plans unless selected).
  Special/archive_manager.py --install still combines folder registration with launcher
  creation. Propose an explicit archive add/list/remove setup/CLI flow and decide that coupling
  before changing it; a one-off --root remains usable without registering anything.
- **Archive manager functional follow-through.** The source is now in Special with private
  manager/updater/sync/plan/registry helpers; scheduling stays Elaborate. The standalone updater
  now uses common settings/results/logging; next adopt that contract in manager paths. Preserve per-archive
  update/sync modes, explicit invocation choices and approval boundaries. Current refresh uses
  the shared sync engine for both modes and retains its report defaults/exit-code interface;
  do not silently change those while integrating the standalone updater. Persisted settings
  component identifiers and all actual user data remain unchanged.
- **Actual archive rollout is paused.** This is conditional supporting work, not the next
  product milestone or an approval request. Before any separately authorized real conversion, review/regenerate
  existing per-archive/refresh-all launchers so they use the current profile-aware manager path;
  stop independent old writers and establish receipt-only state ownership during cutover.
  Existing user launchers and state have not been changed. The eventual migration workflow must
  preserve originals, recover partial activation explicitly and never re-import receipt copies
  when common settings are missing. Native launcher/locking verification remains open.
- Separate archive recognition from update eligibility. The user's criterion is a chosen
  collection with actual Git checkouts; support .git files as well as directories. Pointed or
  system discovery yields candidates and respects hard exclusions; never auto-enroll. Decide
  nesting/depth explicitly because today's manager checks eligible direct children only.
- Resolve sync naming in the complete map: public reference updating is a common use, not a
  restriction that forbids private repositories. Existing archive_sync's upstream discovery/
  cloning/reconciliation also applies to public collections. Personal cross-machine sync belongs
  to Elaborate. sync_self.py remains a suggestion; do not rename or discard existing behavior
  based only on visibility/ownership, or automatically push/pull because a command is called sync.

### Supporting backlog from 2026-10-26 — Bring the product together

Canonical decisions: [knowledge/product-contract.md](knowledge/product-contract.md). The goal
is cross-machine repository visibility and action, assembled into one app while every Special
operation stays useful independently. The conversation comparison above now controls priority;
this older sequence is supporting backlog, not execution authorization. Finish and verify one
agreed bounded change at a time.

1. **Integrate the common settings foundation.** Use
   [knowledge/settings-schema.md](knowledge/settings-schema.md) and `Special/_settings/`.
   Guided standalone updater setup and archive-choice/receipt readers and savers are connected.
   Active scanner common-policy reading and explicit common-policy save helpers are connected.
   Fleet CLI/app readers and savers now share common enrollment, including app settings commands,
   the dashboard client choice and startup/tray/autostart profile routing. Legacy-only profiles
   remain usable. Archive/policy-only setup now has reviewed plan/save/status/resume and original-byte
   retention, with a separate launcher plan. Live launcher/job review and activation are now
   paused; they are not the next product step. Broader conversion and settings-loss
   evidence across enrolled fleet components remain open. Keep private candidates
   separate from summaries and require review/conflict choices and quiet legacy writers. Current mapping
   preserves machine/transport definitions, separate CLI/app selections and behavior, archive
   preferences vs retained receipts and protected values; unknown/older formats require review.
   Complete the coordinated legacy transition before actual cutover, so writing a common
   file cannot leave two independently editable authorities. Preserve originals and never
   silently change action consent or enable features. Explicit relocation/locator handling is
   still needed. The standalone updater now uses common settings/results/logging and guided
   preferences; retain that acceptance baseline while adding consumers. The real default
   profile's read-only masked preview had no conflicts for its archive/policy inputs; no user
   file was written. No automatic migration or actual user-file edit is authorized.
   **Existing-settings rollout.** The scoped action now shows the selected archive/policy inventory,
   preserves original bytes and supports interrupted-write status/resume. Launcher plans name
   existing repair commands but do not execute them. Read-only Windows job/launcher review and
   inert native replacement previews are prepared outside the public checkout. The former
   recommendation to seek a first live switch is withdrawn as the current next step. Only a
   separately reopened, scoped rollout could require fresh source/target/writer checks.
   Visible metadata is not proof against inaccessible process command lines or unknown
   wrappers/manual writers. Keep scheduling off unless separately selected.
   Native Linux/macOS, installed-launcher rollout and broader fleet conversion need their own
   checks. No live configuration/launcher/enrollment change is authorized by preparing this code.
   Existing deferred guard checks remain pending.
   Complete the policy show/add/remove/revelation UI over the tested save helper, then unify
   recovery/hygiene/advice/action consumers deliberately. Archived policy code stays frozen.
   Establish policy revision/freshness checks at supported action gates and an enrolled-profile
   settings-loss/cutover ownership contract; archive receipt v2 alone is not that global proof.
   Agent notes may point at the location but are not runtime configuration. Acceptance: an unenrolled Archive Updater
   works with Git alone; configured preferences are remembered, editable and overridden per run;
   missing optional capabilities do not masquerade as failures or trigger silent setup.
   **Finish line 1:** one standalone operation uses that home and repeatable setup, with
   explicit output and configured local logging; the source checkout carries no runtime data.
   Reconcile the older CLI's single transport with the app's multiple transports deliberately.
   Adopt the implemented Special/_runtime logging seam in remaining consumers. Keep compact
   event/count records, disclosure control and visible failures; multiple sinks/routing and
   other component cutovers remain work. Do not tee raw stdout/stderr as an adoption shortcut.
   **Source updater, same finish line:** reuse `Basic/pull.fast_forward` through a reviewed
   command callable from setup/CLI/app. Define clean/tracking/fork checks and safe app/peer
   stop/restart, then prove ff-only success, refusal and preserved user data in disposable
   fixtures. Existing setup does not implement updating and version checks are report-only.
   Shell wrappers are entry points to the same contract. Frozen bundles require release updates.
2. **Setup/enrollment uses that resolver.** Capture selected roots, machine identity, local
   bindings, output/log preferences, authentication availability and selected state/transport
   options. Private state repo is optional; verify privacy/access when selected. Git/gh/SSH/
   Tailscale requirements apply only to chosen capabilities. Acceptance: repeatable enrollment,
   visible unavailable/stale states, no stored credentials, preserved settings on code updates
   and no mandatory fleet/app setup for an individual operation. Define notes integration with
   the user before implementation; no new service or transport is selected by this task.
   Add hard path/repository exclusions distinct from protected-value lists and namespace
   observe/publish/capture baskets; enforce before inspection. Whole-machine discovery is an
   explicit inventory operation with bounded scope and visible gaps, never automatic enrollment.
   Define the private state-repo layout/ownership and aggregate API budget, batching, payload
   limits, caching, heartbeat costs, backoff and conflict behavior before claiming large fleets.
   Shared settings replication is optional later work; local configuration must stand alone.
   **Guided lifecycle front door (user's direction):** expose guided setup, selection of setup
   items, update of gitSpecOps ONLY and uninstall/selective component unenrollment. Explain the
   matrix, prerequisites, destinations and effects; support cancellation and explicit headless
   actions. Reuse existing private state-repo CREATE/USE guidance, with authenticated account,
   selected name and verified private access; keep it optional. App/CLI call the same operations.
   Unenrollment stops selected observation/publication/schedules/startup entries, removes only
   receipt-owned installation artifacts and preserves user repositories/settings/logs/recovery
   by default. Real repository/data deletion is a separate reviewed action. First bootstrap
   selection/help safety is implemented; full wizard, updater and unenrollment are not yet built.
3. **Apply output policy one operation at a time.** Start with active security scan commands:
   stdout by default, configured stdout/file/both, explicit per-run override, no destination
   fallback. Support deliberately selected private directories outside Git and ignored,
   untracked destinations inside Git. Define filename/create/overwrite behavior before changing
   the writer. Acceptance: unusable output reports failure; tests prove no unexpected writes,
   correct preference precedence, exact destination and independent disclosure per channel.
   Then reconcile `archive_sync` auto-reports, `inventory_export` implicit saving, duplicator
   source-adjacent logs/resume state and manager/tray logging. Preserve required operational
   state. Archive Updater's current opt-in report files are already the starting example.
4. **Unify security policy and evidence.** Compare recovery `core/secret_scan.py`, active scans,
   hygiene and frozen rules; select external-engine integration deliberately. Resolve safe/block
   conflicts, the misleading archived report-fallback assertion, incomplete/binary coverage and
   the uncaptured Windows symlink error. Acceptance: explained differences, known positive and
   negative cases, exact local reveal without implicit log/fleet disclosure, shared callable
   policy and a clear distinction between never-publish settings and generated reports.
5. **Connect advice and action gates.** Add independently visible security facts to sync advice,
   CLI and app. Before supported commit/push actions, inspect exact proposed contents/identity/
   message or outgoing history and recheck freshness on the executing machine. Acceptance:
   prohibited introduction is blocked, removal can proceed, incomplete checking is visible and
   remote approval cannot authorize changed contents. Hooks/host protection remain explicit
   options; do not claim to control Git invocations outside this product.
   **Finish line 2:** prove useful scans/action checks with invented cases and the approved
   disposable scan/rewrite/rescan; don't require the completed fleet/app to establish security.
6. **Complete repair proof and presentation.** Reuse preserved v1 capabilities through the
   layered design; prove scan/rewrite/rescan and retained-content preservation in disposable
   repositories before real history operations. Align help, errors, severity, output schemas,
   progress and review/confirmation across tools and app using existing presentation seams.
   Acceptance: component and app results agree; native OS evidence is recorded; no migration,
   source-state proof, host protection or full-suite result is claimed without execution.
   **Finish line 3:** two-machine fresh/stale sync suggestions through a selected transport,
   shown by the same CLI/headless operation/app contract; then native OS install/update/remove
   and tray evidence. The matrix explains increasing participation and optional capability
   tradeoffs; every lower operation remains independently useful.

### 2026-10-26 — Security rebuild: existing work and remaining boundaries

- The user authorized one reviewed checkpoint commit and normal push on 2026-10-27 after scanning and necessary disclosure cleanup. This is not standing permission for later commits or pushes. The 2026-10-26 product-contract direction authorizes bounded setup/output/security/presentation plumbing work in the order above. The refitter, real history mutation, guard changes and unrelated repairs remain stopped.
- `Special/security/` now contains the active read-only scanner. The archive is frozen. The existing hygiene/legacy-test migration and observer edits still need separate review; do not silently treat them as cut-over approval.
- Next decision: compare established secret scanners, their configuration/allow-list support and the existing history-filtering engine against the actual requirements before extending custom detection or building more rewrite code. Prefer configuration and small adapters where they suffice. The active custom scanner is preliminary supplemental evidence; it is not a replacement for provider-secret coverage. This recommendation is under review, not an approved code change or tool installation.
- Resolve the guard/tool invocation boundary with the user before executing a rewrite rehearsal. Even rewriter help and the attempted alias-configuration read were blocked; no exceptions or alternate launcher have been used. Do not change guard settings.
- **Preserved v1 already has finishing behavior.** `_archive/Security/rewrite_history.py`
  and `_rewrite.py` implement plan, mirror apply/verify, push instructions, clone follow,
  cross-plan commit-ID relinking and finish. Existing tests exercise follow/relink/finish;
  the actual rewrite regression is gated. These were read, not executed in this review.
  Do not describe them as absent or invent a second finishing workflow without comparison.
- **Active rebuild remains incomplete.** Inventory v1 components and regressions for reuse,
  then reconcile the agreed layers, current policy and executable entry points. Preserve
  `_archive/Security/` unmodified. Its moved import/tool-root assumptions, stale-input
  protection, duplicated rule semantics and proof boundaries need specific review. The
  archived finish performs commit and ordinary push by default, despite an inconsistent
  printed instruction; do not run it under the current no-commit/no-push direction. Typed
  review/publish boundaries and remote-tip proof belong in the reviewed active workflow.
- Prove known positive/negative cases and retained-content expectations in disposable
  repositories, then rehearse a real approved scope in a disposable copy. Target-specific
  scopes belong in their own `.agents/`; keep sensitive findings out of tracked files.
  This project is an independently useful tool and is being evaluated for a coordinated
  publication mission; completing every planned refactor is not an automatic prerequisite
  for every target's scoped publication. No history rewrite has happened in this pass.
- Check current external-engine maintenance and execution behavior before choosing one. Primary references: https://github.com/gitleaks/gitleaks (custom rules, allow lists, hooks/CI, explicit archive/decode options; currently announces security-patch-only maintenance), https://github.com/trufflesecurity/trufflehog (secret detection/verification and local/CI scanning), https://github.com/newren/git-filter-repo (history filtering). Hosted enforcement/availability: https://docs.github.com/en/code-security/getting-started/github-security-features . Network verification, dependencies and installation need deliberate scope; no engine has been newly installed or run.
- Review policy interoperability: persistent/per-run safe values work in the active scanners but not yet in the legacy hygiene guard. Explicit block/allow conflicts need a visible decision rather than a silent precedence surprise. The symlink fixture skip did not retain the exact OS error; capture that before claiming the Windows cause is known.
- Keep full candidate values and repo-specific scan results in private ignored agent output. Binary coverage and a dedicated external secret scanner remain open; a completed offline scan is not security clearance. Cross-platform execution remains unverified.
- The previously deferred full suite remains pending; only focused checks have run for this implementation.

### Earlier product handoff — current work order above supersedes its priorities

**The goal (user's words, condensed):** one git client built for repositories everywhere --
many machines, many orgs. Glance at the tray, see every out-of-sync repository on every machine
(and what exists remotely), fix it from that view, including telling another of your machines
to commit and push. Equally usable from the terminal. Runs on logins already trusted: `gh`,
git, Tailscale, a synced folder.

**Decided (2026-10-20 .. 10-23):**

- Layers Basic -> Special -> Elaborate -> App; `Basic/` is plain git only.
- Security: parked after its phase 1; the rebuild design and the owner's leak rulings are in
  `knowledge/security-design.md`. **The old suite was moved, unmodified, to
  `_archive/Security/`** (2026-10-23, the user's explicit instruction: preserve the existing
  manifestation as a single folder). Do not edit it. Do not add files to `_archive/`.
- Manifest v5: names, branches and commits shared by default; one switch turns them off.
- Remote commands: a person may command their own other machines -- the acting machine's exact
  plan, approved at the asking machine; over the fleet's peer protocol, not SSH.
- The App: Qt (PySide6), App only; everything underneath stays standard-library Python.
- Order of work: v5 (done) -> tray on KDE and macOS -> dashboard buttons (fetch / ff-pull for a
  group and for all) plus remote commands -> phase 3c (split Sync Suggester into the layers) ->
  remote everything.

**Done:** `Basic/reset_keep.py`, `Basic/commit.py`, `Basic/_objects.py`, `_run.stream`, ref and
identity facts; `shared/` removed (version read from `pyproject.toml`); manifest v5; the Qt
trial `tests/probes/qt_shell/` (works on Windows 11). PySide6 6.12 is in this machine's `.venv`.

**Broken by the move, waiting on the user's word -- do not touch until told:**

1. `tests/repo/test_repo_hygiene.py` imports its leak rules from `Security` and now fails. It is
   this public repository's leak guard, so it should not stay broken.
2. `tests/security/test_security.py` imports `Security` and fails.
3. `git-sync-suggester/core/observer.py:278` tells the user to run
   `Security/rewrite_history.py follow`, which no longer exists.

Suite: 47/49 on Windows (those two). Also: `python _archive/Security/<command>.py` does not
start as it stands -- from inside `_archive`, Python cannot find `Basic`.

**Next:** (1) the user decides the three references; (2) on the Debian 13 KDE box: pull, run
`tests/run_all.py` (never run on Linux), then the Qt probe per its README; (3) the Qt App (tray
+ window) on Windows, KDE, macOS; (4) dashboard actions + remote commands; (5) phase 3c;
(6) remote everything.

**How to work with this user (learned 2026-10-23):** do exactly what is asked, in the words
asked, and nothing beyond it. A plain instruction is settled -- do not argue alternatives,
re-interpret, add files, or "improve" what was asked to be preserved.

**Leftover for the user to delete (a guard hook blocks `rm -rf`):** two empty failed venv
folders (`.agents/output/qt-trial-env`, and one in the session's temp scratchpad) and moved-aside
caches in that scratchpad.

### 2026-10-21 — HANDOFF: back to the product; the order of work (user's decision)

The user stepped back from Security to the product: one git client built around many repos on
many machines -- see every out-of-sync repository everywhere (and what exists remotely), and
fix it from that view, on trusted auth (`gh`, git, Tailscale, a synced folder). The order:

1. **Manifest v5 -- DONE 2026-10-21** (names, branch, head by default; `share_names`).
2. **Linux tray (KDE Plasma, StatusNotifierItem) and the macOS menu bar** -- in **Qt via
   PySide6** (decided 2026-10-22; App only). First a small trial (tray + window over the display
   contract) here and on the Debian 13 KDE box, which the user pulls and runs from the repo (no
   release needed yet; run `tests/run_all.py` there first -- never yet run on Linux). Then the
   first real run of the fleet. **Trial built 2026-10-23:** `tests/probes/qt_shell/` -- tray +
   native window over the display contract; works on Windows 11 (demo and a real library,
   read-only). Next: the user runs it on the Debian 13 KDE box (instructions in its README).
   Note: Windows Application Control here blocks any *newly created* `python.exe` (a fresh venv
   in the temp folder or `.agents/output/` both failed), so PySide6 went into the repo's `.venv`.
3. **Dashboard buttons:** the basic actions plus **fetch group, fetch all, fast-forward pull
   group, fast-forward pull all** -- each the same command as the terminal's, plan -> confirm.
   **With them: remote requests** (rule amended 2026-10-22): "B, commit these and push" from A,
   B's exact plan approved by a person at A, B re-checks and acts; over the peer protocol, not
   SSH. Avenues for B's uncommitted work: B reports now; B sends a snapshot (content leaving B
   -- confirm with the user when built); B commits and pushes; if B cannot push, B hands A a
   git bundle of the exact commit and A pushes it.
4. **Phase 3c:** part out Sync Suggester -- its high-level `sync_suggester` operation in its
   place, its components in theirs (layers).
5. **Remote everything, on demand:** gather remote metadata (provider) for comparison and
   exploration -- what is on GitHub that no machine holds, and how remote heads compare with
   v5's per-machine heads. Discussed 2026-10-21; not designed.

**Parked (2026-10-21), with what brings each back:** the Security rebuild after phase 1
(phases 2-6, `knowledge/security-design.md`) -- the next time a repository needs cleaning or is
about to go public; the old `Security/` tools keep working until then. The watch list's levels
(never / watch), per-repository acceptance, and push-time prevention -- same trigger. Phase 1's
Basic operations stay and serve the fleet (commit, reset_keep, identity facts).

**The old Security tools are in active use** (2026-10-22: another public repository cleaned with
them). The user's rulings and requests from that run are in `knowledge/security-design.md` ("The
owner's rulings"): the login is safe everywhere; the real email and the home-folder name are
leaks; other local paths are quiet; leak-describing text near a commit id is a leak; a
`safe.txt` list and `--safe`; `scan_tree` must drop the owner as `scan_history` does. Those go
into the rebuild. **The working suite is preserved in `_archive/Security/`** (user,
2026-10-23): an exact, unmodified copy of the `Security/` folder. Never edit it. Open: whether the "local paths are quiet" ruling relaxes this repository's own
no-absolute-paths rule.

**Flake seen once (2026-10-21):** `tests/fleet/test_git_client.py` timed out (3 s socket read
on its loopback test server) during a full-suite run; it passed alone five times and the next
full run was 49/49. Watch for a repeat before widening the timeout.

### 2026-10-20 — HANDOFF: the Security rebuild is designed and agreed; phase 1 begun

**Read [`knowledge/security-design.md`](knowledge/security-design.md) before touching any security
code.** It supersedes the 2026-10-19 19:45 section below (the design question it raised is
settled). Decided with the user:

- **Placement A:** no Security layer; `Special/security/` (components + one-repo commands),
  `Elaborate/security/clean_history.py`, general rewrite machinery in plain `Special/`.
- **Rebuild, not move:** `Security/_rewrite.py` and `Security/rewrite_history.py` are retired at
  the cut-over. No tag, no `_archive/`, no compatibility -- git history keeps the old code.
- **Typed `REWRITE`** for the rewrite, never skippable by `--yes`; the review stop is typed too.
- **`Basic/reset_keep.py` built** (2026-10-20); `follow_rewrite` will always present move now /
  later / by hand, never move unasked.
- **No machine is enrolled anywhere** -- nothing needs the old code kept working.
- **`shared/` deleted by the user**; the version is read from `pyproject.toml` by
  `git-sync-suggester/core/version.py`.

**Phase 1 (Basic) done 2026-10-20** -- see the work log. **Next: phase 2**, general history
rewriting in `Special/`: `_rewrite_rule`, `_rewrite_plan`, `_history_rewriter`,
`_rewrite_proof`, `_commit_map`; `rewrite_history`, `follow_rewrite`, `relink_ids`; the gated
end-to-end specimen test (cases listed in the design document).
**Open:** the watch list's name; deleting three 2026-10-19 plan folders in the per-user
`security/` folder (they hold real values; awaiting the user's word).

### 2026-10-19 19:45 — (superseded 2026-10-20 by security-design.md) the Security design was unsettled

**Stop and read this before touching `Security/`.** The session ended with the user rightly
frustrated: the agent proposed three different shapes for the Security code in a row, and the
last one contradicted gitSpecOps's own architecture (it put security plumbing in `Basic/`).

**What the user said, to carry forward (their words, condensed):**

- **`Basic/` is for bog-standard git and host operations, one at a time.** Security work is not
  that. Never put security code or plumbing in `Basic/`. "These are not bog-standard git
  operations ... you need to bump up some levels." The user wondered whether the first tier
  belongs in `Special/`. Not decided.
- **Structure must follow the gitSpecOps spirit:** smaller operations, each callable on its
  own, reused by higher ones -- repeated, recursive, or in sequence. The main security
  operations are named as such and call the lower pieces in order. `rewrite_history` is *one*
  component (called by something else, with flags), not the centre of Security.
- **Security is more than history rewriting.** Today it is mostly that. The gaps the agent
  named: prevention (a check of outgoing commits and of each machine's git identity -- the
  personal address got onto commits through a machine's config) and host settings (secret
  scanning, push protection, branch rules). Whether and how to build these: **not decided.**
- **Hand-holding for big operations.** Critical stops must really stop: say what to inspect and
  where (Sourcetree, the files, "have your LLM look"), say the tool will wait, and continue only
  on a typed word -- never a y/N or "press any key" that can be hit by accident. The rewrite
  run had no stop between "rewritten" and "pushed"; the user wants the tool to get them all
  the way there, holding their hand. Concise output, not verbose.
- **The never-publish list must be visible.** If setup or any tool would create it, show what
  it would write first and offer to add custom entries; give a clear way to edit it later (the
  app must have one); every checker prints what it loaded before checking. **Open question,
  unanswered:** print the values in full or masked (the agent suggested masked).
- **Names from other machines: yes, by default** (manifest v5, decided 16:30; not built).
- **The user wants a full setup walk-through** of the fleet app "as it stands", seeing
  everything it sets up -- after the above is resolved.

**What to do first next session:** agree the Security structure *with the user* before writing
code. Read `knowledge/architecture-layers.md` (the import rule ranks `Security` between Special
and Elaborate) and present one consistent proposal in the project's own terms, briefly. Do not
redesign in chat three times.

**Other machines -- the sticky note the user can send now** (plain git, tested here on fake
clones in every state: clean-stale moves; unpushed commit or edited file is held; current is
left alone; a second run changes nothing). For each high-risk checkout (the Alpha repos and
gitSpecOps): fetch; if it shares history with `origin/main` say "same"; else count commits not
in `origin/main` nor `origin/main@{1}` and edited tracked files; if both are 0, `git reset --keep
origin/main`, else print HOLD. Replace `<library>` with that machine's folder:

```powershell
$repos = @(Get-ChildItem <library>\Sb4ssport-Alpha -Directory | ForEach-Object FullName) + '<library>\<you>\gitSpecOps'; foreach ($p in $repos) { if (-not (Test-Path "$p\.git")) { continue }; $n = Split-Path $p -Leaf; git -C $p fetch -q origin; git -C $p merge-base HEAD origin/main *> $null; if ($?) { "same $n - already on the new history"; continue }; $mine = git -C $p rev-list --count HEAD --not origin/main 'origin/main@{1}' 2>$null; $known = $?; $edits = @(git -C $p status --porcelain --untracked-files=no).Count; if (-not $known -or $mine -ne '0' -or $edits) { "HOLD $n - unpushed commits: $(if ($known) { $mine } else { '?' }), edited files: $edits" } else { git -C $p reset -q --keep origin/main; "ok   $n - now $(git -C $p log -1 --format='%h %s')" } }
```

```sh
for p in <library>/Sb4ssport-Alpha/*/ <library>/<you>/gitSpecOps; do [ -e "$p/.git" ] || continue; n=$(basename "$p"); git -C "$p" fetch -q origin; if git -C "$p" merge-base HEAD origin/main >/dev/null 2>&1; then echo "same $n - already on the new history"; continue; fi; mine=$(git -C "$p" rev-list --count HEAD --not origin/main 'origin/main@{1}' 2>/dev/null) || mine='?'; edits=$(git -C "$p" status --porcelain --untracked-files=no | wc -l | tr -d ' '); if [ "$mine" = 0 ] && [ "$edits" = 0 ]; then git -C "$p" reset -q --keep origin/main && echo "ok   $n - now $(git -C "$p" log -1 --format='%h %s')"; else echo "HOLD $n - unpushed commits: $mine, edited files: $edits"; fi; done
```

`--keep` moves the branch
and the files but refuses to overwrite uncommitted edits; it does not protect unpushed commits,
which is what the count is for. The older `rewrite_history.py follow PATH --match` does the same
with a stronger proof (reflog files).

**State of the code (committed, pushed at 17:20; nothing since):** `Security/` = `scan_tree`,
`scan_history`, `scan_secrets`, `scan_folder`, `rewrite_history` (plan / apply / verify / finish
/ follow / relink) over plumbing `_rewrite`, `_report`, `_history`, `_contents`, `_patterns`,
`_seeds`, `_repo`. Suite 48/48 on Windows. The never-publish list now holds the old account name
(private file, outside the repository).

### 2026-10-19 17:20 — where things stand

**Sb4ssport-Alpha: rewritten, published and finished on this machine (17:00).** All ten repos
force-pushed by the user, every checkout here moved, 64 quoted ids relinked (four commits, each
checked to name the same commit as before), committed and pushed normally by the agent. An
independent rescan of every rewritten copy found only the org's own name, the login (kept) and
the IOCCC constant (kept); every identity is the noreply one. An untracked `NEW-NOTES.md` in
Sb4ssport-Authority is the Authority window's to deal with -- **not ours**. The Authority window
should be told the history changed before it resumes.

- **Other machines** (nearly all hold some of these repos, and gitSpecOps itself may be stale):
  one line each, from a fresh temporary clone so it works however stale that machine is --
  see the work log 17:20, built on `follow PATH --match TEXT` (folder
  sweep: checks everything first, lists refusals, asks once). Smoke-tested here: 11 found, 0
  to move.
- **No rulesets on the Alpha repos** -- the user declined (2026-10-19 16:50). gitSpecOps keeps
  its own.
- `finish` now commits exactly the files it relinked and pushes them (`--no-commit` to stop).
- **Next:** enroll this machine in the foreground and show the user its dashboard; then the
  Linux box. `fleet_app.py preflight` is green here (git, gh, Tailscale, port 8760).

### 2026-10-19 16:15 — the Alpha run, as planned

**Sb4ssport-Alpha: ten plans written 2026-10-19 16:16.** Made after the Authority window
finished committing (122 commits incl. its 15:37 checkpoints), with the IOCCC constant kept and
the old account's noreply address claimed. Plans: `.agents/output/security/<repo>/
rewrite-20261019-1616*` (ignored). Cross-checked with Authority's evidence: 12 signed commits
(9 + 3), generated caches removed. A rehearsal of Orbital-Workshop verified clean; the
`rehearsal-*` folders are deletable (`rm -rf` is blocked by the user's guard hook).

The run, from this folder:

1. `python Security/scan_folder.py <Sb4ssport-Alpha folder> --online --plan --keep <IOCCC magic>`
   (the IOCCC value is a published contest constant in third-party archives; the full report
   names it). One table, one plan per repository, one printed `apply` line for all of them.
2. Review each plan's `summary.txt`; `apply` them all (one typed confirmation). It prints the
   forced pushes and one `finish` line.
3. Run the printed pushes (the user's step).
4. `finish <every plan>` once: moves this machine's ten checkouts (`follow`) and updates the
   commit ids they quote of each other (`relink`); then commit + push those edits normally.
   Other machines: `follow <repo>`.
5. (Dropped by the user: no ruleset on these repositories.) Secret scanning + push
   protection when each goes public remains a suggestion.

**Decided by the user for Alpha (2026-10-19 16:10):** the other account (its old personal name, under
both the personal address and its own noreply address) becomes the main identity -- `--mine`
its noreply address; losing "Verified" on the signed commits is fine; author names of the form
`<login>@<machine>` and `<login>@unassigned` are the user's convention and stay. The login in
work-log headings is the public handle the commits carry anyway: kept. Authority has finished
committing; no more work there until the rewrite is done.

**Fixed today while getting ready (each would have broken or weakened the Alpha rewrite):**
see the work log, 16:15. In short: placeholders with backslashes crashed filter-repo; values in
file *names* survived; an old personal address under a second name was left on 86 commits and
never searched for in contents; `--mine` could not claim a noreply address; `follow` matched
commits by timestamp and could hide same-second local work; 253 lockfile checksums and several
fixtures read as secrets; archives, Office files and image metadata were not opened; "nothing
else changed" was not checked at all once any path was removed.

**This repository's rewrite: done (14:20).** 4 of 5 machines moved; the fifth (an old Windows 10
machine elsewhere) the user is content to leave -- `follow` handles it whenever it is touched,
and Sync Suggester now flags such a clone ("upstream history was rewritten"). GitHub ruleset on
`main` since 2026-10-19 15:21: no deletion, no force push, linear history (a stale clone cannot
merge the old history back in). A future rewrite of this repository must pause that ruleset for
its one forced push. Still to do by the user: GitHub → Settings → Emails → "Block command line
pushes that expose my email".

**Manifest v5: decided 2026-10-19 16:30 -- names, branches and head by default** on every
transport, one setting to turn them off (`knowledge/manifest-privacy.md`, "Proposed schema v5").
Not built. The number v4 is already taken by the at-risk fields.

**Then:** the first test on the Linux box (the suite has never run off Windows), the foreground
fleet peer on this PC and that box (the user has never seen their dashboard), the tray trial,
phase 3c.

### 2026-10-19 13:45 — where things stand (read this first)

**Done 2026-10-19 14:20 — this repository's public history is clean.** The user applied the
rewrite and force-pushed it (`main` on GitHub: 82 commits, every author/committer the noreply
address; tailnet addresses, machine names, a local folder path and private org names replaced by
placeholders in every old file version and message). Verified before the push (same commits,
current files byte-identical) and after it: `scan_history` over what GitHub serves finds only
`Sb4ssport-Alpha`, kept on purpose. This checkout was moved onto the new history with
`git reset --keep origin/main` after confirming a clean tree and identical tree ids.

- The first `apply` was refused by its own verification (the rules-file comment bug, see the
  work log); fixed, re-planned, applied cleanly.
- Accepted: the 5 commits made on GitHub's website lost their "Verified" badge.
- **Other clones** (the KDE box, any other machine): `git fetch origin` then
  `git reset --keep origin/main` if clean, or re-clone (now: `rewrite_history.py follow`).
  4 of 5 machines moved as of 2026-10-19 15:10.
  **Tested 2026-10-19 on a stale copy:** old and new histories share no commit, so `git pull`
  does *not* silently merge the old history back — merge mode says "refusing to merge unrelated
  histories", ff-only refuses, rebase mode stops on a conflict at the first old commit (run
  `git rebase --abort`). The real ways it returns are deliberate: `--allow-unrelated-histories`,
  pushing through that rebase, or pushing a branch from the stale clone. "No common ancestor
  with its upstream" is therefore an exact detector for a clone that predates a rewrite.
- Optional: GitHub may serve old commits by SHA from caches for a while; with no forks or pull
  requests, GitHub Support can purge them. Short SHAs quoted in old notes no longer resolve.
- The plan folders under `.agents/output/security/gitSpecOps/` hold the real values and a spoiled
  and a rewritten clone; they are ignored and can be deleted.
- How to do this for another repository, from the gitSpecOps folder: `python Security/
  rewrite_history.py plan <repo> --online`, review, `apply "<plan folder>"`, run the printed push,
  then the printed fetch + `reset --keep`. Plan *after* the last commit; no commits until pushed.

**Next target: Sb4ssport-Alpha's ten repositories, before they are made public.** Sb4ssport-
Authority (another VS Code window) has collected evidence and a draft plan (paths in the user's
paste; private, under that repo's ignored `.agents/output/`). Plan agreed in chat: scan each repo
with gitSpecOps's own `scan_history` (reports land in *this* checkout's
`.agents/output/security/<repo>/`, readable by both agents), cross-check against Authority's
numbers (112 commits, 196 email fields, 29 generated-cache paths, 12 signed commits), then plan
per repo. The missing pieces listed here on 13:45 (archives, quoted commit ids, a wrapper for
many repos) were built at 16:15 -- see the section above; gitleaks stays optional. Authority's
separate code-safety concerns (Ground-Support deletion validation, Windhawk restore, DCG
installer trust) belong in those repos as their own fixes.

**Security/ — what exists now** (details in `knowledge/architecture-layers.md`, last revision):
`scan_tree`, `scan_history` (masked on screen, full report to the ignored output folder, every
commit identity listed), `scan_secrets` (gitleaks when installed), `rewrite_history`
(plan / apply / verify). Identity comes from the machine (git, gh, hostname, home folder,
tailnet, GitHub orgs with `--online`) plus the private never-publish list at
`<per-user gitSpecOps folder>/security/never_publish.txt` (seeded with the user's orgs except
Sb4ssport-Alpha; the offline hygiene test reads it too).

**Then, from the product path:** run the suite on the KDE box; a foreground fleet peer on this
PC and the KDE box (show the user their dashboard for the first time); the tray trial in `App/`;
phase 3c. Setup (one front door) offers the optional pieces: tray dependencies and gitleaks.

### 2026-10-19 11:30 — decisions taken, and the test audit

**The suite has now been read and run.** Full findings and the repair order:
[`knowledge/test-suite-audit.md`](knowledge/test-suite-audit.md). Windows 11, 44/44 files pass,
53 s. Two confirmed defects come before any enrollment that relies on a verdict:

- [x] **`fleet safe-to-wipe` said SAFE (exit 0) over the only copy of work.** Fixed and pinned
  2026-10-19 (and `fleet audit`, same cause).
- [x] **Duplicator cleanup `rmtree`d a non-repository folder.** Fixed and pinned 2026-10-19.
- [x] **The observer / fleet map now sees no-remote repositories and side-branch work**
  (audit #3, manifest schema v4, 2026-10-19). Still open from `knowledge/at-risk-work.md`: the
  fleet-wide `at-risk` command and "probably the same" labelling for root-only matches.
- [x] **Duplicator destination folders — decided 2026-10-19:** an empty folder is used; a
  non-empty one is refused, as git itself refuses, and the user fixes it. No "adopt a non-empty
  folder" scheme.
- [x] **Default state repository name — decided 2026-10-19: `<login>/gitspecops-state`**
  (setup suggests it; any owner/name may be entered instead).
- [ ] **Personal data in public history** — see `knowledge/repo-privacy-and-history.md`
  (2026-10-19 rescan). The user decides on a history rewrite; 0 forks makes now the cheapest time.

**Decided by the user this session:**

- **Yes: one app named gitSpecOps**, Sync Suggester as its home screen. The folder is **`App/`**:
  tray / menu-bar app plus the dashboard.
- **Yes: the tray trial**, on this Windows machine and the Debian box. **Debian runs Wayland**
  (desktop environment still to confirm: GNOME needs an extension for tray icons; KDE does not).
- **The 2012 iMac is optional** — it will be sold; use it while it lasts, skip it if the toolkit
  cannot support Catalina. Newer Macs are available for testing.
- **Yes: phase 3c and `App/`**, kicked off.
- **Yes: sleep / shutdown / lock triggers** (item 5).
- **Yes: diff, commit, branch/switch, stash in `Basic/`** (path step 6).
- **The user wants to act through gitSpecOps**: alerts that say "commit here / pull there", and
  the fix done from the same place. Cheap watching (kernel file events, no polling) on all three
  OSes is the requirement behind "simple watchdogs".
- **New ask: machines instructing each other** ("next time online: push this"), and
  **LLM-driven operation** across machines (an agent on one machine asks a peer to commit/push).
  Design discussion opened in chat; not decided. Existing design note: "Actionable Fleet
  dashboard … a narrow device job protocol rather than a generic remote shell" (below).
- **Scheduled archive refresh: the user is removing it for now** (it has been failing since
  2026-09-01; it still pointed at the deleted `gitArchiveUpdater\` folder). The three archives'
  `update_archive` launchers are stale for the same reason.

**Decided later the same day:** the effect-rule rewrite (done in the brief, both READMEs,
CLAUDE.md/AGENTS.md, `architecture-layers.md`, HANDOFF phase 5 and the local diagram file — the
*published* diagram canvas still shows the old footer); mailboxes; CLI-first with flag strings
and settings, **not** blanket `--json`; the dashboard stays with Sync Suggester (a setting
chooses terminal or dashboard), the tray is `App/`, scheduling and start-at-login stay below
`App/`; skins deferred to `modern` only; **KDE Plasma** on the Debian box. Recorded in
`architecture-layers.md` "Revisions, 2026-10-19".

**Still unanswered:** manifest schema v4 with names (item 3), the auto-update basket's details
(item 4). The user has **never seen their own dashboard** — show it on the first enrollment.

### 2026-10-19 — product direction: the vision, what was decided, what is owed (HANDOFF)

A long design discussion (2026-10-17 to 10-19) re-anchored the product. **Nothing in the code
changed.** Read this section first; [`HANDOFF.md`](HANDOFF.md) points here.

**The user's vision, in their words, and the one that must stick:** relegate Sourcetree, GitHub
Desktop, GitKraken and the git CLI to *surgical tools*. Sync Suggester takes over day-to-day use.
The result is that every repository is more up to date on every machine, and **at a glance the
user can SEE what is out of sync on any given machine** — "go back to machine-A and push x, y, z;
machine-B push some more; machine-C pull and push a mess; machine-D hasn't been online in a while
and has even more." On boot or wake, pull-ff everything (including folders of public repos kept
only to stay current). A tray app with notifications, a menu and a popup, or a dashboard of
connected machines and repo states across them.

**A caution carried from the start of the discussion:** an earlier session in this conversation
repeated "44/44 green" from these notes as fact without opening a test or running the suite. The
user was rightly alarmed. Test counts in these notes are counts of *scripts that exited 0*, written
by the same sessions that wrote the code. **No one has audited what the tests assert.** Treat
every pass count here as a claim until the suite has been read and run.

#### Decided by the user

- **A tray app, on Windows, Linux and macOS. All three are critical.** The tray is a must, not an
  extra. Debian 13 with a desktop tray and macOS's menu bar both already show third-party icons
  (the user sees another product's icon in both).
- **Dependencies are acceptable for the App, and so is a native helper.** The operations stay
  stdlib-only; the optional App may carry a dependency or ship a small native shell. Preference:
  something that **looks the same everywhere**.
- **The icon should carry information:** this machine out of sync / syncing / in sync, plus a dot
  or coloured symbol per other enrolled machine, and some sign of whether each is online.
  Dense at 16 px; **experiments are required**, viewed on all three OSes.
- **One front door for setup** (agreed): one re-runnable flow asks base preferences — checks
  (git, host login), roots, transports, baskets, triggers, notifications, tray and
  start-at-login — and **every answer stays changeable** later (re-run setup or a settings page).
  Today `run_setup` asks nothing and `fleet setup` is a separate second setup.
  **Optional components it offers (decided 2026-10-19):** the tray app's dependencies, and
  **gitleaks** for `Security/scan_secrets.py` (winget / brew / package manager). Neither is
  ever required; the tools say how to install them when absent.
- **Transports to try for real:** the private GitHub state repo (valued: "a special git repo
  just for gitSpecOps to control"), **Dropbox** and **Syncthing**. **Obsidian is out** — the user
  does not use it, and its sync is paid. Drop the "vault note" idea; the private repo can carry
  human-readable per-machine notes instead (GitHub renders them, readable from a phone).
- **Broadcast on sleep / shutdown** is wanted: not a scan (the peer already knows its state from
  file events) but an immediate publish that bypasses the 1800 s repo-transport rate limit, ideally
  saying "going to sleep" so peers show "asleep since 22:10" rather than "not seen".
- **A second household user gets their own fleet on their own two Macs** — the first
  stranger's-first-run test of the front door, when the time comes.
- **State repo name:** decided later the same day — the default is `<login>/gitspecops-state`
  (changed in `fleet_app.py`); the user may name any owner/name.

#### Recommended, awaiting the user's yes

1. **One app, named gitSpecOps, whose home screen is Sync Suggester.** Tray = glance, route lines,
   notifications. Dashboard/popup = the route, the repo×machine grid, and daily git operations.
   Operations = a runner for archive update, org duplication, inventory, each planned, shown and
   confirmed. The terminal stays a first-class entry point. Sync Suggester's engine stays in
   `Elaborate/` (it *is* "across machines and across time"); `App/` is the prominent part.
2. **Rewrite the effect rule — it contradicts the vision.** The diagram footer says "the peer, tray
   and dashboard only observe", and `architecture-layers.md` plans a test that everything reachable
   from them or the scheduler is `EFFECT = "none"`. Committing/pushing from the app and ff-on-wake
   both violate it, and the archive scheduled task (`--update`) already does. Proposed:
   **background** (peer, scheduler, wake/sleep triggers) observes only, except a **standing
   consent the user configured** (an auto-update basket: ff-only, clean, behind-only — as the
   archive launchers already do); **foreground** (a tray item, a dashboard button) runs the same
   command as the terminal with the same plan/show/confirm. Then update the diagram and phase 5.
3. **Manifest schema v4 before any enrollment:** the private repo transport and the live tier
   carry repository names, branch names and the head commit; the folder transport stays
   names-free unless opted in. Rationale is already in `knowledge/manifest-privacy.md`: on a
   private GitHub repo the salt "is no longer load-bearing" because GitHub hosts the repos being
   described. Names are needed for the route ("push x, y, z"); the head commit lets the tool say
   "C is on the commit A pushed" instead of inferring. The user asked "why can't we record
   names?" — leaning yes, not formally confirmed.
4. **A fourth basket scope, auto-update:** which namespaces may fast-forward unattended.
5. **Triggers:** publish on sleep, shutdown and screen lock; the "before you leave" warning on lock.

#### Still to ask

- Which Debian desktop (KDE / GNOME / Xfce / Cinnamon) — GNOME shows tray icons only via an
  extension.
- Is the 2012 iMac (macOS Catalina 10.15 is its ceiling) a full peer, or acceptable headless if
  the chosen tray toolkit will not support Catalina?

#### New concepts from the discussion

- **The route (itinerary).** The display contract is repo rows × machine cells; the missing view
  is the same data per machine, **in an order you can follow**: "C: pull R, after A pushes" when A
  is ahead on R and C has R. Computed by the peer and shipped in the contract (skins never
  classify). Repos only a peer holds render `repo:abcd1234` until names arrive (v4) or `converge`
  resolves them. Last-known state survives staleness, so an offline machine reads "last seen 12
  days ago; then held unpushed work in 5 repositories".
- **Notification texts (draft),** each a route line, announced only on transitions (the tray
  already suppresses the first paint): caught up N, 2 need you here (names); machine-B pushed 4,
  3 are clean fast-forwards here; unfinished work on this machine (before you leave);
  machine-D not seen for 12 days, held unpushed work; diverged on A and C, needs a decision;
  fleet clear; publishing paused (host login expired).
- **Tray menu** shows the top route lines, Preview catch-up, Open dashboard. No separate tkinter
  popup: a popup window, if any, renders our own HTML so it is identical on every OS.

#### Verified in the code this session (read, not run)

- **The tray is Windows-only** (`app/fleet_tray.py`, ctypes; `supported()` is `win32`). Its icon
  is a 16×16 dot drawn in code (`_make_icon`, hardcoded 16 px — should draw at the real
  `SM_CXSMICON` size). It handles neither power events (`WM_POWERBROADCAST`), session end
  (`WM_QUERYENDSESSION`), lock, nor balloon clicks (`NIN_BALLOONUSERCLICK`). Notify texts today:
  "Fleet needs attention", "Fleet problem", "Fleet clear".
- **macOS has no tray, no file-event backend and no scheduler** (`_os/macos/` reports
  unsupported); start-at-login (LaunchAgent) exists. Nothing records gitSpecOps ever running on a
  Mac. **Linux has no tray**; file events and XDG/systemd autostart exist.
- **No by-machine view** in the dashboard JS.
- **`run_setup` asks no questions** (launchers, `.venv`, prerequisite report only).
- **Basic has no diff, commit, log, branch/switch or stash** — the gap between this and "Sourcetree
  becomes surgical". The architecture diagram never listed them either.
- **AI-friendliness:** strong for an AI *developing* gitSpecOps; weak for an AI helping a user
  *use* it — it would read these notes as its own instructions. Needed: a fork at the top of
  `AGENTS.md` ("helping someone use this? read the usage guide; leave `.agents/` alone"), a usage
  guide (commands, `--answers`, `--no-prompt`, `--json` where it exists), and a line that plans and
  confirmations belong to the human even when an AI holds `--yes`.

#### Tray toolkit: run a spike before choosing

What can look identical everywhere is **our icon** (we draw it) and **a popup that renders our
HTML**; the right-click menu is native per OS and should be. Candidates for a thin shell:

- **A — Python:** pystray + pywebview. Stays in one language; Linux leans on system
  GTK/AppIndicator packages (the usual breakage).
- **B — Tauri:** small Rust shell, OS webview, talks to the engine over the loopback HTTP API the
  tray already uses in connect mode. Adds a Rust build toolchain.
- (A Go helper like Tailscale's tray was considered; Go ≥ 1.23 does not run on macOS 10.15.)

Spike: the same tiny tray (icon cycling states, three menu items, a popup showing the route, one
notification) in A and B, on Windows 11, Debian 13 and the Catalina iMac; keep the one that broke
least. First icon experiment: a stdlib script rendering candidates to PNG at 16/20/24/32 px.
Design idea: the Git logo's branch graph (CC BY 3.0, attribution required) with **each node a
machine** — main node = this machine, branch nodes = peers, filled = online, ring = offline;
shape as well as colour, for colour-blind users. On macOS the menu-bar item can show text beside
a monochrome template icon ("↑3 ↓2 ●●○").

#### Transport facts that matter for testing

- **Dropbox** has a server, so an offline machine's last report waits there. Its free plan allows
  3 devices.
- **Syncthing** is free but peer-to-peer: a report moves only while two devices are online at once,
  so a rarely-online machine can publish and sleep unseen unless one node stays up.
- **GitHub state repo** has a server and needs nothing new installed. Every Contents API write is
  a commit, so the repo's history is a free log of every machine's state over time.
- **Sleep/shutdown hooks:** use the tray (runs as the user, has the host login). Windows gives about
  2 s on `PBT_APMSUSPEND`; `WM_QUERYENDSESSION` + `ShutdownBlockReasonCreate` can hold shutdown
  until a publish finishes; lock notifications have no deadline. Modern Standby laptops report
  sleep differently — test on real hardware. Avoid Task Scheduler event triggers (late) and Group
  Policy shutdown scripts (run as SYSTEM). Linux: systemd-logind delay inhibitors.
- **Self-update for a source checkout:** gitSpecOps is a Git repo, so it can sit in the
  auto-update basket and fast-forward like anything else; missing are a restart offer after
  self-update and regenerating launchers. The installed-app updater (signed manifest, rollback)
  is designed in `knowledge/distribution.md`, unbuilt.

#### Test machines available (generic descriptions)

Windows 11 (primary); one box dual-booting Windows and Debian 13 (two identities on one hardware,
never online together — a curious case if a shared data partition is visible to both); an old
Windows 10 laptop; a 2012 iMac (Catalina ceiling — the compatibility canary); an old Windows 10
desktop at a remote site (the real rarely-online "machine-D"); a second user's two MacBooks (their
own fleet).

#### Proposed path (the user agreed the earlier order; this re-sequencing is not yet confirmed)

Each step ends in something visible:

1. **Trust.** Read the tests (what each asserts, fakes, never touches) and run the suite on
   Windows 11, Debian and the iMac — the Mac's first run ever.
2. **Throwaway fleet.** Foreground `fleet run` peers, no start-at-login (so the migration need not
   come first), on a disposable fleet key, trying the GitHub repo, Dropbox and Syncthing. A Mac
   peer needs a file-event backend first (FSEvents via ctypes is plausible); until then `check`.
3. **Tray spike + icon experiments.** Choose the toolkit.
4. **Make it real.** Phase 3c, `App/` with the chosen tray, schema v4, the rewritten effect rule,
   the diagram updated.
5. **Seeing.** Real enrollment with start-at-login; the route; notifications; sleep/wake/lock
   triggers; the auto-update basket. Delivers "at a glance, what's out of sync on any machine".
6. **Doing.** diff, commit with review, branch/switch, stash in `Basic/`, exposed in the app.
   Delivers "Sourcetree becomes surgical". Remote device jobs (ask an online peer to push) after.
7. **The second user's fleet.** The one front door plus portable builds for their Macs.

Also still owed by the user, unchanged: the scheduled-task replacement and three archive
launchers (below), the history-rewrite decision before public promotion, and cutting v0.2.0.

### 2026-10-19 — side quest: a self-doxxing scan across the user's own fleet

Idea from the user: with everything gitSpecOps already knows about a user's fleet, a script could
**take what is known about the user and work backwards**, scanning their repositories for
personal information they leaked themselves. Not built; recorded for design.

- **Seeds it can gather without asking:** `git config` name and email, the host CLI's login,
  machine labels and hostnames, home-directory paths, tailnet addresses the fleet has seen, and
  the namespaces/orgs in the inventory. Plus anything the user adds (real name, phone, street,
  other emails).
- **Known credentials** (tokens, keys) may be supplied **at run time only**: held in memory or
  compared by hash, **never written to disk or to the report** — the report names the location
  and a redacted fingerprint. This keeps the prior-auth rule: gitSpecOps never stores a credential.
- **Scope:** working trees, **full history** (every blob, as the 2026-09-11 audit of this repo
  did — see `knowledge/repo-privacy-and-history.md`), and **commit metadata** (author/committer
  emails are themselves a self-dox), across every repository the fleet knows, on this machine or
  as a plan for others.
- **Report-only, `EFFECT = "none"`.** Any fix (rewrite, rotate) is a separate decision with its
  own warnings; a history rewrite breaks every clone. The report itself names private
  repositories and personal data, so it goes to the gitignored `.agents/output/` like the
  inventory, and never into the fleet manifest.
- **Reuse:** `tests/repo/test_repo_hygiene.py` patterns and the seven secret shapes from the
  history audit. Layer: a Special operation (one repo scan repeated with judgment), with an
  Elaborate wrapper if it plans across machines.

### 2026-10-05 — library inventory shipped (uncommitted); follow-ups

Built `Special/inventory_export.py` / `inventory_restore.py` (see work log). Not yet done:

- [x] Committed 2026-10-05 (`a7c339e`). The one suite failure then, `basic/test_run.py`, predated
  it: a Python child writing `✓` to a pipe on Windows emits cp1252 unless UTF-8 mode is set.
  Fixed 2026-10-05 at the cause: `Basic/_run.run` now sets `PYTHONUTF8=1` and
  `PYTHONIOENCODING=utf-8` for every child (a caller's own value wins), pinned in
  `tests/basic/test_run.py`. Full suite alone on Windows with neither variable set: 44/44.
- [ ] **Not yet run on a second machine / Linux**: the real round trip (export here, restore there)
  is unproven. Path handling is POSIX-relative by design but only Windows has run it.
- [ ] **Phase 3c: rebuild `materialize` on `_inventory.plan_restore`**, one clone planner not two.
- [ ] **A diff mode** (`inventory_check`: inventory vs disk — missing, extra, origin mismatch) is the
  natural "converge, with names" and is not built.
- [ ] **Restore ignores the recorded branch** (it records it; clone checks out the remote default).
  Decide whether to offer checking it out. Submodules are skipped, not cloned recursively.
- [ ] **The real GUI dialogs are unverified.** Tests drive the terminal/scripted path only; open
  the three dialogs once by hand on Windows (and on a Linux desktop, where tkinter may be absent
  and should fall back to the terminal prompt).
- [ ] No per-repository pick yet (restore takes everything, or `--only LABEL`). `parse_selection`
  in `Basic/_confirm.py` is the grammar to reuse if wanted.
- [ ] Mention the commands in the README Repo Shape / launcher list when 3c settles the layout.

### 2026-09-22 — migration: phases 1, 2, 3a–3b done; 3c next

The target tree (revised 2026-09-21), the phases and the decisions are in
[`knowledge/architecture-layers.md`](knowledge/architecture-layers.md) and
[`HANDOFF.md`](HANDOFF.md). Carried forward:

- [ ] **Direct `subprocess` calls outside `_run`** remain (re-measured 2026-09-22):
  `fleet_autostart` (3), `capture`, `retirement`, `snapshot_restore`, `fleet_net`,
  `release_check`, `setup_gitspecops` (1 each). `schtasks` now lives in `_os/windows/schedule.py`. Each moves onto
  `_run` or into `_os/` as its owner moves in phases 2–4; none should survive phase 4.
- [ ] **`gh` calls are all in the provider now, but two callers still speak raw `gh`**:
  `repo_transport` (Contents API) and `fleet_app` (auth status, login) call `run_gh` with their
  own arguments. Move the Contents API into `github.py` when the transport moves (phase 3);
  `fleet_app` dissolves in phase 3 anyway.
- [ ] **Scheduled task — waiting on the user.** New launcher written 2026-09-22 into the
  per-user state folder; the user replaces the task and reinstalls three archive launchers; then
  delete `gitArchiveUpdater/`.
- [ ] **Two registered archives predate the `mode` field and use custom prefixes.** Reinstalling
  must pass each entry's own `approved_remote_prefixes`; a missing mode means `update`.

Two framings from the design discussion were wrong and are recorded as
such so they are not revived: **"plugins"** (the provider seam already existed; no plugin folders,
loaders or hyphen tricks) and **"legacy vs fleet" Sync Suggester runtimes** (not two products:
`check` runs the observation job once, `peer` runs it continuously, over one config and one code
path).

### 2026-09-20 — the goal outranks the rules; do not re-derive "read-only"

The brief now opens with **What this is for**. If anything further down contradicts it, the goal
wins and the rule is the defect. This is not hypothetical — a scaffold-era "never writes" claim
outranked the product goal for 17 days and had to be removed; see the work log.

**These tools perform Git operations.** The boundary is *observation never mutates; mutation is
always a command the user invoked*. Do not restate that as "Sync Suggester is read-only", and do
not bolt exceptions onto a rule that is wrong — fix the rule.

- [x] **"Sync Suggester" is not a vestigial name — resolved 2026-09-20.** An earlier note here
  claimed it was left over from the read-only era and should be reconsidered before release. The
  user settled it: *the best thing it does is suggest sync.* Suggesting is the headline value, not
  the old limitation — the tool now suggests **and** can act, and the suggestion is still the part
  that earns its place in the tray. Do not reopen this as a rename.

### 2026-09-19 — Product direction confirmed; implementation is ready to resume

The user confirmed one repository, one family, with two shapes: careful terminal
operations and an optional fleet service that coordinates them. The archive updater,
org duplicator, and Sync Suggester remain peers in that family; do not turn the
service into an authority or degrade the clone-and-run command path.

**Headline outcome:** from any enrolled machine, the user can see the state of all
their repositories everywhere and receive a safe, specific suggestion for unsynced
work. The dashboard and tray are skins over terminal-first operations, not separate
policy engines.

**Implemented 2026-09-19:** the medium-tier recovery slice is now end to end: an explicit
private location, local per-repository policy, capture-basket selection, event-quiet capture,
peer checksum acknowledgement, preview/disposable restore, and exact freshly-fetched remote
retirement proof. `safe-to-wipe` now accepts only exact current snapshots verified by another
peer, and never unpushed commits. Setup preflight has honest tier offers; setup can explicitly
request an authenticated Tailscale session hand-off from a running peer. The dashboard has the
same fresh-fetch catch-up preview as the terminal (applying stays terminal-confirmed).

**Also implemented 2026-09-19:** `fleet audit` reports remote/upstream/unfinished-work issues
without mutation, and `fleet materialize` provides a reviewed clone-only plan for the locally
observed working set. The materializer rejects unsafe remote-derived filesystem paths and
symlink escapes. `fleet live-buffers` supplies explicit, local-only VS Code backup evidence;
publishing unsaved content remains deliberately unbuilt. `catchup` fresh-fetches
and previews every observed checkout;
`--apply --yes` fast-forwards only clean behind-only checkouts and lists every other
state for a human. Remote actions retain the existing safety ladder: fetch, safe pull,
ahead-only non-force push, reviewed commit; never guess through divergence or conflict.

Preparation and implementation completed 2026-09-19: mapped the tree, added catch-up, recovery
activation, authenticated session join, dashboard preview, and replacement evidence. Targeted
Windows validation passed, including new recovery runtime and retirement tests. No live
deployment, commit, or push was performed.

**Packaging readiness update:** the desktop PyInstaller recipe had incorrect relative source
paths and omitted dynamic modules; both are repaired and a read-only release gate checks them.
The release remains deliberately uncut: the current working tree is uncommitted, no matching tag
exists, and PyInstaller is not installed in a disposable build environment.

### Current continuation — 2026-09-11

Stale active host/client guidance has been reconciled. Guided durable setup, pending transport
delivery, the desktop Git client shortcut and **baskets** are implemented; details are in the
work log.

- **Medium-tier recovery: encryption question is CLOSED (2026-09-12) — snapshots are not
  encrypted.** Reasoning and the verified per-tier authority table are in
  [RECOVERY-DESIGN.md](../git-sync-suggester/docs/RECOVERY-DESIGN.md) under "Trust boundary".
  No `age`, no new dependency, stdlib-only runtime rule intact. Do not reopen this without a
  concrete threat the three tiers do not already cover.
- **Capture is enabled only through an explicit medium-tier enrollment.** `core/capture.py` and
  `core/secret_scan.py` remain protected by default. The capture basket may select namespaces
  only after a separate confirmed location passes overlap checks; running peers capture after
  filesystem quiet periods, and a second peer must verify the checksum before the source calls
  it recoverable elsewhere.
- **Done 2026-09-12:** snapshot store, preview, restore (`core/snapshot_restore.py`), and the
  per-repository capture policy (`CapturePolicy`: obey `.gitignore`, secret protection,
  `allow_paths`), all tested against real repositories. See the work log.
- **Recovery proof is exact.** `core/retirement.py` recreates a bundle's resulting tree in a
  temporary index, freshly fetches origin, and permits retirement only if the upstream tree is
  identical. Clean state or counts never suffice. The follow-up is cross-machine snapshot
  discovery/restore UX, not a weaker proof.
- **Run test suites alone before claiming a result.** On 2026-09-12 `fleet/test_git_client.py`
  failed only while five test processes ran concurrently; alone it passed. The full suite alone
  passed **26/26 on Windows** on 2026-09-19.
- **Manual probes are versioned under `tests/probes/`.** Code, synthetic fixtures and
  instructions belong there; profiles, raw logs and results remain temporary/local. The
  automated runner explicitly excludes this directory. The VS Code hot-exit probe **has now
  run against a real unsaved edit** and found a backup differing from the saved file: dirty
  buffers are persisted before exit (VS Code 1.137.0, this machine). Existence only — the
  probe says nothing about how quickly a backup appears.
- **Desktop Git client shortcut is implemented and verified** (`app/git_client.py`,
  `tests/fleet/test_git_client.py`, `tests/probes/desktop_client_ui.py`). Selection is
  per-machine; the action only opens a locally observed checkout in Sourcetree or GitHub
  Desktop. It performs no Git operations and is not a step on the tier ladder.
- **Validation environment:** use the existing virtual environment (Python 3.14.2 on this
  Windows checkout). Bare `python` is below the declared >=3.11 minimum.

- [x] **The tier ladder's local slices are built (updated 2026-09-19).** See
  [knowledge/tiers-and-capture.md](knowledge/tiers-and-capture.md). Today all three tiers carry
  the *same* v3 status manifest, so they differ only in latency. They are supposed to differ in
  what they can rescue: durable = committed + status; medium = **saved but uncommitted content**;
  live = **unsaved editor buffers**. Ordered next steps:
  1. **Guided durable setup — implemented 2026-09-11.** Suggested private repo name,
     app ownership/publication explanation, and named CREATE/USE confirmations.
  2. **Content capture on the medium tier** (the user's *stealth-stash*): a separate,
     size-capped bundle per repository that expires only after retirement proof. It is not
     encrypted by design; policy, retirement proof and peer wiring are active after explicit
     recovery-location and capture-basket enrollment. See `docs/RECOVERY-DESIGN.md`.
  3. **Unsaved buffers on the live tier — local reader built.** VS Code does write
     dirty buffers to its backup store before exit (measured 2026-09-11 via
     `tests/probes/vscode_hot_exit/probe.py --run`). So no editor plugin is needed for VS Code:
     read what the editor already wrote. `fleet live-buffers` maps existing backup records to
     configured roots and returns metadata only. Still undecided: backup latency, other editors,
     and whether unsaved content may leave the machine at all.
  4. **Baskets — implemented 2026-09-11**, ahead of capture at the user's direction. Three
     independent scopes; capture is refused rather than offered. See the work log and
     `docs/FLEET.md`. Config is schema v4.

- [x] ~~**Selecting which repositories a machine syncs is all-or-nothing.**~~ **Done
  2026-09-11.** `fleet baskets` selects by namespace per scope. Still open on top of it: a
  basket cannot yet name an individual repository (namespace granularity only), and there is no
  UI to change baskets — App & setup displays them read-only and points at the CLI.

- [ ] **History holds personal data but no secrets — verified (2026-09-11).** Every blob in
  history was scanned (566 objects, 355 blobs, seven secret shapes): **no secrets**. Personal
  data is there: 3 Tailscale addresses, 4 machine names, 5 private namespaces, 1 Windows path.
  A rewrite is the only complete fix and breaks every clone and fork; not done deliberately,
  since there is nothing to rotate. **Decision still owed by the user.** Method and the
  if-a-secret-is-found procedure:
  [knowledge/repo-privacy-and-history.md](knowledge/repo-privacy-and-history.md).

- [ ] **First release is not cut.** `pyproject.toml` says 0.2.0 and the update check works,
  but there are **no tags and no GitHub release**, so `version --check` correctly reports
  "unknown" for everyone. Tag `v0.2.0`, publish a release, then confirm the check flips to
  "current". Until that exists, the update path is untested against reality. The new read-only
  `git-sync-suggester/packaging/release_check.py` makes the local prerequisites explicit; it
  currently correctly reports the dirty implementation worktree, absent tag, and absent
  disposable PyInstaller environment.

- [ ] **Distribution beyond a hand-built bundle.** Decided direction: one installable app per OS
  acting as a *launcher* for the operations, with the heavy fleet tier opt-in behind first run;
  the clone-and-run-scripts path must never degrade, since it is also the development path.
  Self-replacing update is deliberately NOT built — report-and-tell first, and an opt-in
  "download and replace" only after the version contract has proven itself in the field.

- [ ] **Enroll the remaining machines as peers.** Use `fleet setup` with the existing fleet
  key and chosen transports. No central host is needed. Reuse the fleet key rather than minting
  a separate fleet. Historical machine inventories and reachability are in the work log; check
  actual deployment state before acting. Keep any installed bundle in a durable location before
  enabling per-user start-at-login. Do not infer enrollment from a successful build.
- [ ] **Live deployment validation.** Verify saved-work status across two actual peers, including
  one being offline. The Windows/Linux event mechanisms and independent dashboard ship; actual
  fleet membership and configured transports still need operational verification.
- [ ] **Product onboarding and fleet actions.** Keep the source-checkout path working while
  developing a self-contained installed app. Baskets, unencrypted recovery wiring and narrow
  remote Git jobs remain future work in the agreed tier order. Integration choices are independent;
  nothing requires a particular sync client. Do not expose cosmetic enable switches.

- [ ] **Outside fleet review (2026-09-04) — status.** Recorded by the user; two items were acted
  on the same day, the rest are still open.
  - ~~**Windows discovery returned an empty fleet.**~~ **Fixed 2026-09-04.** The diagnosis in the
    review was exactly right: `os.DirEntry.stat()` on Windows serves data cached from the directory
    scan and that record carries `st_dev == 0`, while the root statted directly reports a real
    device number, so every direct child was rejected as cross-filesystem. `repo_discovery.py` now
    excludes only on **positive evidence** of a different device — unknown never means skip — via
    `device_id()` / `entry_device_id()`, which pay for a real stat only when the cached value is
    absent. `tests/test_repo_discovery_devices.py` reproduces the Windows symptom on any platform
    by faking the cached-zero device; verified it fails ("found 0 of 3") against the old code.
    **Confirmed on the real Windows T: drive:** direct-child scans found all 5 <namespace-a>
    agent repos, all 8 <namespace-b> repos, and all 3 <namespace-c> repos.
  - ~~**Compound facts hidden by precedence.**~~ **Fixed 2026-09-04.** `classify_repository` is now
    documented as a headline for severity *ordering only*; anything that renders or advises uses
    `repository_flags` / `describe_repository` / `secondary_facts`, so a repository that is dirty
    AND ahead now reads `STOP: uncommitted work on cbox (also ahead 9)`. Tests pin dirty+ahead,
    behind+stash, diverged+dirty, missing-upstream+dirty, and that a clean repository invents no
    extras.
  - **Integrations stay optional.** gitSpecOps, the org admin/agent repositories, Digital
    Cartography and <namespace-c> are independent systems that interoperate through small contracts;
    none may become a required runtime dependency of Sync Suggester. Sync Suggester owns its local
    stable machine id (it already does — `config.py`, derived from the hostname and overridable)
    and may *optionally* accept a human label or metadata exported by another tool. Nothing to
    build until a concrete contract is proposed; the constraint is what matters.
  - **Intentionally-dirty trees (patch ledgers).** Org/agent policy may locally annotate such a
    tree as "recorded" or "drifted", but **raw dirtiness must still be published and must never
    become an all-clear**. Not built. The natural home is a local-only annotation in the catalog
    (beside `alias`), displayed alongside the state and explicitly excluded from classification —
    the manifest must keep carrying the raw counts.
  - **Run background operation as the interactive user.** This is implemented for the fleet
    tray and per-user autostart; preserve it for future scheduled legacy commands too.
  - **Note on sequencing:** the review's "watchdog path remains" list was written against
    `9989dc0`, before the 2026-09-03 work. Persistent per-root config and machine identity,
    peer-manifest aggregation with stale/expired rules, optional bounded fetch with honest
    `upstream_observed_at`, and visible polling/watch with semantic-change writes plus heartbeat
    are all **already built** (see [`WORK-LOG.md`](WORK-LOG.md)). What genuinely remains from that
    list is **notifications**, then **explicit handoff**.

- [ ] **`.venv` stays package-free — watch for regressions.** `[tool.uv] package = false` makes
  `uv sync` a virtual project (`uv.lock` shows `source = { virtual = "." }`, no `.pth`). If a stray
  `pip install -e .` or a pyproject edit ever re-adds an `__editable__*.pth` / `git_spec_ops*.egg-info`,
  remove it. See [`knowledge/venv-and-editors.md`](knowledge/venv-and-editors.md).
- [ ] **Duplicator modes 1-3 (download-one / upload / migrate): no CLI flags.** Only
  `--batch`/`--single` have them; `--answers FILE` is the stopgap. Low priority — mode 4 is the hot
  path — and the same `parse_args()` pattern applies if it is ever wanted. (The `CommandTimeout`
  retry half of this item was fixed 2026-09-03.)
- [ ] **Sync Suggester roadmap toward the three-machine fleet.** The product goal is recorded in
  [`new-tool-sync-suggester.md`](new-tool-sync-suggester.md#product-goal-stated-by-the-user-2026-09-03):
  three machines point at their GitHub folder, converge on the same orgs/repos, and stay in sync
  with each other and the cloud, making GitKraken's grouping obsolete for many-org sync
  management. Ordered so schema-affecting work lands before any fleet exists:
  1. ~~Manifest schema v2~~ — **done 2026-09-03** (salted `repo_id`, `head` dropped, `fleet_id`
     mismatch detection). Any further schema change still belongs before a real fleet exists.
  2. ~~Fleet convergence~~ — **done 2026-09-03** (`converge`; names peer hashes by enumerating
     candidates through the provider seam and matching the deterministic HMAC). Still open on top
     of it: convergence currently compares against *peers*, not against the org itself — "the org
     has repos nobody in the fleet has" needs `list_repos` over configured namespaces compared to
     the fleet union, which is a small addition to the same module. Also worth adding: the reverse
     direction (repositories this machine has that no peer does — possibly unpushed local-only
     work).
  3. ~~Source-remote fetching~~ — **done 2026-09-03** as opt-in `--fetch` on `check`/`watch`
     (bounded pool, per-repo stamping, separate remote-freshness accounting). The *scheduled*
     variant is still open: whether a periodic `watch --fetch` is wanted, and at what interval,
     is a policy call now rather than a design one.
  4. **Earlier hook proposal is superseded for the peer app.** Native filesystem event
     observation ships and includes saved edits that Git hooks cannot see. Do not install a
     global hooks dispatcher as part of the current roadmap. Legacy command automation remains
     separate. Joining with a shared fleet key works; automatic key exchange remains follow-up.
  5. `handoff` — **design pass written 2026-09-03** ([`handoff-design.md`](handoff-design.md));
     still unbuilt, on purpose. Its recommendation is to not build it yet: most of "I left work on
     the other machine" is unpushed commits, which `--publish` now covers. Three open questions
     there need the user's answer before any code.
  6. Long-lived stashes: information, or do they block an "all clear"? Currently `stashed` ranks
     above `unknown` but below `ahead`, so it surfaces without shouting.
  7. The **advice → apply** step (clean + behind-only + fresh fetch -> `git pull --ff-only`) stays
     purely advisory until fetching is settled.

- [ ] **Actionable Fleet dashboard, in safety order.** The user wants dashboard-wide and per-repo
  fetch, fast-forward pull, commit and push, plus conflict help and remote execution on an online
  source machine. Build a narrow device job protocol rather than a generic remote shell. Start with
  fetch; allow pull only after a fresh fetch and only for a clean behind-only checkout using
  `--ff-only`; allow push only for a clean ahead-only checkout after revalidation and never force;
  require diff/file review and an entered message for commits. Diverged or conflicted work needs an
  explicit merge/rebase workflow or launch into an installed Git client, not a one-click guess.
- [x] **Recovery snapshots (user names: stealth-stash / stealth-sync) — local chain complete
  2026-09-19.** An opt-in, unencrypted snapshot of staged, unstaged and selected untracked work
  that survives the source machine going offline, can be previewed/applied elsewhere, and expires
  only after retirement proof. Capture, storage, preview, restore, the
  retention/size/ignore/secret-scan/deletion controls, peer checksum acknowledgement and exact
  retirement proof are all built and tested. Availability is still gated on explicit
  recovery-location and capture-basket enrollment, so an unenrolled dashboard correctly shows it
  unavailable — do not present a cosmetic toggle. **Remaining: cross-machine verification on real
  peers**, and the separate open decision on whether unsaved buffer *content* may ever leave a
  machine.

- [ ] **Legacy transports: `state_dir` and `state_repo` both ship; folder auto-detection is not built.**
  The user chose "both, gh-backed first" — the gh Contents API transport landed 2026-09-03. Still
  to do: probe the known OneDrive/Dropbox/Drive/Syncthing/iCloud locations per OS at `init` so a
  machine with a sync client needs no path typed. Detect availability at setup time;
  historical machine observations are not current evidence. `rclone` remains a possible
  advanced escape hatch — 70+ backends, auth configured once — but its own setup is real tedium.

- [ ] **Scale work for mega/enterprise users.** Measured 2026-09-03: a v3 record is ~321 B/repo,
  so ~3,200 repositories fit the Contents API's 1 MB inline read. Open items, in order of value:
  1. ~~Compress the manifest~~ — **done 2026-09-03** as the opt-in `compress_manifests` setting,
     off by default (8:1 measured on real data).
  2. **Selective `--fetch`.** 20 repositories take ~4s at 4 workers, so 10,000 would take ~30
     minutes. Needs to fetch only what is stale or recently touched, not everything.
  3. **Discovery** over very large trees.
  4. Beyond ~20k repositories, shard a manifest per namespace.
  The dashboard already scales — the exceptions view shows only what needs action.

- [ ] **Zero-friction join for the repo transport.** Because a private repo's access control is
  already the boundary (see [`knowledge/manifest-privacy.md`](knowledge/manifest-privacy.md)), the
  fleet key can live inside the state repo, making a second machine's setup just
  `init --state-repo owner/name` with no secret to carry. Explicitly does NOT apply to the folder
  transport. This is the piece that delivers "everything just works as long as gh is authed".

## Someday / deferred

- `--yes` shipped for the duplicator (2026-08-31, batch + single); no `--dry-run` yet.
  `_legacy_sources/` still left untouched.
- Push/"publish" direction: **first slice shipped 2026-09-03** (`archive_sync.py --publish`,
  ahead-only non-force). Not built: per-agent branches + `open_pr()` on the provider seam,
  auto-commit behind a flag, protected-branch awareness, secret/size pre-flight checks. Ship those
  only if the ahead-only slice proves insufficient.
- Multi-host support is a stated goal: archive tools first via `Basic/_providers/` (one
  `<host>.py` that calls `register_provider(...)`, plus its import line in `_registry.py`; fix `remote_identity` URL-port
  parsing first). `github-org-duplicator` stays GitHub-specific by design. Auth stays
  user-owned (host CLI logins); no credential management anywhere.
