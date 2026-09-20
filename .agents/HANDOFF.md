# Handoff — 2026-09-19

For the next session, human or LLM. Read [`README.md`](README.md) (the project brief) first,
then this, then [`working-notes.md`](working-notes.md).

## 2026-09-19 — Current priority

The user has approved resuming Sync Suggester work. Keep this as **one repository,
one family** of elaborate but careful Git operations, with terminal commands as the
source of policy and the optional fleet service as their visual, cross-machine
coordinator. Do not make any machine authoritative and do not weaken the standalone
script workflow.

The headline feature is **seeing every repository everywhere, then receiving a safe
suggestion to synchronize unsynced work**. On 2026-09-19 the medium-tier chain was completed:
recovery location/policy/configuration, event-quiet capture, peer acknowledgement, preview,
disposable restore and exact upstream retirement proof. Setup preflight and opt-in Tailscale
session joining are wired; the local dashboard invokes the same fresh-fetch catch-up preview as
the terminal. `safe-to-wipe` now recognizes only an exact current snapshot verified by another
peer, never an unpushed commit or a merely old snapshot.

The locally actionable follow-through is also complete: `fleet audit` and `fleet materialize`
cover the observed local working set, `fleet live-buffers` provides explicit content-free VS
Code backup evidence, and the packaging recipe has a read-only release gate. Remaining work is
operational or needs a new product/privacy decision: enroll real peers, validate them together,
cut/sign/publish a release, and decide whether unsaved buffer *content* may ever cross machines.

On 2026-09-19 the Windows suite ran alone through the repository virtual environment:
**34/34 test files passed** — re-verified after the work landed. The recovery work is
**committed** (`checkpoint`), and the working tree is clean. No live fleet deployment, fetch,
pull, commit, or push against a real remote was performed.

**The next step is operational, not code.** Everything below the "Open decisions owed by the
user" heading is what remains; the blocking item is that no machine is enrolled yet.

## Continuation update — 2026-09-11

Active guidance now matches the peer runtime. Guided durable setup and deferred transport
publication are implemented in the working tree (see work log). The medium-tier recovery path
is activated only through explicit enrollment: capture, storage, preview, restore, local policy,
retirement proof and peer acknowledgement. Snapshots are **not encrypted**; the
trust-boundary decision is recorded in `git-sync-suggester/docs/RECOVERY-DESIGN.md` and requires
no dependency. Manual experiments belong in tracked `tests/probes/`. The VS Code hot-exit probe
has run: dirty buffers are persisted before exit, so the live tier can read the editor's own
backups rather than needing a plugin. The optional desktop Git client shortcut ships (open a
local checkout in Sourcetree / GitHub Desktop; it performs no Git operations). Baskets are built
and the capture basket still refuses every setting other than `none`.

## Do these three things before touching anything

1. **Map the tree with the tool, do not work from memory.** The layout changed substantially
   today.
   ```bash
   curl -sSfL -o .agents/tools/generate_folder_structure.py \
     https://raw.githubusercontent.com/sb4ssman/PythonTools/main/LLM_Tools/generate_folder_structure.py
   python .agents/tools/generate_folder_structure.py --path . --out .agents/output/folder_structure.md
   ```
   Then read the output file.
2. **Run the suite.** `& .\.venv\Scripts\python.exe tests\run_all.py` on Windows —
   34/34 as of this handoff. Do not run the suite in parallel with itself.
3. **Never commit personal information.** No local paths, machine names, addresses, or real
   account/org/repo names — in code, comments, tests, notes, or commit messages.
   `tests/repo/test_repo_hygiene.py` enforces it; it has already caught real leaks.

## Where the project actually stands

**Three special operations.** Org duplication and archive updating are careful scripts and are
stable. Sync Suggester is a small distributed system and is where all current work is.

**The fleet model was wrong until today and is now right.** There used to be a `host` that owned
the database and served the dashboard, and `connect` clients that pushed to it — so when the
host was off, nobody could publish and nobody had a dashboard. Now there is **one kind of
machine: a peer**. It observes itself, publishes to every transport it has, serves its own
dashboard on loopback, and talks to peers only when Tailscale happens to be up. **Peers pull;
nothing is ever pushed to a peer.** Do not reintroduce an authority.

**Tailscale is optional and last.** Nothing above the tailnet tier may depend on it. A peer with
no network still observes, still publishes to a synced folder, and still shows a dashboard.

**There is no scanning.** One acknowledged inventory, then kernel notifications (inotify /
`ReadDirectoryChangesW`). The only periodic work is a 30s tailnet poll and change-gated
transport publishes. Do not add a polling loop.

## Tier capability status

The three tiers currently carry the **same** v3 status manifest, so they differ only in latency.
They are supposed to differ in **what work they can rescue** — see
[`knowledge/tiers-and-capture.md`](knowledge/tiers-and-capture.md):

| Tier | Should preserve |
|---|---|
| Durable (private GitHub repo) | committed history + status |
| Medium (synced folder) | + **saved but uncommitted content** (the user's *stealth-stash*) |
| Live (tailnet) | + **unsaved editor buffers** |

Ordered next steps, agreed with the user:

1. **Guided durable setup — implemented.** It proposes a repo name, explains app ownership
   and publication conditions, and requires named creation/use confirmation.
2. **Content capture on the medium tier — implemented.** Capture, store, preview, disposable
   restore, exact retirement proof and peer acknowledgement are all wired behind explicit
   recovery-location and capture-basket enrollment. **Snapshots are not encrypted**: every tier already rides inside a system that
   authenticates, and the captured work is already plaintext in the working tree on the same
   disk — read the trust boundary section of `docs/RECOVERY-DESIGN.md` before reopening that.
   Protection is local per-repository policy (`CapturePolicy`: obey `.gitignore`, secret
   protection, `allow_paths`), on by default, relaxations recorded in the bundle.
3. **Unsaved buffers on the live tier — local evidence implemented.** VS Code does write dirty
   editor buffers to its backup store before exit; `fleet live-buffers` reports only bounded,
   root-confined metadata for buffers that differ from their saved files. It never outputs or
   transmits their content. Backup latency, other editors, and any cross-machine content
   transport remain open product/privacy decisions.
4. **Baskets — implemented 2026-09-11**, brought forward ahead of capture at the user's
   direction. Namespace selection per scope via `fleet baskets`; config schema v4. The three
   scopes are independent, and capture is *refused* rather than offered, so no toggle claims a
   protection that does not exist. Still namespace-granularity only, and CLI-only to change.

## Open decisions owed by the user

- **Git history still contains personal data** (machine names, tailnet addresses, paths,
  namespaces). No secrets — verified by scanning every blob; see
  [`knowledge/repo-privacy-and-history.md`](knowledge/repo-privacy-and-history.md). A rewrite is
  the only complete fix and breaks every clone and fork. Not done deliberately.
- **No release is cut.** `shared/version.py` is 0.2.0, there are no tags and no GitHub release,
  so `version --check` correctly reports "unknown" for everyone. Tag `v0.2.0` and publish, then
  confirm the check flips to "current".
- **Neither Windows machine is enrolled yet**, and the user has not run `run_setup` on this one.
  The peer model removed the blocker (no host needed); the durable tier needs one private state
  repo, which must not be created without the user naming it.

## Traps this codebase has already fallen into

Each of these shipped once. They are in the code comments too — do not re-learn them.

- **Validate on the platform you claim.** Windows-only defects have shipped twice because the
  suite was run on Linux. Windows filesystem observation had *never worked*: the ignore list was
  tested against the absolute path, so a root under `AppData` discarded every event, silently.
- **Silence is never good news.** A stale report can never become an "all clear". An update
  check that cannot reach GitHub reports *unknown*, not "up to date".
- **ctypes needs `argtypes`, not just `restype`.** Handles above 2³¹ raise "int too long to
  convert" — intermittently, because handle values grow during a session.
- **Status glyphs are not cp1252-encodable**, so a *redirected* stream on Windows dies after the
  real work succeeded. Every entry point calls `shared.console.enable_unicode_output()` first.
- **Flush logs.** A peer runs under the tray or at login with stdout redirected; block buffering
  leaves the log empty exactly when it is needed.
- **Detect → alert → approve.** Never silently mutate. The recent new-repository fix detects a
  freshly cloned checkout and *says so*; it does not add it. The defect was the silence, not the
  confirmation step.
- **`build_display` is the only place fleet state becomes display semantics.** Every skin — the
  browser UI and the tray — consumes that contract and refuses an unknown version rather than
  reclassifying Git facts.

## Verification commands

```bash
python tests/run_all.py                                    # 34/34
python tests/repo/test_repo_hygiene.py                     # sanitization gate
python git-archive-updater/archive_diff.py                 # pure-logic self-test
python git-sync-suggester/sync_suggester.py dashboard --serve   # local dashboard, no Tailscale
python git-sync-suggester/app/fleet_app.py --help
```
