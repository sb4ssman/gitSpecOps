# Working notes

Living todo / scratch pad. Add items freely; **prune regularly**. When something is done, move it
into [`work-log.md`](work-log.md) with an absolute date. Dates are always absolute.

_Last tended: 2026-09-03_

## Open

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
    **Confirmed on the real Windows T: drive:** direct-child scans found all 5 Sb4ssport-Alpha
    agent repos, all 8 moon-and-back repos, and all 3 BonusBrain repos.
  - ~~**Compound facts hidden by precedence.**~~ **Fixed 2026-09-04.** `classify_repository` is now
    documented as a headline for severity *ordering only*; anything that renders or advises uses
    `repository_flags` / `describe_repository` / `secondary_facts`, so a repository that is dirty
    AND ahead now reads `STOP: uncommitted work on cbox (also ahead 9)`. Tests pin dirty+ahead,
    behind+stash, diverged+dirty, missing-upstream+dirty, and that a clean repository invents no
    extras.
  - **Integrations stay optional.** gitSpecOps, the org admin/agent repositories, Digital
    Cartography and BonusBrain are independent systems that interoperate through small contracts;
    none may become a required runtime dependency of Sync Suggester. Sync Suggester owns its local
    stable machine id (it already does — `config.py`, derived from the hostname and overridable)
    and may *optionally* accept a human label or metadata exported by another tool. Nothing to
    build until a concrete contract is proposed; the constraint is what matters.
  - **Intentionally-dirty trees (patch ledgers).** Org/agent policy may locally annotate such a
    tree as "recorded" or "drifted", but **raw dirtiness must still be published and must never
    become an all-clear**. Not built. The natural home is a local-only annotation in the catalog
    (beside `alias`), displayed alongside the state and explicitly excluded from classification —
    the manifest must keep carrying the raw counts.
  - **Run background operation as the interactive user**, so Git ownership, credentials,
    configuration and cloud-folder access all match. Applies to whatever schedules `check`; not
    built, and it is the main correctness trap in the tier-2 OS-timer idea.
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
  4. **Change detection via git hooks (tier 1)** — the "no running junk" mechanism, decided
     2026-09-03 and written up in [`knowledge/change-detection.md`](knowledge/change-detection.md).
     A chained global `core.hooksPath` dispatcher that publishes local state on
     `post-commit`/`post-checkout`/`post-merge`/`post-rewrite`. Must chain to each repo's own
     hooks, must always exit 0, and must never do network I/O — so with the repo transport the
     hook writes locally and something else uploads. An OS timer stays optional (tier 2) because
     the freshness model already degrades to "unknown" rather than lying.
     Also still open: **joining a fleet in one step** on machines two and three.
  5. `handoff` — **design pass written 2026-09-03** ([`handoff-design.md`](handoff-design.md));
     still unbuilt, on purpose. Its recommendation is to not build it yet: most of "I left work on
     the other machine" is unpushed commits, which `--publish` now covers. Three open questions
     there need the user's answer before any code.
  6. Long-lived stashes: information, or do they block an "all clear"? Currently `stashed` ranks
     above `unknown` but below `ahead`, so it surfaces without shouting.
  7. The **advice → apply** step (clean + behind-only + fresh fetch -> `git pull --ff-only`) stays
     purely advisory until fetching is settled.

- [ ] **Transports: `state_dir` and `state_repo` both ship; folder auto-detection is not built.**
  The user chose "both, gh-backed first" — the gh Contents API transport landed 2026-09-03. Still
  to do: probe the known OneDrive/Dropbox/Drive/Syncthing/iCloud locations per OS at `init` so a
  machine with a sync client needs no path typed. Note this machine has *no* such folder (only
  `rclone`), so auto-detection is a convenience, not a default. `rclone` remains a possible
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
