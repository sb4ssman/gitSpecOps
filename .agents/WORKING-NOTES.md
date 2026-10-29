# Working notes

Living todo / scratch pad. Add items freely; **prune regularly**. When something is done, move it
into [`WORK-LOG.md`](WORK-LOG.md) (appended at the bottom, `YYYY-MM-DD HH:MM`) and delete it here.
Dates are always absolute.

_Last tended: 2026-10-29 (work-in-progress checkpoint; open-work consolidation)_

## Open

### Remaining repair acceptance after the public cleanup workflow — 2026-10-29

- Direct/CLI and callable cleanup now share plan/apply, finding-id choices, exact private plans,
  proof/rescan and common output/log/artifact delivery; completed evidence is in the log/design.
  Remaining: GUI controls/visual acceptance, standalone general-rewrite presentation if needed,
  follow/relink/publication workflow and reviewed actual-repository inventory/scope. Keep raw
  plans/native diagnostics private; never infer purge scope from missing files or classifications.
- Current native reading accepts attached HEAD, local branches and commit-target tags with
  portable UTF-8 text/paths and regular/executable/symlink objects. Tracking refs require explicit
  inclusion and preserve their names, remote-only history and symbolic aliases without fetching.
  Other private ref namespaces, detached/unborn HEAD, signed/unknown-header objects, submodules,
  shallow/promisor/alternate/grafted stores and unhandled encodings are refused. Inventory those
  cases before actual cleanup; do not silently discard refs or strip signatures. Ref renaming/
  removal and scoped example-review transfer into mirrors remain explicit separate decisions.
- Exact plans/object reads have finite object/byte/path limits and a private cache. Performance,
  larger histories, native Linux/macOS, nested-tag execution and additional signature formats
  need their own acceptance. Windows symlink proof used real Git symlink objects with
  core.symlinks=false, not privileged filesystem-link creation or a native other-OS trial.
- Actual repository cleanup, following rewritten history, contributor/identity choices and
  forced publication remain separately reviewed boundaries. The frozen v1 archive stays
  unchanged. Previously deferred checks and the wider product/native acceptance stay open.

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
- **Remaining security review/presentation:** active scans support full private external reports
  and explicit exact-content example review/revocation. Findings stay visible and propagate
  through the common scanner and commit/push/advice policy revisions; binding digests/reasons
  stay private. The log and product/settings/security contracts hold the implemented evidence.
  Remaining: GUI human revelation/review, explicit operational-record transfer/relocation,
  native permission/link proof, private message/hook-only action-report delivery and remaining
  log/notification routing. scan-tree --staged now covers staged file bytes after line-ending/
  filter conversion without staging or changing working files. No raw value is required
  for agent triage. Optional-engine findings and coverage gaps cannot be waived by this review.
  Reproduce one intermediate parallel advisory regression that reported working-tree checking
  incomplete instead of blocked; isolated and complete reruns passed, with no root cause proved.
  Masked assertion diagnostics now retain the full result on recurrence. Do not weaken refusal
  states or claim that rerunning alone proves native/concurrency reliability.
- **Common front door:** `python gitso.py` now provides a static 16-command catalog, source-derived
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
  remaining cleanup GUI/finishing integration and native/multimachine acceptance stay in the comparison/backlog. Do
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
| A2 | One coherent app at the top; each individual operation remains useful on its own. No shelf, shape, fleet or shared helper dependency for casual archive updating. | **Partial.** Direct scripts and plain Python/Git operation paths exist. Sixteen public `--help` commands work outside the checkout without creating a profile. Common settings/results/logging and app integration are not universal. |
| A3 | Preserve Basic -> Special -> Elaborate -> App, with plumbing in private helper folders and operations visible at layer roots. | **Partial.** `_settings`, `_archive`, `_org_duplicator`, `_runtime` and security `_commit` group helpers. Archive aliases/CLI forwarding are removed; other families still need cleanup. Fleet/app largely remain in their earlier tree. The current 110-file layer check passes; this is not complete physical reorganization. |
| A4 | Move `duplicate_org.py`, `update_archive.py` and local `archive_manager.py` into Special; scheduling and fleet coordination remain Elaborate. | **Implemented for the selected source split.** All three public scripts are in Special. `Elaborate/archive_manage.py` retains scheduling/compatibility. Functionality and defaults beyond that source move remain separately reviewable. |
| A5 | An action-named updater invokes reusable updater plumbing; avoid underscore/helper clutter among public commands. | **Partial.** `Special/update_archive.py` is the public adapter; `_archive/update_operation.py` owns its callable operation, with supporting helpers grouped privately. Other families still need consistent public/private mapping. Exact helper basenames are implementation choices, not user-mandated renames. |
| A6 | One CLI/main menu exposes operations to terminal users and LLMs; direct scripts still work. | **Partial.** User selected `gitso`. Source launcher/catalog/menu and source-derived docs now dispatch sixteen operations; direct scripts remain. Installed wrappers, richer shared metadata/results and full GUI integration remain unfinished. |
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
| D2 | File output destinations and no-fallback behavior must be intentional, predictable and testable. | **Implemented selected private report routing; broader acceptance partial.** Reports can use explicit external storage; inside Git they require untracked positive ignore. Exclusive writes, link/traversal/bare/overwrite refusal and partial cleanup have disposable proof. Native POSIX/Windows ACL and symlink acceptance still needs other hosts; remaining consumers need adoption. |
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
| E3 | User blocklist plus allowed generic values; conflicts explicit; protect private publication values as well as credentials. | **Implemented active policy; broader adoption partial.** Master/local prohibited values, safe values and explicit conflict refusal feed the common scanner and checked commit/push/advice. Scoped example reviews do not weaken prohibited values or add global allowances. Remaining: hygiene/recovery adoption, profile UX/transport portability and native acceptance. |
| E4 | Enrollment exclusions define what the tool must never inspect/manage, separately from strings prohibited in publication. | **Partial.** Discovery controls and scoped fleet selections exist, but namespace baskets are not a universal hard no-inspection boundary. Cross-consumer exclusion enforcement and discovery/enrollment UX remain unfinished. |
| E5 | A human can deliberately read what is at risk; agents normally receive useful masked context, not the underlying secrets. | **Partial.** Active scanner masks stdout by default and can explicitly write full reports. There is no equivalent intentional stdout/app reveal flow yet. Do not solve this by always exposing values or by preventing human inspection. |
| E6 | Reuse scanner/policy behavior across standalone checking, sync advice, action gates, recovery and repository hygiene. | **Partial.** Standalone scans, checked commits, direct/archive publication and local advice share material/check/policy/engine code, severity and check_status. Recovery, archived rules and hygiene remain separate; reconcile behavior before replacing them. These callers are not universal cross-consumer equivalence. |
| E7 | Distinguish introducing a prohibited value from removing it; reviewed exceptions and incomplete scans are explicit. | **Partial.** Archive gate checks outgoing versions, allowing simple baseline removal while blocking introduce-then-remove. Checked commits inspect new selected bytes/paths/message/identity, allowing removal of an old prohibited path. Gaps/selected failures hold actions; uncertain candidates require policy review and rerun. State/policy rechecks include settings loss during checking. General exceptions, remaining action consumers, shared policy ownership and installed outside-client hooks remain open. |
| E8 | Assess established security tools before extending custom detection; privacy policy and orchestration still belong here. | **Choice settled, partial implementation.** User requires optional Gitleaks/Betterleaks/TruffleHog or none. Three versioned stdin adapters now run over already selected material with masked results and explicit gaps. No actual engine is installed/selected here; native/version acceptance remains open. Detection is distinct from dependency security and historical-clutter removal. |
| E9 | Security coverage must state its gaps, including symlinks and binary/container material. | **Partial.** Archive/nested compression, OOXML/EPUB and selected image metadata are handled with bounds. PDF, 7z/RAR, LFS content, submodules, unsupported/oversize/binary material and external-engine coverage remain gaps. The native symlink case is skipped on this Windows run; its precise OS cause is not captured. This is a scan coverage issue, not a requirement to symlink settings or copy tool installations. |
| E10 | Reviewed test fixtures and public contest constants are explained exceptions, not an unexplained all-clear. | **Implemented local scoped review; broader acceptance partial.** Explicit whole-plan approval can accept a supported uncertain example for exact repo/check/location/line/occurrence/context/bytes without global safe-values. Private reasons and revocations remain auditable; changed content requires review and changed state invalidates action plans. No actual user reviews were saved here. Optional-engine review/native/GUI/transport remain open. |
| E11 | Reuse existing history-repair/finishing behavior; prove scan -> rewrite -> scan on disposable repositories before real approved purges. | **Direct/CLI repair and disposable proof implemented; broader workflow partial.** clean-history composes private finding-id/path/identity choices, exact plan approval, independent mirror rewrite/proof and active rescan, honoring common output/logging and refusing fallback. Explicit tracking refs preserve names, remote-only history and symbolic aliases. Windows trials prove removal, retained graph/content and untouched source, including policy loss and incomplete selected checks. GUI, follow/relink/publication, unsupported/larger/native other-OS acceptance and fresh real-history clearance remain open. Frozen v1 finish remains uncalled. |
| E12 | Purge only explicitly approved obsolete material; avoid erasing project history or deleting current packaging by inference. | **Paused pending scoped execution/proof.** The affected repository owns concrete purge manifests/former aliases; private mission notes preserve the conversation's scope. A new repository was considered, not selected. Tree absence and dated cleanup reports are not fresh history proof, nor proof external copies vanished. |
| E13 | Full reports/private findings cannot leak via tracked notes, generated diagnostics, shared state or app notifications. | **Partial safeguards.** Raw tray tee/generated-key output were repaired; full reports and content-bound review records now use explicit private storage, exclusive writes and masked artifacts. Evidence digests/reasons never enter normal records/logs/fleet state. GUI revelation, explicit transfer and remaining raw-channel/native acceptance remain open. |

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

- A source user can run individual Special scripts. The archive runner and cleanup workflow
  use common settings, headless results, explicit output and compact logging. Other families
  still need adoption; the current catalog has sixteen direct/CLI routes.
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

### Remaining architecture and delivery work

The acceptance comparison above controls priority; these are supporting tasks, not permission
to activate settings, launchers or a live fleet. The five-stage plan remains: organize helpers,
establish public operations, connect common infrastructure, expose the common front door, then
finish security/fleet/native integration. Completed evidence lives in WORK-LOG, not here.

- Complete the remaining fleet/app layer split and source/caller map before more moves. Preserve
  Basic -> Special -> Elaborate -> App, independent direct scripts and existing user-owned data.
  Review remaining public names; `sync_self.py` is a suggestion, not an approved rename.
- Finish catalog/parser/effect/result metadata and generated-documentation parity. Help and
  discovery must not execute an operation, read secrets or create profiles. Distinguish helping
  a user operate the tool from developing it so agents need not absorb all developer history.
- Finish independent archive add/list/remove, membership/discovery depth and nested-repository
  policy. Registration must not require scheduling. Preserve each archive's update/sync choice
  and allowed-origin prefixes; recognition is broader than update eligibility.
- Keep actual existing-settings conversion and launcher/job rollout paused. Before any reopened
  rollout, verify writers and ownership, preserve originals/receipts, review replacements and
  prove settings-loss/interruption behavior. No live registration/startup/task repair is implied.
- Finish guided setup/update/uninstall/selective unenrollment, profile relocation/locator and
  the app's common settings UI. Source updating targets this checkout only, with reviewed
  fast-forward behavior and restart/launcher handling; installed-app updates need their own proof.
- Reconcile remaining output/state consumers: duplicator resume/logs, inventory exports,
  remaining manager/scheduling paths and private hook/message action reports. Required operational
  state is distinct from an optional report. Preserve explicit destinations and refuse fallback.
- Finish security GUI controls, continuous advisory scheduling/invalidation, shared policy
  transport/ownership/conflict handling and recovery/hygiene reconciliation. The frozen archive
  is a reference, never an editable alternate engine or permission to run its finishing command.
- Complete the attended remote-action protocol: exact acting-machine plan, human approval at
  the requesting machine, then state/policy revalidation. No generic remote shell or automatic
  commit/merge/rebase/reset/forced action. Standalone Basic operations remain policy-free.
- Prove the selected private Git, synced-folder and tailnet conduits on real peers, including
  offline/stale/fresh transitions. Finish readable derived fleet notes, aggregate request budgets,
  batching/backoff/retention, selective fetch and large-tree/sharded-manifest acceptance.
- Finish the chosen Qt/PySide6 app shell and native tray/menu-bar acceptance on Windows, KDE
  Linux and supported macOS, including icon density, accessible states, notifications and
  wake/sleep/lock/shutdown behavior. GUI controls must invoke the same headless operations.
  Do not enroll machines or install dependencies/startup merely to inspect the implementation.

### Carried-forward acceptance and unresolved details

These open items survived consolidation of the older dated handoffs. Verify current code
before implementing an older proposal; current product/security contracts override it.

- Inventory: prove export/restore across machines/OSs; unify materialize with the inventory
  restore planner; review inventory-vs-disk comparison, recorded-branch restoration, individual
  repository selection and real GUI dialogs. Preserve explicit submodule/unsupported coverage.
- Fleet safety: retain raw dirty/ahead/stash facts even with local annotations for intentionally
  dirty trees. Review fleet-wide at-risk reporting and root-only “probably the same” identities.
  Compare provider inventory with the fleet union and surface local-only work without auto-enrollment.
- Recovery: verify discovery/restore across actual peers and exact checksum/retirement proof.
  Keep capture opt-in and snapshots unencrypted under the existing trust design. Unsaved-buffer
  transfer, other editors and backup latency need separate decisions/evidence; local metadata
  reading is not permission to publish content.
- Enrollment: improve guided secure fleet-key handoff and optional transport availability
  discovery without silently sharing the key in a state repository or installing a sync client.
  Verify actual enrollment rather than inferring it from a build or a historical machine list.
- Ordinary Git UX: finish diff/log/branch-switch/stash operations and app actions where still
  absent, with file/message review and explicit conflict handling. Per-repository basket choice,
  basket editing in the GUI and notification/route presentation still need acceptance.
- Preserve interactive-user execution for background components. Review remaining direct
  subprocess/provider calls in fleet/autostart/capture/retirement/restore/setup as their owners
  move, rather than relying on stale counts from an old audit.
- Native probes under `tests/probes/` are manual acceptance, not automated-suite coverage.
  Keep source/fixtures/instructions versioned; private profiles/logs/results stay local.
- Reproduce the older loopback Git-client timeout before changing its budget. Separately,
  the current intermediate advisory incomplete-vs-blocked result remains unexplained; isolated
  and full focused reruns passed. Preserve refusal states and masked diagnostics.
- Review optional account/host protections separately; no blanket shelf ruleset or settings
  change is authorized. A historical rewrite or old “clean” report is not current clearance.
- Private old plan folders, failed environments/caches and retained resume state require
  ownership/scope review before deletion. No cache/state cleanup or guard-deferred check is
  authorized just because the notes were pruned.
- Verify release/tag/build receipts and native packaging before cutting a release. Keep the
  source workflow package-free and guard against accidental editable-install artifacts.

### Deferred work

- Broader duplicator headless modes, a useful dry-run and individual-repository selection.
- Provider-backed multi-host support and future per-agent branch/PR workflows. Verify URL/port
  identity handling before adding hosts; keep authentication with the user's existing CLIs.
- A separate narrowly scoped handoff/recovery workflow only when the existing publish/capture
  paths cannot meet a demonstrated need. Do not revive superseded naming, host or key-sharing
  proposals as settled requirements.
