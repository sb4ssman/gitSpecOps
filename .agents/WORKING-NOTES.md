# Working notes

Open work only. When something is done, record it at the bottom of [`WORK-LOG.md`](WORK-LOG.md)
(`## YYYY-MM-DD HH:MM - <user> (<agent>) - <title>`) and delete it here. Dates are absolute.
Verify an item against the code before acting on it.

_Last tended: 2026-11-17. Pruned to open work; what was done is in the log entries of that day.
What works today, per capability, is in [`docs/STATUS.md`](../docs/STATUS.md)._

## Handoff, 2026-11-17 (from the agent that worked 2026-11-14 to 17)

The user has run `gitso update` on four machines and glanced at the page. **Nothing built on
2026-11-17 has been tested by a person.** Every Python operation behind the page has tests (113
files pass); the page's own scripts have none, and no new button has been clicked through.

**What the user wants, in his words:** "the app needs to be the conduit to the special
operations". Every view is a slice of the same rows and must be able to act. The scripts are
the product; the page and the tray are faces on the same functions (`docs/ONE-OPERATION.md`).
Remote management: see work on a machine, act on it from any machine.

**Built 2026-11-17, untested by a person, most likely to need fixes:**
- `App/_web/skins/standard/fleet_actions.js`: fast-forward / clone bars on the map's levels,
  Machines cards and Reference. Requests now run on arrival (`auto_requests`, default on).
- Reference's Use it form; `run-command` in `Special/_sync/resolve.py` opens a terminal with a
  catalog command in a folder this machine knows (Windows `cmd /k`; macOS a `.command` file;
  Linux the first terminal found). Only Windows was exercised, and only by a mocked test.
- The Resolve box (commit, push, safe to delete, copy chooser, not counted), Accept and Not a
  secret on audit findings, "On my other devices", the map's repository boxes.
- `X-GitSpecOps-Page`: an open tab reloads when the app's page files change.

**Screenshots:** the README's images predate the menu tiles, Reference and the buttons. Retake
them from the demo fleet (`_build/demo_fleet.py`, port 8799: invented machines and
repositories), never from the user's real fleet, and ask before capturing any real screen. The
user wants to reuse one of them on his two sites, so make one wide image of the map and one of
Reference worth showing.

**Open from the outside review:** listed below under "From the outside review".

## Next, in order
The missing-library fallback is covered with disposable repositories on Windows. Confirm the
dashboard and `fleet doctor` during the next real Linux mount outage and after remounting.

1. **A person's pass over the page's new buttons** (2026-11-17): Resolve (open, changes, commit,
   push, safe to delete, not counted), the copy chooser, Accept and Not a secret, Reference,
   "On my other devices", requests running on arrival between two real machines. The Python
   behind each is tested; no button has been clicked through.
2. **Merge `dev` to `main`** when the user says.
3. **Publish the shelf** (visibility is the user's call).

## From the outside review (knowledge/external-review-2026-11-17.md), still open
- **Split the two largest files:** `Elaborate/_fleet/cli.py` (about 1,000 lines) and
  `_build/setup_walkthrough.py` (about 1,650). Move `PeerNetwork` and `TransportPublisher` out of
  `peer.py`; tests patch `local_identity` and `fetch_peer_report` by that module's name, so the
  patches move with them.
- **Recovery:** its own subprocess runners (use Basic's, which needs binary stdin there) and its
  own secret rules (`Elaborate/_recovery/secret_scan.py` skips binary patches and differs from
  the shared scanner). The hygiene test's patterns are a third set.
- **Org copy, cleaning in one step:** today a held repository's clone is kept and the person is
  pointed at `gitso history clean`; the flow does not yet run the clean and upload the result.
  Also: a useful dry run, choosing single repositories, the station style for its menu.
- **Browser tests for the page's scripts.** None exist; a button wired to the wrong action is
  caught only by a person.
- **An attention queue:** one sorted table answering "what needs me, where, why, what can I
  safely do next", as the fastest route from the page to work.
- **Label every count** on the page as repositories, copies, machines or findings.
- **Keyboard, focus, contrast and narrow screens:** never reviewed.
- **Malformed peer records, interrupted operations, names that need Git's quoting:** failure
  tests not written yet.
- **`auto_requests` has no switch in Settings**; it is a key in the app's settings (default on).

## Waiting on the user
- **Screenshots to retake on the user's screen** (redact user and computer): the setup menu
  (changed 2026-11-15); the org copy screenshot; the page since Reference was added.
- **Old archive registrations:** the registry is empty. The pre-shared-settings registry
  (`old-settings.json` in the settings folder) still lists three archive folders. Register an
  archive again with `gitso archive add <folder>` if wanted.
- **The state repository, before first use:** how a repository-only machine proves it is alive
  (it reads as not reporting after about an hour of quiet); the "scribe" idea (one machine on
  Tailscale commits every online machine's state at once); removing a machine's file when it
  leaves.
- **The folder mapper:** `.agents/tools/README.md` fetches it from a repository that now
  redirects to a private one (checked 2026-11-14), so a fresh machine cannot fetch it.
- **Whether a machine's own map view may show real library paths** (kept private for now).
- **Packaging and distribution** (ruling 2026-11-15): clone plus setup stays for now. A package
  (pipx, PyPI or a release download) needs one package layout first; see the 2026-11-14 log.
- **Code signing** for release builds. **A GUI installer**, eventually.
- **Tailscale names for the other-devices view** (2026-11-17; the user: not yet). The view
  answers only to the numeric address. Accepting this machine's own `<name>.<tailnet>.ts.net`
  would read better, and with Tailscale's HTTPS certificates would get a padlock; certificate
  names are written to public logs, so machine names become public. If built: accept exactly
  this machine's own name, nothing else.

## The user's view of the fleet (to design with him, then build)
- **Repositories as repositories** (decided 2026-11-16): absorb every source of truth and
  compare them: what is on the machines, what the account has on GitHub (owned, organization
  member, collaborator, forks, contributed-to; via `gh`, read-only), and which local
  repositories hold the user's own commits; the differences are the findings. Perspectives with
  their issues and actions: Needs me, Out of sync, At risk, Publishing, Age, Coverage.
  Statistics: repositories touched, own commits per repository, first and last commit.
- **The master list and the network library:** every repository he contributes to or collects,
  in one list; a complete library on a networked machine with a large drive; tick
  organization folders onto or off each machine. Builds on materialize and safe-to-wipe.
- **The explorer map** (built 2026-11-17): still to be looked at critically with the user.
  The overview's machine-to-machine link labels can overlap under the machine boxes.
- **Run an operation from Reference:** today it is reading only. Each operation with its plan
  and approval, from the page.
- **Windows checkouts read from Linux on a dual-boot machine:** Git on Linux sees every line
  ending as a change. Either `core.autocrlf=true` there, or gitSpecOps reporting "line endings
  only" as its own state instead of "dirty" (the uncommitted-work summary already says so).

## Not built yet
- **The gitso alias in a synced profile** (found 2026-11-15): on Windows the PowerShell profile
  can live in a synced Documents folder. The alias is a function with this machine's absolute
  paths and wins over the launcher on PATH, so another PC would run a path that is not there.
  Setup should notice a profile under a synced folder and recommend the PATH launcher alone.
- The Qt window (`App/window.py` is a placeholder; the page is the full view).
- Attended commit and push on another machine (`Elaborate/request.py` and
  `history_follow_fleet.py` are placeholders; the design is in the brief, rule 2).
- Ordinary Git in the app: log, branch switch, stash.
- Designs only: handing work between machines (`knowledge/handoff-design.md`), at-risk work
  (`knowledge/at-risk-work.md`).
- Older Macs: confirm the menu-bar icon starts at sign-in and stops with `gitso tray --stop`.
  `gh` keeps its token in the login keychain, which an SSH session cannot read: restart the app
  at the Mac itself.

## Needs proof on real machines
- Status through a synced folder and through a private repository, between two machines.
- Archive scheduling on Linux and macOS.
- Inventory export and restore across machines; recovery across two machines.
- betterleaks and trufflehog as real programs (their adapters are tested with stand-ins).
- History cleanup on a real repository, then following or relinking clones.
- A test that runs the peer under `pythonw.exe` on Windows CI (the tray's real conditions).

## Tests
- `security/test_commit_gate.py` failed once under heavy parallel load (2026-11-13 and
  2026-11-14, 12 test processes at once). The failure text was not kept; if it recurs, keep it.
- `special/test_scope_proofs.py`'s link test is skipped where links cannot be made (Windows
  without the privilege); it runs on Linux and macOS CI.

## Notes to bring up to date
- `knowledge/settings-schema.md`, and parts of `product-contract.md` and
  `architecture-layers.md`, still describe settings migration and files removed on 2026-11-13.
- `knowledge/handoff-design.md` links a section of the brief that is now in
  `knowledge/history/`.
