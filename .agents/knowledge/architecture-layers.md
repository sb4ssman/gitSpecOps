# Architecture: the layer stack

**Status:** shape agreed 2026-09-20, migration not started. This is the **target**.
[`../README.md`](../README.md) "Repo Shape" still describes what is on disk today; update it as
each phase lands.

## The model

Everything here is **git Special Operations**. The layers are about **composition** — what an
operation is built out of — not about difficulty, and not about how many repositories it touches.

| Layer | What it *is* | What it adds |
|---|---|---|
| **Basic** | one git or remote operation | **care** — a timeout always, forced non-interactive, structured results, no `--force` available |
| **Special** | a Basic operation repeated, with the logic of the repetition | **judgment** — which qualify, what to skip, collect failures, report at the end |
| **Elaborate** | wider scale, calling Basic and Special | **reach** — across machines, and across time |
| **App** | all of it, assembled | **presence** — it is in your tray |

Three clarifications that took several passes to get right, recorded so they are not re-derived:

- **Basic is one operation.** It is scoped to a single repository only because that is what a
  single git command necessarily touches. The definition is the operation count, not the scope.
- **Special is not "many repos."** A shell loop running `pull` fifty times is not a Special
  operation. What makes `archive-update` special is the *logic of the repetition* — which repos
  qualify, approved remote, clean tree only, skip the rest, collect failures, report. That
  judgment is the layer.
- **Elaborate reaches across machines *and across time*.** `archive-manage` belongs here despite
  touching one machine, because it keeps a registry, installs launchers, and runs operations **on
  a schedule**. That is also exactly why the rule exists that scheduled runs may never emit
  `--reconcile` or `--rename-folders`: an Elaborate operation can fire while you are asleep.

### The one rule

> A layer may call only layers below it. Never sideways into a sibling, never upward.
> Enforced by a test that reads the imports, not by good intentions.

Composition is therefore the only mechanism, and the stack holds itself up.

## Three kinds of file

| Kind | Looks like | Who touches it |
|---|---|---|
| **operation** | `fetch.py` | you run it; it declares its effect |
| **plumbing** | `_run.py` | its own layer imports it |
| **plugin** | `plugins-remote/github/` | nobody imports it — it is *loaded* |

An operation that needs several modules gets a folder of its own name instead of a file.

**The hyphen does real work.** `import plugins-remote` is a syntax error, so no layer can
accidentally depend on a plugin implementation. Plugins are discovered and loaded by path. The
naming convention enforces the architecture for free.

## The shape on disk

Listed as the filesystem shows it — **alphabetical, folders before files** — because that is how
it will actually be read:

```
gitSpecOps/
├── .agents/              brief, working notes, work log, knowledge
│
├── App/                  the thing in your tray
│     skins/
│       lcars/  modern/  retro/
│       CONTRACT.md
│     _contract.py
│     autostart  cli  dashboard  peer  tray
│
├── Basic/                ONE operation, wrapped with care
│     git/     clone  fetch  pull  push  revs  status
│     remote/  repo-create  repo-list  repo-rename  repo-view
│               _contract.py   (the interface + loader; host-blind)
│     _console  _discovery  _facts  _identity  _paths  _run
│
├── build/                PyInstaller recipe, release gate, build notes
├── docs/                 FLEET, RECOVERY-DESIGN, user-facing guides
│
├── Elaborate/            WIDER SCALE — across machines, across time
│     archive-manage  at-risk  capture  catchup  materialize
│     observe  restore  retire
│     _fleet  _manifest  _transport
│
├── plugins-local/        what is on THIS machine — selected by detection, never configured
│     editors/       vscode/  …
│     git-clients/   github-desktop/  sourcetree/  …
│     platform/      linux/  macos/  windows/
│     CONTRACT.md
│
├── plugins-remote/       which host — selected by the remote's URL
│     gitea/  github/  gitlab/  plain-git/
│     CONTRACT.md
│
├── Special/              a Basic operation REPEATED, with the logic of the repetition
│     duplicate-org/
│     archive-sync  archive-update  publish
│
└── tests/                mirrors the stack
      App/  Basic/  Elaborate/  Special/  probes/  repo/
```

**Alphabetical order is not dependency order.** On disk it reads App, Basic, Elaborate, Special;
the stack is Basic → Special → Elaborate → App. The filesystem cannot show the stack, so the
documentation and the import test are what carry it. Do not infer layering from the folder list.

## Three seams, one shape

Each seam swaps an implementation and keeps a contract. This is what makes "agnostic" real in
every direction at once, and it is why **cross-platform works from the beginning** rather than
arriving as a porting effort: the OS is a seam like the others, not a special case.

| Seam | Swaps | Selected by | Contract |
|---|---|---|---|
| **remote** | which host | the remote URL's host | `plugins-remote/CONTRACT.md` |
| **local** | editors, desktop git clients, OS mechanisms | detection | `plugins-local/CONTRACT.md` |
| **skin** | which look | the user | `App/skins/CONTRACT.md` |

None of the three is configured by hand where detection can answer it: a host is known from the
URL, an OS from the platform, an installed editor from its presence. The skin is the one genuine
user choice.

`plugins-local/platform/` is where "one command, three mechanisms" becomes structural. Today
`autostart` spans a registry Run key, an XDG autostart file and a LaunchAgent; watching spans
`ReadDirectoryChangesW` and inotify. Adding macOS should mean adding a folder, never editing
branches spread through the stack. **No caller above ever branches on OS.**

### The loader split (get this right early)

A hyphenated folder cannot be imported — which is the property we want — but a contract is code,
so something must define it:

- **`Basic/remote/_contract.py`** — the interface every remote plugin implements, plus the
  loader. In the stack, importable, and host-blind: it names no host.
- **`plugins-remote/github/`** — an implementation. Imported by nobody; loaded by path.
- **`plugins-remote/CONTRACT.md`** — the human-readable spec, sitting where a plugin author looks.

The same split applies to `App/skins/`, though it bites less: a skin is mostly HTML/CSS/JS served
by exact name rather than imported at all. The display contract already exists and already
anticipates this — `gitspecops.fleet.display` is versioned, one module is permitted to turn state
into display semantics, and every skin (**including LCARS**) must consume it and must never
reimplement Git or freshness policy. It becomes `App/skins/CONTRACT.md`; today's dashboard becomes
`App/skins/modern/`.

## Every operation declares its effect

The layer says what an operation is composed of. It does not say what the operation *does to your
repositories* — and leaving that to prose is precisely how a Git tool came to be documented as
never touching Git. So each operation declares one field:

**`effect: none | local | remote`**, where **`none` means nothing you would have to undo.**

`git fetch` writes into `.git/` — remote-tracking refs, objects — yet no branch of yours moves and
no file you authored changes. Run it a thousand times by accident and there is nothing to recover.
So fetch is `none`, and that is exactly why the observing side is allowed to do it. The peer
writing its own manifests, logs and caches is `none` too: that is the tool's bookkeeping, not your
repository.

Avoid the word "mutating" in prose — it is ambiguous between *an operation whose behavior varies
with input* and *an operation that changes its target*. Write what is true instead: "this
operation has no effect on your repositories."

One rule then covers the whole background-app risk, and it is a test rather than a paragraph:

> Everything reachable from the peer, tray, dashboard or scheduler must be `effect: none`.

## Migration, in phases that each end green

1. **`Basic/`.** Collapse the two independently-evolved git subprocess wrappers
   (`shared/git_facts.run_git`, `gh_common.run_command`) into one careful `_run`. Move console,
   paths, atomic writes, facts, discovery, identity. Existing tool folders import downward; none
   of them move yet. Highest value, lowest risk, repays immediately in deleted duplication.
2. **`Basic/remote/` + `plugins-remote/`.** Define the contract and the loader; move `gh_cli`,
   `remote_provider`, `provider_github`, and the duplicator's `gh` calls. Add the import-direction
   test here — this is the boundary worth the most.
3. **`Special/` and `Elaborate/`.** Move the operations, drop the `git-` prefixes, split
   `archive_diff` (generic classification down to Basic, archive policy stays). Update
   `LAUNCHER_SPECS`, `_paths.py`, `tests/_bootstrap.py`, and every path in the docs.
4. **`App/`, `App/skins/`, `plugins-local/`, `build/`, `docs/`.**
5. **Effect declarations and the invariant tests.**

## Sequencing: this precedes enrolling machines

`fleet_autostart.py` writes an **absolute resolved path** to the peer entry point into the Windows
registry Run key, the XDG `.desktop` file, and the LaunchAgent. Moving files after enrollment
breaks start-at-login on every machine — *silently*: the app simply stops coming back after a
reboot, the worst failure mode for a tool whose whole job is noticing things.

Migrate first, enroll onto the final layout.

## Open

- `plugins-local/`'s internal split (editors / git-clients / platform) is proposed, not settled.
- Whether `plugins-local/platform/` absorbs the tray implementations themselves, or only the
  autostart and filesystem-watch mechanisms, since a tray must live on the main thread and owns
  the Win32 message loop.
