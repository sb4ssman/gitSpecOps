# Architecture: the layer stack

**Status:** target agreed 2026-09-20; migration not started. How to get there is in
[`../HANDOFF.md`](../HANDOFF.md). The picture is [`architecture-diagram.md`](architecture-diagram.md).
[`../README.md`](../README.md) "Repo Shape" describes what is on disk *today* until the migration lands.

## The model

`git` is the raw material, and authentication is assumed: the user's own `git` and `gh` are
already set up, and nothing here stores, configures or asks for a credential. Everything is built
downward from there, becoming more elaborate as it builds on the basic operations.

| Layer | What it *is* | What it adds |
|---|---|---|
| **Basic** | one git or host operation | **care**: always a timeout, never interactive, structured results, no `--force` available |
| **Special** | a Basic operation repeated, with the logic of the repetition | **judgment**: which qualify, what to skip, what to collect and report |
| **Elaborate** | wider scale, built on Basic and Special | **reach**: across machines, and across time |
| **App** | all of it, assembled for a human | **presence**: it lives in the tray, if the user lets it |

Clarifications that took several passes to get right, recorded so they are not re-derived:

- **Basic is one operation.** It touches one repository only because that is what a single git
  command touches. The definition is the operation count, not the scope.
- **Special is not "many repos."** A loop running `pull` fifty times is not a Special operation.
  What makes `archive_update` special is the logic of the repetition. That judgment is the layer.
- **Elaborate reaches across machines *and across time*.** `archive_manage` belongs here because it
  keeps a registry and runs operations **on a schedule**. That is also why scheduled runs may never
  emit `--reconcile` or `--rename-folders`: an Elaborate operation can fire while you are asleep.
- **App is optional, and it is mostly the tray.** Every operation runs from the terminal on its
  own, forever. The App adds presence, not capability, and nothing may come to depend on it. The
  best thing it does is **suggest sync**.

## The rules

- **A file without an underscore is a command. A file or folder with one is plumbing.** `ls` on
  any layer lists exactly what it can do.
- **Every command is also an ordinary importable module**, runnable by its path from anywhere.
  Higher layers call lower ones with a normal `import`. The only subprocesses are calls out to
  `git` and the host CLIs themselves. Imports behave identically on every operating system;
  interpreter discovery, argument quoting and stdout encoding across a subprocess boundary do not.
- **A layer builds only on the layers above it** in the diagram (Basic → Special → Elaborate → App):
  never sideways, never on what comes after. Enforced by a test that reads the imports.
- **Plain names: lowercase words joined by underscores.** No hyphens anywhere.
- **Plain scripts, not a package.** No installation step and no console-script entry points.

## The shape on disk

```
gitSpecOps/
├── .agents/                    brief, notes, work log, knowledge, diagrams
├── _build/                     PyInstaller recipe, release gate, build notes
├── _docs/                      FLEET, DISPLAY-CONTRACT, RECOVERY-DESIGN
├── _tests/                     App/ Basic/ Elaborate/ Special/ probes/ repo/  run_all.py
├── App/                        optional, and mostly the tray
│   ├── skins/
│   │   ├── lcars/              placeholder at first
│   │   ├── modern/             today's dashboard
│   │   ├── retro/              placeholder at first
│   │   └── _assets.py          serves skin files by exact name
│   ├── tray/
│   │   └── tray.py
│   ├── autostart.py            registry Run key / XDG autostart / LaunchAgent
│   ├── dashboard.py            the loopback dashboard
│   ├── desktop.py              packaged-app entry
│   ├── git_client.py           open a checkout in a desktop Git client
│   ├── setup_fleet.py          guided first run
│   └── version.py
├── Basic/                      one git or host operation, wrapped with care
│   ├── git/
│   │   ├── clone.py
│   │   ├── fetch.py
│   │   ├── pull.py             fast-forward only
│   │   ├── push.py             never --force
│   │   └── status.py
│   ├── providers/
│   │   ├── _registry.py        the Protocol, register, provider_for
│   │   └── github.py           one module per host
│   ├── _console.py
│   ├── _discovery.py
│   ├── _facts.py
│   ├── _identity.py
│   ├── _paths.py
│   └── _run.py                 the one subprocess wrapper
├── Elaborate/                  wider scale: across machines, across time
│   ├── _fleet/                 advice, aggregate, config, display, events, manifest,
│   │                           net, observer, store
│   ├── _transport/             folder, repo
│   ├── recovery/               one operation, with details
│   │   ├── acknowledge.py  policy.py  preview.py  restore.py  retire.py
│   │   └── _capture  _patch_parse  _retirement  _runtime  _secret_scan  _snapshot_store …
│   ├── _editors.py
│   ├── alias.py
│   ├── archive_manage.py       registry, launchers, schedule
│   ├── audit.py
│   ├── baskets.py
│   ├── catchup.py
│   ├── check.py                observe, publish, show: once
│   ├── converge.py
│   ├── doctor.py
│   ├── live_buffers.py
│   ├── materialize.py
│   ├── peer.py                 observe, publish, show: continuously
│   ├── preflight.py
│   └── safe_to_wipe.py
├── Special/                    a Basic operation repeated, with judgment
│   ├── duplicate_org/          one operation, with details
│   │   ├── duplicate_org.py
│   │   └── _batch  _local_repos  _operations  _tracking
│   ├── _archive_plan.py
│   ├── archive_sync.py         keeps --publish as its own apply class
│   └── archive_update.py
├── AGENTS.md  CLAUDE.md  LICENSE  README.md  pyproject.toml
└── run_setup.bat .ps1 .sh      setup_gitspecops.py
```

## Providers: the one seam

Host-awareness lives in exactly one place: `Basic/providers/`. This is the seam the repository
already had (`shared/providers.py`: a `RemoteProvider` Protocol with `list_repos` and `resolve`,
a host → provider registry, and graceful degradation to host-agnostic behavior when no provider
matches). The migration moves it into the stack. It does not redesign it.

- **Adding a host is one module and one `register_provider()` line.** GitLab is `gitlab.py`.
- **Providers register where they live.** The old facade (`remote_provider.py`) and the
  tool-side registration dance (`_register_providers()`) existed only because `shared/` could not
  import tool folders. In the stack that constraint is gone, and so are they.
- **Providers, not "plugins" and not "APIs."** Nothing is discovered or loaded dynamically, so
  they are not plugins. `plain-git` has no API at all and GitHub is reached through the `gh` CLI as
  much as through HTTP, so "API" is too narrow. *Earlier drafts of this document proposed
  `plugins-remote/` and `plugins-local/` folders with contract files, loaders and hyphenated
  un-importable names. Dropped on 2026-09-20: the provider seam already existed and did the job,
  and the hyphen "protection" was bypassable by `importlib` anyway. Do not reintroduce it.*

Use the same Protocol-and-registry pattern for anything else that genuinely gains a second
implementation, such as a second editor alongside VS Code. Until then it is one module.

## Operating systems

Windows, Linux and macOS are peers. A per-OS mechanism lives **inside the module that needs it**,
behind one function: `autostart.py` over the registry Run key, XDG autostart and LaunchAgent;
`tray/` over the platform tray; `_fleet/events` over `ReadDirectoryChangesW` and inotify. **No
caller ever branches on OS.** If a component grows several per-OS files, they sit beside it as
plumbing (`App/tray/_windows.py`). There is no global per-OS folder.

## Skins

Three ship: **lcars, modern, retro.** `modern` is today's dashboard; `retro` and `lcars` start as
placeholders. Every skin consumes the versioned display contract
(`_docs/DISPLAY-CONTRACT.md`) and refuses a version it does not recognize. None reimplements Git
or freshness policy. The contract's builder lives in `Elaborate/_fleet/`, not in `App/`, because
deciding what needs attention is policy and the App holds none.

## Sync Suggester: one job, run two ways

`check` observes this machine's repositories, publishes its status, and shows the fleet: once.
`peer` does the same job continuously. **One configuration and one observation code path serve
both.** The earlier second runtime is dissolved rather than carried: `watch` (polling) is gone
because the peer's file events replace it; `init` folds into `setup_fleet`; the terminal
`dashboard` becomes `check` without observing; the reserved `handoff` stub is removed.

## Every operation declares its effect

The layer says what an operation is built from. It does not say what the operation *does to your
repositories*, and leaving that to prose is how a Git tool once came to be documented as never
touching Git. So each operation declares one module-level field:

**`EFFECT = "none" | "local" | "remote"`**, where **`none` means nothing you would have to undo.**

`git fetch` writes into `.git/`, yet no branch of yours moves and no file you authored changes.
It is `none`, which is exactly why the background peer may run it. The peer writing its own
manifests and logs is `none` too: that is the tool's bookkeeping, not your repository.

A test collects every declaration by scanning the layer folders and asserts the rule that matters:

> Everything reachable from the peer, tray, dashboard or scheduler is `EFFECT = "none"`.

## Sequencing: this precedes enrolling machines

`autostart` writes an **absolute resolved path** to the peer into the registry Run key, the XDG
`.desktop` file and the LaunchAgent. Moving files after enrollment breaks start-at-login on every
machine, silently. Migrate first, then enroll onto the final layout.
