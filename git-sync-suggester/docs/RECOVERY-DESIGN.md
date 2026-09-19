# Recovery snapshots: implementation contract

Design recorded 2026-09-11; trust boundary settled 2026-09-12. The v1 medium-tier path is now
implemented: separately confirmed local storage, local per-repository policy, event-driven
capture, peer acknowledgement, preview, disposable restore, and exact remote retirement proof.
It remains opt-in and intentionally narrow; this document describes both the implemented contract
and the boundaries that remain.

## Purpose and scope

Preserve saved, uncommitted work in a folder the user's sync client replicates. A snapshot is
independent of the names-free v3 status manifest. The durable GitHub status repository never
receives file content. Capture does not run `git stash`, alter the index, or modify the source.

Enrollment is explicit per repository initially, later via basket subscriptions. Observing
or publishing a repository never enrolls it in capture. Existing configurations migrate with
capture off. The first-run UI must show which files are eligible and which are excluded.
Remote actions remain a separate feature.

## Trust boundary — decided 2026-09-12: no file encryption

**Snapshots are written in the clear, like manifests.** An earlier draft of this document
required an `age` CLI and a stdlib-only exception to go with it. That was wrong, and the
correction is the design: every tier of this tool rides *inside* a system that already performs
its own authentication, and the job is to work within those systems rather than rebuild them.

| Tier | Authority relied on | Wire |
|---|---|---|
| Durable | private GitHub repository, `gh`-authenticated; `RepoTransport.doctor()` refuses a repository that is not private and writable | HTTPS |
| Medium | the user's own sync client account | the provider's HTTPS |
| Live | Tailscale: `peer_identity()` resolves the caller's IP and rejects any device not owned by the allowed login, and any tagged device | WireGuard |

The tailnet peer endpoint is deliberately plain `http://`. WireGuard already provides
confidentiality and Tailscale already proves device identity; adding TLS there would
re-implement a check the layer beneath has already made.

Three facts close the gap that file encryption would otherwise fill:

1. **Locally, capture discloses nothing new.** The uncommitted work being captured is already
   sitting in plaintext in the working tree on the same disk. A bundle beside it adds no local
   exposure that did not already exist.
2. **Remotely, access control is the boundary** — the same conclusion already recorded for
   manifests in `.agents/knowledge/manifest-privacy.md`, reached there by carrying less rather
   than by encrypting.
3. **A key would cost more than it buys.** To restore on a second machine that machine needs the
   key; carrying identities to every peer is a subsystem, and losing them destroys exactly the
   work the feature exists to save. A key stored beside its ciphertext protects nothing — the
   same reasoning that keeps `fleet_secret` out of the state directory.

**What stays cryptographic:** the existing HMAC over repository and branch names. Its purpose is
not content confidentiality but that a state folder does not enumerate the user's repository
list. Snapshots keep using opaque repository identifiers for the same reason.

**What this shifts onto other controls.** Encryption was never going to stop the realistic harm —
a credential in an uncommitted file replicated to every peer. Secret scanning is therefore
load-bearing, not a nicety, and the limits, exclusions and explicit enrollment below carry the
weight that ciphertext was imagined to carry.

**Capture never inherits the status folder.** A folder transport may have been pointed at a
shared or team location precisely because names-free manifests were harmless there. Snapshots
carry filenames and source, so the capture location is confirmed separately, at capture
enrollment, and the app must warn when the chosen location is the status folder or is shared.

Revisit this decision only for a concrete threat these three tiers do not already cover. If it
is ever revisited, the bundle is an envelope with a declared format field, so encryption can be
added as a new format without changing the capture, preview or restore paths.

## Capture representation and consistency

A single bundle carries a declared format field (so a future encrypted format is additive) and a
versioned index plus:

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
| Maximum content per snapshot | 10 MiB |
| Maximum selected regular file | 2 MiB |
| Maximum selected files | 200 |
| Retained versions per repository | 10 |
| Maximum snapshot storage per source machine | 250 MiB |
| Retention period | 7 days |

Enforce limits before reading large content and again on the serialized output.
An oversized capture is refused visibly, never truncated. Untracked capture defaults to none,
and `.git` is always excluded: that is repository structure, not a policy question.

Two further protections are **per-repository, local-only policy** (`capture.CapturePolicy`),
decided 2026-09-12 with the user. Both default on; either can be switched off deliberately on one
machine; neither setting is ever synced.

| Policy | Default | When on |
|---|---|---|
| Obey `.gitignore` | on | an ignored file is never carried, even when explicitly selected |
| Secret protection | on | likely credential files (`.env`, `*.pem`, …) are excluded by name, and content the snapshot adds is screened |

`allow_paths` names specific repository-relative paths that pass both the name exclusion and
screening while protection stays on for everything else. It exists because the alternative is
worse: a user who deliberately carries their `.env` with protection on would otherwise have every
snapshot of that repository refused, and the only way out would be switching protection off
entirely. Whenever a policy is relaxed, the bundle records it in its notes, and the dashboard
must say so — relaxing a protection is never silent.

Screening reads the lines each patch section *adds*, plus whole carried files; context and
removed lines are already in the committed base, and flagging them would refuse a snapshot for
rotating a secret out. Binary content cannot be pattern-screened. On a match, refuse the
snapshot and report only the path and rule, never the matched value. Pattern matching is best
effort and never a guarantee of secret absence — which is precisely why enrollment stays narrow
and explicit, and why a refusal is visible rather than downgraded to a warning.

## Delivery and retention

Write a complete artifact atomically beneath a dedicated snapshots directory, in the separately
confirmed capture location, using opaque repository identifiers and random version identifiers.
Each source machine writes and retires only its own artifacts. Multiple sources never overwrite
one shared snapshot file.

Distinguish: captured locally, artifact placed in the synced folder, acknowledged on a second
machine, and retired. A successful folder write does not prove off-device durability.
Acknowledgements name the bundle checksum and originate from the receiving machine. Do not show
'recoverable elsewhere' before another machine verifies the bundle reads back and its checksums
match.

Retention expiration is explicit policy, not evidence of a successful commit. Show impending
expiration of the last recoverable copy. At quota, refuse new captures rather than silently
delete the last unacknowledged recovery artifact. User-requested deletion is previewed by count,
size, and scope, with paths confined to the snapshot store. Synced-folder deletion cannot
promise erasure of provider backups or offline copies.

Retirement uses proof: it reconstructs the exact tree represented by staged patch, unstaged
patch, and carried files in a temporary Git index, freshly fetches `origin`, and compares it with
the upstream tree. A clean working tree, equal counts, or a successful push of unrelated work is
insufficient. If proof is unavailable, keep the artifact subject to the separately acknowledged
retention policy. This fetch is explicit through `fleet recovery retire`; periodic observation
does not fetch in order to delete a snapshot.

## Preview and restore

Read a bundle only on explicit local request. Validate schema, lengths, checksums, path
separators, absolute/parent traversal paths, duplicate paths, and unsupported file types before
extraction. **A readable bundle is still untrusted input**: it was written by another machine,
so never trust paths inside it. Use an isolated scratch directory outside sync folders to
preview file lists, staged/unstaged differences, exclusions, and required base.

First restore target: an explicitly selected disposable checkout at the captured base. Verify
the base and a clean index/worktree before applying staged then unstaged patches and selected
untracked files. Preflight all patches; never overwrite existing untracked files. A failed
restore must leave the source and user's working checkout untouched. Applying to an existing
dirty or different-base checkout is a later conflict workflow, not a forced fallback.

**Fidelity boundary — measured 2026-09-12 on Windows, Git 2.52.** Restore promises Git-content
fidelity: after applying, `git diff --staged` and `git diff` in the target reproduce the captured
patches byte for byte, and restore verifies exactly that before reporting success. It does not
promise working-tree byte fidelity for patched text files: the target checkout's own line-ending
conversion (`core.autocrlf`, `.gitattributes`) applies, as it would on any ordinary checkout of
the same content. Carried untracked files are written raw and stay byte-identical. Apply runs with
whitespace handling pinned on the command line, because a user's `apply.whitespace=fix` would
silently rewrite restored content and `error` would refuse it. Capture pins diff prefixes for the
same reason (`diff.mnemonicPrefix` changes them), and refuses text that is not valid UTF-8 rather
than storing a lossy decode. Symbolic links and submodules are refused by preview in this slice.

## Unsaved buffers and baskets

The `fleet live-buffers` command now performs the deliberately narrow first production slice:
it reads existing VS Code backup metadata only when the URI resolves beneath a configured root,
reports a bounded content-difference fact, and neither prints, stores, watches nor transmits
buffer content. A disposable-file probe remains the way to establish backup existence for a
specific installed VS Code version. It does not establish backup latency, a stable public format,
or support for every editor/profile/remote workspace. Publishing unsaved content requires a
separate privacy and transport decision.

Basket subscriptions must keep observe, publish, and capture independent. Start from an
explicit inventory preview and default capture to off. Namespace/path selectors must not
silently enroll new repositories into capture; changes need a reviewed scope preview.

## Acceptance gates

Offline tests must cover staged and unstaged changes to the same file, binary content,
deletions, selected untracked files, ignore rules, secret refusal, limits, changing files,
corrupted or truncated bundles, missing base, hostile paths, restore failure, independent
writers, acknowledgement, and retirement proof. Test a real capture/preview/restore round trip
on the claimed platform before enabling capture in the dashboard.
