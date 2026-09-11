# Public-repo privacy: what was checked, how confident, and what to do about history

This repository is **public**. Recorded 2026-09-11.

## The working tree is clean, and a test keeps it that way

`tests/repo/test_repo_hygiene.py` scans every *tracked* file on every run for secrets, local
paths, real Tailscale addresses, tracked generated launchers, leaked `.agents/tools|output`
files, and a missing LICENSE. Each pattern corresponds to something this repository shipped or
nearly shipped. If it fails, fix the file; only widen its allowlist after deciding a match is
genuinely documentation or invented fixture data.

## History audit — method and result

The first pass used `git log -p --all | grep`, which only covers **diff text** on reachable
refs and skips binary blobs. That was not good enough to make a claim, so a second pass
enumerated **every object in history** (`git rev-list --objects --all`) and scanned the content
of **every blob** — 566 objects, 355 blobs — for seven secret shapes (64-hex fleet-secret shape,
GitHub tokens, AWS keys, private-key blocks, Slack/Stripe/Google keys, credential assignments,
and URLs with inline credentials).

**Result: no secrets in history.** The only credential-shaped hit is
`http://user:password@100.64.0.1:8765` in `test_fleet_app.py` — a fixture asserting that such a
URL is *rejected*.

**Personal data is in history** and was never removed, only sanitized going forward: three
Tailscale addresses, four machine names, five private namespaces, one Windows user path.

Confidence: high for those seven shapes across all reachable objects. It does **not** cover
unreachable/dangling objects, and no regex set is exhaustive. For an independent opinion use
`gitleaks detect --log-opts=--all` or `trufflehog git file://.`, and check GitHub's own secret
scanning (free and on by default for public repositories) under the repository's Security tab.

## If a secret is ever found in history

Order matters, and the first step is the one people skip:

1. **Revoke and rotate the secret first.** Publishing it is the breach; rewriting history does
   not un-publish it. Assume it was captured the moment it was pushed.
2. Rewrite history with `git filter-repo --replace-text` (or BFG). `filter-branch` is
   deprecated and slow.
3. Force-push every ref and tag. **Every clone and fork must re-clone** — old clones still hold
   the object, and a rebase or merge from one can reintroduce it.
4. Ask GitHub Support to purge cached views and fork-network objects. A commit can stay
   reachable through a fork or a cached URL after a force-push; this step is what actually
   removes it from GitHub.
5. Rotate again afterwards if the value was ever used in the interval.

## Why history was NOT rewritten here

What is in history is machine names, private-range Tailscale addresses, folder paths and
namespace names — **no credentials**, so there is nothing to rotate and no access to revoke.
Rewriting would break every existing clone and fork for a low-value cleanup.

That is a judgement, and the user may overrule it. If they do, the procedure above applies
minus the rotation steps, and the trade is: a clean history against invalidating every clone.
