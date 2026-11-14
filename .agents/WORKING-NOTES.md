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
- **Merge, in order:** PR #1 basic-and-secure-commands, #2 remove-legacy, #3 readme-docs,
  #4 polish, #5 command-names; then the cleanup wave (branch wave/cleanup).
- **His three archive launchers** were made before the shared settings and the command renames;
  they run files that no longer exist. Regenerate each with `gitso archive add <folder>`.
- **Protected values:** copy them back from `settings.json.before-first-run` after the first-run
  test. Its old `output.mode`/`output.format` keys no longer exist (now `{save, directory}`).
- **The state repository, before first use:** how a repository-only machine proves it is alive
  (it reads as not reporting after about an hour of quiet); the user's "scribe" idea (one
  machine on Tailscale commits every online machine's state at once); removing a machine's file
  when it leaves.
- **The folder mapper:** `.agents/tools/README.md` fetches it from `sb4ssman/PythonTools`, which
  now redirects to a private repository (checked 2026-11-14), so a fresh machine cannot fetch it.
- **Whether a machine's own map view may show real library paths** (kept private for now).
- **One-command install** (`pipx install`): needs a package layout first; see the 2026-11-14 log.
- **Code signing** for release builds.

## Not built yet
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
  2026-11-13. `.agents/README.md`'s Sync Suggester sections predate the layer move.
