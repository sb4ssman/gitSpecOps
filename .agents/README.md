# gitSpecOps — project brief (`.agents/README.md`)

**This is the primary project document. Read it first.** Root `AGENTS.md` and `CLAUDE.md` are lean
pointers to this file. Tend this document as the project evolves — it is the durable, hand-authored
knowledge the code and git history do not capture.

Shape: repo-standalone from Structural-Engineering @ fdd316c
Coordination: standalone

This `.agents/` folder is public on purpose: it follows the
[repo-standalone shape](https://github.com/Sb4ssport-Alpha/Structural-Engineering/tree/main/shapes/repo-standalone)
of the Sb4ssport shelf, which anyone can adopt for their own repositories.

## What this is for (read before any rule below)

**Start from the situation:** a user has many repositories, spread across many orgs and
namespaces, checked out on several machines. Off-the-shelf clients (GitHub Desktop, Sourcetree,
GitKraken) are surgical tools — fine for one repository at a time, and weak at exactly this. The
family here starts from the many-repos-many-machines case and keeps it in order.

Each operation came from a plain "I should be able to…":

- *I should be able to pull a whole org down to a new machine* → **org duplicator**
- *I should be able to keep a set of repos pulled and fast-forwarded as a group* → **archive updater**
- *I should be able to see which repos need syncing — everywhere they are, from any machine, and
  then fix it* → **Sync Suggester**

The desktop outcome, in the user's words: glance at the system tray, see that repositories are out
of sync, open a dashboard to see where and what, rescue orphaned uncommitted changes, and get
everything in order for every machine — including after not touching a computer for weeks.
Simple, visual, and **equally operable from the terminal**, like the first two tools.

**Therefore these tools perform Git operations.** That is the point. The safety model is about
*how* they act — never *whether*. Three rules (rewritten 2026-10-19 with the user; the earlier
"the peer, tray and dashboard only observe" contradicted the goal — catching up on wake, and
committing or pushing from the app, are what the product is for):

1. **Watching never changes anything by itself.** Observing, publishing this machine's status
   and fetching are the background's whole job. No change to a repository is ever a side effect
   of observation or of time passing. A daemon that *decides* to pull is the catastrophe.
2. **Background change only under standing consent the user configured.** The peer, the
   scheduler and the wake / sleep / login triggers may change a repository only through a
   consent the user set up explicitly — named, narrow, visible in the app, revocable, logged —
   and only within the safe class: fast-forward of a clean, behind-only checkout (the
   auto-update basket; the archive launchers already work this way). A request arriving from
   another machine's mailbox runs unattended only if such a consent covers it; otherwise it
   waits on this machine as a suggestion. Commit, merge, rebase, reset, rename, delete, origin
   rewrites and anything forced are never covered by any consent.
   *Amended 2026-10-22 with the user:* **a person may command another of their machines.** The
   network and the machines are the user's own and already trusted, so "B, commit these files
   and push" is legitimate when it is *attended from the other keyboard*: B produces the exact
   plan (files, diff summary, branch, the commit it would make), the requesting machine shows it
   to a person -- alone or helped by an AI -- who approves it there with a typed word; the
   request is bound to that plan, and B re-checks that its state still matches before acting,
   or refuses. B needs no person and no AI of its own. The channel is the fleet's own peer
   protocol over the tailnet (Tailscale identity + fleet key), with a fixed set of verbs, never
   a shell. Forced pushes, reset, rebase, merge and delete stay out of reach from anywhere.
   *Amended 2026-11-18:* **the two safe requests can run on arrival with explicit opt-in.** A request
   from another machine of the same fleet can only ask for a fast-forward after a fresh fetch
   or a clone that replaces nothing. The receiving machine waits for Apply by default; its
   Settings page can opt in to running these requests on arrival without a second approval.
   **App Security** also allows confirmation on the sending device, with a click or typed
   acknowledgment. Both options trust the authenticated sending device. One approval applies
   to the received request and expires after 15 minutes. Each machine chooses its own policy.
   **Pause incoming operations** holds fleet writes while the local Git actions remain available.
   The fleet executor validates the request again and uses approved HTTPS provider URLs,
   bounded local checkout paths and fixed Git arguments. Checkout-owned execution rules and
   rewritten destinations require local review. A fast-forward applies the fetched commit that
   was planned and refuses an ignored-file collision.
   Commit and push on another machine remain the attended design above.
3. **Everything else is a command the user invoked**, from the terminal, a tray item or a
   dashboard button alike — the same command, the same plan → show → confirm:
   detect → plan → approve → execute → review. Fast-forward-only pulls, non-force pushes, nothing
   auto-committed.

The tiers are meant to *differ in capability*, not just latency: durable (a private repo — free,
`gh`-shaped, available to anyone) carries committed history and status; medium (a synced folder or
faster-pinging store) adds saved-but-uncommitted content; live (tailnet) adds real-time and
unsaved buffers. See [`knowledge/tiers-and-capture.md`](knowledge/tiers-and-capture.md).

If a rule further down this file contradicts this section, **this section wins** and the rule is
the thing to fix. That is not hypothetical: a scaffold-era "never writes" claim outranked this
goal for seventeen days (the archived design notes record the correction).

## Directives (how to work in this repo)

### How this user works

Answer the question asked, plainly and briefly. Explain the plan before acting and always say
what was not verified. Ask before running anything in the background (tray, peer, or scheduled
tasks), acting over SSH, or capturing any screen. Work with the Destructive Command Guard, never
around it. Do not force-push, reset, rebase, or delete branches. Work on `dev`; merging to
`main` is the user's call. Commit and push only when asked.

### Development preview workflow

1. Work on `dev`. Verify the change in that checkout and run the repository hygiene and security
   checks. Keep unrelated work out of the release.
2. When the user asks to distribute the preview, commit and push the verified work to `dev`, then
   promote it to `main` through the repository's pull-request workflow. Verify both remote refs.
   The installed `gitso update` follows the checkout's configured upstream branch, so both
   channels need the fix for propagation.
3. A running preview loads its Python modules and web assets at startup. Refresh it through its
   existing lifecycle when authorized, using the same profile. Check the served page version or
   assets and exercise the changed behavior. A browser reload against the original process still
   serves the original code. On the tray, the local lifecycle is `gitso tray --stop` then
   `gitso tray`. A fleet trial needs the updated preview on both peers.
4. Report the commit or pull request for each branch and what the running preview actually
   served and did. If a guard or authorization prevents any step, report the exact blocker.

This repository is public. Keep machine names, real paths, and the user's name and email out.
Run `tests/repo/test_repo_hygiene.py` before every commit and **stop if it fails**. On
2026-11-17 a machine name reached a pushed commit because a hygiene failure was ignored.

### Canonical product contract

Read [knowledge/product-contract.md](knowledge/product-contract.md) before work on setup,
enrollment, output, security or presentation. It records the 2026-10-26 direction: one coherent
app over independently useful operations, remembered per-machine context and explicit output
policy. Its acceptance work is in WORKING-NOTES. It extends the existing layer/security designs;
old handoffs and descriptions of current code do not override these newer decisions.

What each command does today is generated from its source: `gitso commands`, or
[`docs/COMMANDS.md`](../docs/COMMANDS.md).

### Start every session by looking, not remembering

1. **Read this file**, then [`WORKING-NOTES.md`](WORKING-NOTES.md) for current work and the
   latest [`WORK-LOG.md`](WORK-LOG.md) entries for evidence. Older handoffs were absorbed into
   the log and removed on 2026-11-14; git history keeps them.
2. **Map the tree with the tool**, do not reconstruct it from memory or a few `ls` calls:

   ```bash
   python .agents/tools/generate_folder_structure.py --path . --out .agents/output/folder_structure.md
   ```

   If the script is not there, fetch it first — [`tools/README.md`](tools/README.md) has the
   one-line `curl`. It is gitignored on purpose and takes seconds to retrieve on any machine.
   Then **read the output file.** This repo has been reorganized; a session working from a
   remembered layout will confidently reference files that moved.
3. **Verify before asserting.** Anything you state about this codebase — a path, a flag, a
   behavior — gets checked against the working tree in the same turn you claim it. A memory or
   an older note is a lead, never evidence.

### This is a PUBLIC repository — never write personal information into it

Applies to **every tracked file**: code, comments, docstrings, tests, `WORKING-NOTES.md`,
`WORK-LOG.md`, `knowledge/`, and commit messages. Never commit:

- **Absolute local paths** (`T:\…`, `/home/<you>`, `/srv/<drive>`, `C:\Users\…`) — use
  `<library-root>`, `/path/to/archive`, or a clearly invented example.
- **Real machine names, IP addresses (Tailscale `100.x` included), or tailnet topology** — use
  `<prime-tailscale-ip>`, `machine-a`.
- **Real account, organization, or repository names** — fixtures and self-tests use invented
  names (`old-team`, `new-team`, `example/work`). A real namespace in a self-test is still a
  disclosure, and `archive_diff.py` shipped with one for months before it was caught.
- **Secrets of any kind.** The fleet secret, tokens, anything 64-hex. `fleet doctor` and config dumps
  must keep printing `(set, hidden)`.

Write the *shape* of the finding, not the specimen: "a root under an ignored name discarded
every event" beats naming the drive it happened on. When you must record an operational detail
to be useful, sanitize it as you write it — not later.

`output/` and everything in `tools/` except its README are gitignored, so local detail may live
there freely. That is the release valve.

### Keeping the record

- **Keep `WORKING-NOTES.md` current** — a living todo / scratch pad. Add items as they arise; prune
  stale or resolved ones regularly. It is what saves the next session from reconstructing state.
- **Graduate completed work into `WORK-LOG.md`**: append at the **bottom**, newest last, as
  `## YYYY-MM-DD HH:MM - <User> (<agent>) - <title>`, with the time read from the clock. Never
  edit or delete a past entry — append a correction. The log is union-merged (`.gitattributes`),
  so concurrent appends never conflict. Always write dates absolutely — never "yesterday".
- **Record durable decisions and findings under `knowledge/`** (one topic per file). Working notes
  are transient; knowledge is kept.
- **Record the bug's cause, not just its fix.** The valuable half is why it hid — which platform,
  which assumption, which test could not see it.

### Constraints that do not bend

- **Prior auth first. Auth belongs to the user.** Tools shell out only to already-authenticated
  host CLIs (`gh auth login`, ...); nothing here stores, configures, or manages credentials, and
  nothing falls back to asking for a secret.
- **Cross-platform first.** Windows, Linux and macOS are peers, not a primary and two ports. A
  platform-specific mechanism (registry Run key, XDG autostart, LaunchAgent, `ReadDirectoryChangesW`
  vs inotify) is written behind one command that works everywhere.
- **Plain scripts, layered — not a package.** No `src/` package, no console-script entry points,
  no clever indirection; every module stays a plain script that can be run directly. Directories
  express the layer stack ([`knowledge/architecture-layers.md`](knowledge/architecture-layers.md)),
  with a one-way import rule: a layer imports only layers below it. *Amended 2026-09-20 — this
  previously read "keep the repo flat", which was about avoiding premature packaging; it was
  being read as "never introduce structure" and would have contradicted the agreed architecture.*
- **No runtime dependencies.** Everything is stdlib. A build-time tool (PyInstaller) lives in a
  disposable environment, never in `pyproject.toml`.
- **Validate on the platform you claim.** "The suite passes" means the suite passes *here*.
  Windows-only defects have shipped twice because validation happened on Linux.

## One operation, two faces (decided 2026-11-17)

**The scripts are the product.** Every operation is a plain Python function in `Basic/`,
`Special/` or `Elaborate/`; its script is a thin command-line face on it, and the page (and the
tray) is a second thin face that calls the same function with the settings profile and the
target given explicitly. The page never starts a script as a separate program and never rebuilds
a command line: that is how a profile was once lost between the page and `secure-commit`.
[`docs/ONE-OPERATION.md`](../docs/ONE-OPERATION.md) follows one click down to its tests.

## Where things are

| Folder | What it holds |
|---|---|
| `Basic/` | One Git or host operation each (`fetch`, `pull`, `push`, ...), and the shared parts under `_names`: the one subprocess runner, discovery, facts. |
| `Special/` | This machine, once: enrollment and the observer (`_sync`), archives, org copy, security, history, settings. |
| `Elaborate/` | Across machines and over time: the peer and its network, transports, requests, recovery. |
| `App/` | The tray, the web server and the page (`_web/skins/standard`). |
| `_os/` | What differs per operating system, behind one name each. |
| `_build/` | Setup, the walkthrough, packaging, generated documents. |
| `tests/` | The offline suite, by area. `uv run python tests/run_all.py` runs all of it. |
| `docs/` | For people using it. `STATUS.md` is what works today. |
| `.agents/knowledge/` | Decisions and findings, one topic per file; `history/` holds what is no longer current. |

A layer imports only layers below it (Basic, then Special, then Elaborate, then App);
`tests/repo/test_import_direction.py` enforces it, and a command never imports a sibling
command. The launcher `gitso.py` is the front door and is imported by nothing in the stack.

## Validation

```sh
uv run python tests/run_all.py
```

Every test is synthetic: no network, no real repository, never the real app or its settings.
`tests/repo/test_repo_hygiene.py` guards this public repository against private values;
`tests/repo/test_command_docs.py` fails when `docs/COMMANDS.md` is stale
(`python _build/command_docs.py --write` regenerates it). Do not run live GitHub duplication,
archive refreshes or scheduled-task changes as validation unless the user asks.

A test that inspects source text proves a convention. A guarantee (never forced, never outside
the library, only the chosen copy) needs a test that runs the behaviour, with hostile input.

## Style

Prefer boring, visible, local behaviour: direct script calls, explicit output folders, progress
for long work, a plan before anything changes. Avoid hidden background behaviour, broad
filesystem traversal, clever packaging and surprising cleanup.
