# Local settings: schemas, resolver, migration preview and writer

Status: common v1 plus typed enrollment v2, read-only migration preview and explicit writer
implemented, 2026-10-26. Product requirements are in
[product-contract.md](product-contract.md). This reader does not yet replace existing command
configuration, enroll machines or configure log handlers. No actual settings migration has run.

Implementation: [`Special/_settings.py`](../../Special/_settings.py).
Typed enrollment records: [`_settings_records.py`](../../Special/_settings_records.py).
Preview and writer: [`_settings_migration.py`](../../Special/_settings_migration.py),
[`_settings_store.py`](../../Special/_settings_store.py).
Focused tests: [`test_settings.py`](../../tests/special/test_settings.py),
[`test_settings_migration.py`](../../tests/special/test_settings_migration.py).

## Location and read behavior

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
The new resolver never imports legacy settings automatically. Old commands keep their current
readers until a deliberate cutover. `GITSPECOPS_SYNC_HOME` remains a legacy-reader override;
the common resolver does not reinterpret it as a new global home. Sync/app/common resolution
with that legacy override requires migration or an explicitly chosen new home, rather than
silently ignoring it. Other independent components are not redirected by a sync-only override.

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
    "security": {"never_publish": [], "safe_values": []}
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
| security | never_publish and safe_values: lists of nonempty literal strings |

The example shows complete built-in defaults plus one illustrative component override. Report
files are off by default. Local operational logging is the default preference, with 10 MiB
rotation and three backups; no logger is started by this reader. Actual logging still needs
the shared handler/routing implementation, concurrency rules and explicit failure behavior.
Reporting directory preferences do not themselves request file output or create directories.
There are no raw-value disclosure settings yet: channel-specific revelation remains separate
work. Security policy values belong in private local configuration, not tracked examples.

## Resolution and privacy

`resolve_settings(component=None, *, home=None, overrides=None)` applies:

1. Built-in defaults.
2. Saved defaults.
3. The selected component's saved settings.
4. Explicit invocation overrides supplied by the calling CLI/app operation.

Fields replace earlier fields except excluded paths and never-publish values, which accumulate.
An invocation can add exclusions/protected values but cannot clear inherited ones with an empty
list. Removing them requires an intentional change to their owning saved settings. Lists of
roots replace rather than accumulate, so selecting a narrower operation stays possible.
Exact case-insensitive overlap between safe and never-publish values is rejected as a conflict;
the reader does not silently choose precedence. Broader detector-specific exception semantics
still require the security-policy integration work.

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
not deleted, renamed or adopted automatically, and no command reader has switched yet.

Still open: guided settings write/migration UI, record adapters and coordinated reader cutover,
explicit conflict choices, action-consent review, storage relocation/locator, logging integration
and native OS validation. New settings preservation does not enable unattended actions or
complete source updating, enrollment or uninstall. Tests use temporary, invented fixtures;
no actual user settings were read or changed during this implementation.
