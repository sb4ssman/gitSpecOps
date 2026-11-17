# Working notes

Open work only. When something is done, record it at the bottom of [`WORK-LOG.md`](WORK-LOG.md)
(`## YYYY-MM-DD HH:MM - <user> (<agent>) - <title>`) and delete it here. Dates are absolute.
Verify an item against the code before acting on it.

_Last tended: 2026-11-14. Pruned to open work; what was done is in the log entry of the same day._

## The mission, in order (the user, 2026-11-14)
1. **A working install on the user's main Windows machine.** The user's first-run test of
   setup, with the real settings file set aside (`settings.json.before-first-run`). Not yet seen
   in use: the walkthrough's Archives part, the web setup page's plan box, `gitso <subject>
   <action>`.
2. **Point it at the user's shelf organization:** a gitleaks scan, then review the findings.
   gitSpecOps never installs a scanner; the user installs gitleaks.
3. **Then the user's other three machines** (a second Windows machine, a Debian desktop, an
   iMac), and the fleet over Tailscale between them. Machine names stay out of this public
   repository (the hygiene test treats them as private).
4. **Publish the shelf** (visibility is the user's call). The fleet's state repository stays
   marked "experimental, untested".

## Waiting on the user
- **Merge PR #7** (wave/setup-protection). PRs #1 to #6 were merged 2026-11-15.
- **Screenshots to retake on the user's screen** (redact user and computer): `docs/images/setup-menu.png`
  shows the old setup menu (the menu changed 2026-11-15); the org copy screenshot.
- **Old archive registrations:** the current registry is empty. The pre-shared-settings registry
  (`old-settings.json` in the settings folder) still lists three archive folders; only one had a
  launcher file, and it was removed 2026-11-14 at the user's request. Register an archive again
  with `gitso archive add <folder>` if wanted.
- **Protected values:** copy them back from `settings.json.before-first-run` after the first-run
  test. Its old `output.mode`/`output.format` keys no longer exist (now `{save, directory}`).
- **The state repository, before first use:** how a repository-only machine proves it is alive
  (it reads as not reporting after about an hour of quiet); the user's "scribe" idea (one
  machine on Tailscale commits every online machine's state at once); removing a machine's file
  when it leaves.
- **The folder mapper:** `.agents/tools/README.md` fetches it from `sb4ssman/PythonTools`, which
  now redirects to a private repository (checked 2026-11-14), so a fresh machine cannot fetch it.
- **Whether a machine's own map view may show real library paths** (kept private for now).
- **Packaging and distribution** (ruling 2026-11-15): clone plus setup stays for now. A more
  professional package and distribution (pipx, PyPI or a release download) stays under
  consideration; any of them needs one package layout first; see the 2026-11-14 log.
- **The shelf lists gitSpecOps as an outside entry** (ruling 2026-11-15); the repository stays
  at its own home. Recording it is the shelf's job, not this repository's.
- **Code signing** for release builds.
- **A GUI installer app, eventually** (the user, 2026-11-16): setup as a window, for people who
  will not open a terminal. Today: the terminal walkthrough, then the App & setup tab.

## Before the tray runs on any machine again (the 2026-11-15 window storm; see the work log)
- **Prove it on the user's machine first, watched:** start the tray with the window fix, a
  small library and the user present, and stop it at the first window that appears.
- **A test that runs the peer under pythonw.exe on Windows CI**, so the tray's real conditions
  are tested, not only a terminal's.

## The user's view of the fleet (raised 2026-11-15; to design with him, then build)
- **Organise by where things live:** in the app's Repositories tab, Security tab and network
  map, group by library folder, then the folder inside it (his org folders, and a folder holding
  other people's projects), then the repository; a switch between that hierarchy and the
  GitHub-owner grouping. Today other people's repositories each get their own owner group (many
  one-repository groups). `gitso machine
  check` already shows this hierarchy on screen (2026-11-15). Across machines it needs each
  report to carry the containing folder's name (a name, never a path): his decision, next to the
  open "real library paths" question above.
- **From the cloud down:** one picture from GitHub owners through machines and libraries down to
  each repository's state on every machine.
- **The master list and the network library:** every repository he contributes to or collects,
  in one list; a complete library on a networked machine with a large drive; tick
  org-level folders to put them on, or take them off, each machine. Builds on materialize
  (clone what is missing) and safe-to-wipe (prove a removal loses nothing).
- **The folder mapper as an optional view:** if Orbital-Workshop's mapper is present, an ASCII
  map of a library with each repository's state appended. gitSpecOps does not depend on it.
- **One inventory, not two:** `gitso machine check` and the app each read the library; the app
  could reuse a recent read instead of reading again at start. The user asked why, not for a
  change.

## Fleet sync (raised 2026-11-16)
- **Apply requests automatically, by choice:** a per-machine setting ("fast-forwards: apply
  automatically") so a request needs no one at that machine. Clones stay manual unless chosen.
- **The page after the 2026-11-16 rebuild** (menu tiles, shared grid; see the work log): the
  zoomable map's machine-to-machine link labels overlap under the machine boxes; the map's
  machine trees show organizations, not yet libraries; the map should one day show everything.
- **A customizable legend for the map** (raised 2026-11-16).
- **Repositories as repositories (decided 2026-11-16):** no place grouping on Repositories (node1
  showed three "library on machine" groups). Absorb every source of truth and compare them: what is
  on my machines, what my account has on GitHub (owned, org member, collaborator, forks,
  contributed-to, via `gh`, read-only), and which local repositories hold my own commits; the
  differences are the findings. Perspectives with their issues and resolving actions: Needs me,
  Out of sync, At risk, Publishing, Age, Coverage; statistics (repositories touched, my commits
  per repository, first and last commit). The same questions at every integration level.
- **The map as a focus-and-context explorer (raised 2026-11-16):** hover magnifies what is under
  the cursor (the rest fades, details appear), drag pans laterally when zoomed, chosen dimensions
  (place, ownership, state, time, sameness) set the layout and the perspective, jump straight to
  each issue and see how it differs elsewhere. Effectively 3D.
- **The Memory Gamma copies on the dual-boot machine** are Windows checkouts read from Linux: Git
  on Linux sees every line ending as a change. Either `core.autocrlf=true` in those repositories,
  or gitSpecOps reporting "line endings only" instead of "dirty".

## Older Macs (macOS 10.15): parked for completeness, not tonight's detour (2026-11-16)
- **Safari 15 has no CSS color-mix**: every tone colour on the page is missing there. Replace
  color-mix with precomputed colours, or a fallback.
- **A menu-bar icon without Qt:** a Swift prototype worked (`knowledge/macos-menubar-prototype.md`).
  Still needed: the real mark, start at sign-in, stop together with `gitso tray --stop`.
- **SSH and the keychain:** `gh` keeps its token in the login keychain, which an SSH session cannot
  read, and an app restarted by `gitso update` over SSH cannot either; restart it at the Mac
  itself. `gh auth setup-git` was needed so git uses `gh`'s sign-in.
- **Sign-in in old Safari:** GitHub's device page did not work in Safari 15; Chrome did.

## Not built yet
- **The gitso alias in a synced profile (found 2026-11-15):** on Windows the PowerShell profiles
  can live in OneDrive's Documents, which syncs to the user's other PCs. The alias is a function
  with this machine's absolute paths, and a PowerShell function wins over the `gitso` launcher on
  PATH, so on another PC `gitso` would run a path that is not there, and each PC's setup would
  rewrite the shared block. Setup should notice a profile under a synced folder and recommend
  the PATH launcher alone (it already works in cmd, PowerShell and Git Bash).
- Security tab: review a finding from the page (accept an example, as `gitso review` does).
- A menu of every command in the web view, through the same plans and safety checks.
- Updating gitSpecOps itself (fast-forward its own checkout, restart the app). Only a version
  check exists (`Basic/_version.py`).
- The Qt window (`App/window.py` is a placeholder; the web view is the full view).
- The attended remote-request protocol (`Elaborate/request.py` and `history_follow_fleet.py`
  are placeholders).
- Recovery's secret scan (`Elaborate/_recovery/secret_scan.py`) and the hygiene test's patterns
  (`tests/repo/_hygiene_patterns.py`) still use their own rules, not the shared security rules.
- `org copy`'s interactive menu is not in the station style yet (plain prints).
- Org copy: a useful dry run and choosing individual repositories.
- Ordinary Git in the app: diff, log, branch switch, stash.
- Designs only: handing work between machines (`knowledge/handoff-design.md`), at-risk work
  (`knowledge/at-risk-work.md`).

## Needs proof on real machines
- Linux and macOS: CI runs the suite on both; setup, the tray or menu bar, start at sign-in and
  archive scheduling have never run natively.
- The transports between real machines (folder, private repository, Tailscale), including
  offline and stale machines.
- Inventory export and restore across machines; recovery across peers.
- The optional scanners (Gitleaks 8, Betterleaks 1, TruffleHog 3) as real programs; their
  adapters are tested with stand-ins only.
- History cleanup on a real repository, and following or relinking clones after a rewrite.
  Coverage gaps stay reported as gaps: PDF, 7z/RAR, LFS content, submodules, oversized files.

## Tests
- `security/test_commit_gate.py` failed once under heavy parallel load (2026-11-13, and again
  2026-11-14 with 12 test processes at once). Alone and at 8 copies at once it passed 36 of 36.
  The failure text was not kept; if it recurs, keep the output: the masked result is printed.

## Notes to bring up to date
- `knowledge/settings-schema.md`, and parts of `product-contract.md` and
  `architecture-layers.md`, still describe settings migration and older files removed on
  2026-11-13. `.agents/README.md`'s Sync Suggester sections predate the layer move, and its smoke checks
  still name the old scripts (`update_archive.py`, `sync_archive.py`, `duplicate_org.py`).
