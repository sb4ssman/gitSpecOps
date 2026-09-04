# Sync Suggester manifest privacy — what the v1 boundary actually protects

_Recorded 2026-09-03, from inspecting a real published manifest during the first slice._

## What the boundary does hold

A published manifest contains no repository name, no owner, no host, no remote URL, no local
path, and no filename. That was verified against a real 20-repository manifest: scans for the
archive path, the account name, a repository name, `github.com`, `/home/`, and `http` all
returned zero hits. Repositories appear only as `repo_id`, a SHA-256 of the canonical
`host/owner/name`.

## What it does not hold, and why that matters

Three fields are still real correlators:

- **`repo_id` is an unsalted hash of a tiny input space.** Anyone holding the state folder can
  build candidate strings (`github.com/<known account>/<repo name from a wordlist>`, or simply
  every public repo of an account they already suspect) and hash them until they match. Hashing
  a low-entropy identifier is obfuscation, not anonymity.
- **`head` is a commit SHA.** For any repository that is public — or that the reader can
  otherwise see — a head SHA can be looked up directly and identifies the repository outright.
  It is the strongest de-anonymizer in the record, and nothing in the tool reads it: `advice.py`
  and `aggregate.py` classify entirely from `ahead`/`behind`/dirty counts/`operation`/`stashes`.
  It is currently written and never used.
- **`branch` is a human-authored string.** `feature/acquire-northwind` says more than the
  repository name would.

Net effect: someone who obtains the state folder — the cloud provider hosting it, a device where
that folder is also synced, an old backup — can often recover the list of repositories on each
machine. That is precisely what the hashing was introduced to prevent.

## Options (a design decision, not a bug fix)

1. **Salt the identity.** `HMAC-SHA256(secret, host/owner/name)` with the secret stored only in
   local config and never in a manifest. Closes the brute-force hole cheaply. Costs: the secret
   must reach every machine (it can ride in the same private state folder, or be typed at
   `init`), and rotating it orphans every peer's history.
2. **Drop `head`.** Nothing reads it. This is the cheapest real improvement available and costs
   nothing today. If a future feature wants "are these two machines on the same commit?", a
   salted short digest of the SHA answers that without publishing the SHA itself.
3. **Treat `branch` like display names.** Publish a hashed branch id and keep the readable name
   in the local-only catalog, exactly as repository names already work.
4. **Change nothing and document the threat model.** The transport is a private folder the user
   chose. Then the honest statement is: *the state folder is as sensitive as a list of your
   repository names and the branches you work on* — which is a fine position, but it should be
   written down rather than implied by the word "privacy-minimized".

## Recommendation

Do (2) and (4) whenever the schema next moves — dropping an unused field is free and removes the
strongest correlator. Do (1) at the same time if cross-machine identity is worth a shared secret.
`schema_version` is the lever: any of these is a v2, and `validate_manifest` already refuses a
version it does not know, so a mixed-version fleet fails loudly instead of silently mis-joining.
