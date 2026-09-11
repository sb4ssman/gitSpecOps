# Recovery snapshots: implementation contract

Design recorded 2026-09-11. Content capture remains unavailable until encryption, capture,
preview, restore, and retirement work end to end. This document is the next handoff slice,
not a claim that snapshots already exist.

## Purpose and scope

Preserve saved, uncommitted work in a folder the user's sync client replicates. A snapshot is
independent of the names-free v3 status manifest. The durable GitHub status repository never
receives file content. Capture does not run `git stash`, alter the index, or modify the source.

Enrollment is explicit per repository initially, later via basket subscriptions. Observing
or publishing a repository never enrolls it in capture. Existing configurations migrate with
capture off. The first-run UI must show which files are eligible and which are excluded.
Remote actions remain a separate feature.

## Encryption boundary

Proposed backend: an existing `age` CLI, invoked without a shell. This requires the user's
exception to the repository's stdlib-only runtime rule; approval is pending. Do not implement
cryptographic primitives in Python or silently install a package/tool as a workaround.

Use native age recipients supplied by the user. Public recipients may live in local capture
configuration; private identity files stay outside synchronized folders and outside source
repositories. Do not reuse the fleet identity secret as an encryption key. Every designated
recovery machine must have access to a private identity, carried out of band. Losing every
identity makes recovery impossible; verify decryptability during enrollment with synthetic data.

Encrypt the complete bundle, including filenames, base commit identifiers, metadata, and
patches. Only ciphertext may enter the synced folder. No plaintext spool files, content logs,
command-line content arguments, automatic key upload, or fallback to plaintext. Bound process
time, input, output, and memory. On encryption failure, retain the previous recovery artifact.

Reference: [age CLI and file format](https://github.com/FiloSottile/age#readme).

## Capture representation and consistency

A single encrypted bundle contains a versioned index plus:

- Base commit and tree identity, repository identity, source machine, capture time, and checksums.
- A binary-capable staged patch from HEAD to the index and a separate unstaged patch from the
  index to the working tree. A lone `git diff HEAD` loses staging boundaries and can omit staged
  work reversed in the working tree; it is insufficient for faithful recovery.
- Explicitly selected untracked regular files, stored with relative paths and checksums.
- Mode changes, tracked deletions, and a record of all exclusions and unsupported entries.

Disable external diff commands and text conversion. Use bounded subprocesses and literal
pathspecs. Read HEAD and index state before and after capture; reject a changing snapshot and
retry on the next event, with bounded retries. Recheck selected file metadata/content to avoid
publishing a mixture of editor writes. Debounce events, then capture only affected enrolled
repositories. Compare content digests rather than staged/unstaged counts to detect new edits.

The first slice rejects unresolved conflicts, in-progress Git operations, symlinks/reparse
points, submodule content, and unsupported modes instead of claiming complete recovery.
Support for unborn branches and a missing base object must be designed and tested explicitly.
A patch cannot restore against an unavailable base. Preview must report that condition, never
claim offline portability from status metadata alone.

## Limits and exclusions

Proposed initial defaults, adjustable downward or upward through explicit local configuration:

| Control | Default |
|---|---|
| Maximum plaintext per snapshot | 10 MiB |
| Maximum selected regular file | 2 MiB |
| Maximum selected files | 200 |
| Retained versions per repository | 10 |
| Maximum ciphertext storage per source machine | 250 MiB |
| Retention period | 7 days |

Enforce limits before reading large content and again on the serialized and encrypted outputs.
An oversized capture is refused visibly, never truncated. Each repository can supply capture
exclusion globs; `.git`, private-key files, credential stores, and local configuration are
always excluded. Respect Git ignore rules for untracked files even when a broad selector
matches them. Untracked capture defaults to none. Tracked sensitive files require exclusions
too; being tracked does not imply safe-to-copy.

Scan included plaintext locally for credential/private-key patterns before encryption.
On a match, refuse the snapshot and report only the path and rule, never the matched value.
An allowlist must be explicit and narrowly scoped. Pattern matching is best effort, not a
guarantee of secret absence; encryption and scope controls remain required.

## Delivery and retention

Write a complete encrypted artifact atomically beneath a dedicated snapshots directory, using
opaque repository identifiers and random version identifiers. Each source machine writes and
retires only its own artifacts. Multiple sources never overwrite one shared snapshot file.

Distinguish: captured locally, encrypted artifact placed in synced folder, acknowledged on a
second machine, and retired. A successful folder write does not prove off-device durability.
Acknowledgements name the ciphertext checksum and originate from the receiving machine.
Do not show 'recoverable elsewhere' before another machine verifies decryptability and integrity.

Retention expiration is explicit policy, not evidence of a successful commit. Show impending
expiration of the last recoverable copy. At quota, refuse new captures rather than silently
delete the last unacknowledged recovery artifact. User-requested deletion is previewed by count,
size, and scope, with paths confined to the snapshot store. Synced-folder deletion cannot
promise erasure of provider backups or offline copies.

Automatic retirement after publication needs proof: captured content must be represented by
a specific real commit and that commit must be reachable from a freshly verified remote ref.
A clean working tree, equal counts, or a successful push of unrelated work is insufficient.
If proof is unavailable, keep the artifact subject to the separately acknowledged retention
policy. Source fetching is explicit; do not introduce periodic Git fetches to enable retirement.

## Preview and restore

Decrypt only on explicit local request. Validate schema, lengths, checksums, path separators,
absolute/parent traversal paths, duplicate paths, and unsupported file types before extraction.
Never trust paths inside a decrypted archive. Use an isolated scratch directory outside sync
folders to preview file lists, staged/unstaged differences, exclusions, and required base.

First restore target: an explicitly selected disposable checkout at the captured base. Verify
the base and a clean index/worktree before applying staged then unstaged patches and selected
untracked files. Preflight all patches; never overwrite existing untracked files. A failed
restore must leave the source and user's working checkout untouched. Applying to an existing
dirty or different-base checkout is a later conflict workflow, not a forced fallback.

## Unsaved buffers and baskets

Unsaved buffers require a separate empirical VS Code experiment before production code.
Use a disposable file, type without saving, and verify backup contents appear before closing
the editor. Record the installed version, delay, settings, and whether the source file stayed
unchanged. A backup directory merely existing is not evidence. Even eager backups do not
establish a stable public format or support for every editor/profile/remote workspace.

Basket subscriptions must keep observe, publish, and capture independent. Start from an
explicit inventory preview and default capture to off. Namespace/path selectors must not
silently enroll new repositories into capture; changes need a reviewed scope preview.

## Acceptance gates

Offline tests must cover staged and unstaged changes to the same file, binary content,
deletions, selected untracked files, ignore rules, secret refusal, limits, changing files,
wrong keys, corrupted ciphertext, missing base, hostile paths, restore failure, independent
writers, acknowledgement, and retirement proof. Test a real encrypt/decrypt/restore round trip
with the chosen backend on the claimed platform before enabling capture in the dashboard.
