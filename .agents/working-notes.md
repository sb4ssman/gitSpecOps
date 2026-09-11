# Working notes

Living todo / scratch pad. Add items freely; **prune regularly**. When something is done, move it
into [`work-log.md`](work-log.md) with an absolute date. Dates are always absolute.

_Last tended: 2026-09-11_

## Open

### Current continuation — 2026-09-11

Stale active host/client guidance has been reconciled. Guided durable setup, pending transport
delivery, the desktop Git client shortcut and **baskets** are implemented; details are in the
work log.

- **Medium-tier recovery is deferred by the user's decision (2026-09-11):** do baskets first,
  decide encryption later. The implementation contract is already written in
  [RECOVERY-DESIGN.md](../git-sync-suggester/docs/RECOVERY-DESIGN.md) — scope, staged versus
  unstaged fidelity, encryption, quotas, exclusions, secret screening, restore, retirement
  proof. **Nothing is blocked on the `age` question until capture is picked up again**; no
  encryption dependency is installed and no content-capture code exists. The capture basket
  refuses any value but `none`, so there is no cosmetic toggle in the meantime.
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

- [ ] **The tier ladder is not built yet (design recorded 2026-09-11).** See
  [knowledge/tiers-and-capture.md](knowledge/tiers-and-capture.md). Today all three tiers carry
  the *same* v3 status manifest, so they differ only in latency. They are supposed to differ in
  what they can rescue: durable = committed + status; medium = **saved but uncommitted content**;
  live = **unsaved editor buffers**. Ordered next steps:
  1. **Guided durable setup — implemented 2026-09-11.** Suggested private repo name,
     app ownership/publication explanation, and named CREATE/USE confirmations.
  2. **Content capture on the medium tier** (the user's *stealth-stash*): a patch bundle per
     repository, encrypted, size-capped, expiring after the real commit is published, separate
     from the manifest. Controls are now designed in `docs/RECOVERY-DESIGN.md`;
     encryption dependency choice remains pending before capture implementation.
  3. **Unsaved buffers on the live tier — probe answered, reader unbuilt.** VS Code does write
     dirty buffers to its backup store before exit (measured 2026-09-11 via
     `tests/probes/vscode_hot_exit/probe.py --run`). So no editor plugin is needed for VS Code:
     read what the editor already wrote. Still undecided and unbuilt: backup latency, the
     mapping from a backup file back to its repository and path, other editors, and whether
     unsaved content may leave the machine at all.
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

- [ ] **First release is not cut.** `shared/version.py` says 0.2.0 and the update check works,
  but there are **no tags and no GitHub release**, so `version --check` correctly reports
  "unknown" for everyone. Tag `v0.2.0`, publish a release, then confirm the check flips to
  "current". Until that exists, the update path is untested against reality.

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
  developing a self-contained installed app. Baskets, encrypted recovery and narrow remote Git
  jobs remain future work in the agreed tier order. Integration choices are independent;
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
    are all **already built** (see [`work-log.md`](work-log.md)). What genuinely remains from that
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
- [ ] **Recovery snapshots (user names: stealth-stash / stealth-sync).** This means an opt-in,
  encrypted snapshot of staged, unstaged and selected untracked work that survives the source
  machine going offline, can be previewed/applied elsewhere, and expires after the real commit is
  safely published. It is separate from remote actions and must have retention, size, ignore,
  secret-scan and deletion controls. The dashboard display contract exposes it as unavailable until
  content capture and restoration are implemented; do not present a cosmetic toggle.

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
- Multi-host support is a stated goal: archive tools first via `shared/providers.py` (one
  `provider_<host>.py` + `register_provider(...)` per host; fix `remote_identity` URL-port
  parsing first). `github-org-duplicator` stays GitHub-specific by design. Auth stays
  user-owned (host CLI logins); no credential management anywhere.
