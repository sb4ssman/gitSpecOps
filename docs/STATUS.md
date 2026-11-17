# What works today

A factual table, kept current. Four separate questions per capability, because "built" is not
"proven":

- **Built**: the code exists and is reachable from `gitso` or the page.
- **Used**: the author has used it for real work on real repositories.
- **Tested**: automated tests cover it (the suite runs on Windows, macOS and Linux in CI).
- **Run natively on**: where a person has actually run it, as opposed to CI.

Last reviewed: 2026-11-17. The author's fleet is two Windows 11 machines, one machine that boots
either Debian or Windows, and an iMac on macOS 10.15.

## Operations

| Capability | Built | Used | Tested | Run natively on | Not yet |
|---|---|---|---|---|---|
| Basic Git operations (`discover`, `status`, `fetch`, `pull`, `clone`, `commit`, `push`, `reset-keep`) | yes | yes | yes, including push and pull under hostile Git configuration | Windows, Debian, macOS | |
| This machine: enroll libraries, `machine check`, `machine map`, catch-up | yes | yes | yes | Windows, Debian, macOS | |
| Safe-to-wipe audit (prove a machine holds nothing unique) | yes | not confirmed | yes | Windows | a real machine retirement |
| Clone what is missing into a library (`machine materialize`) | yes | yes | yes; the link-escape test needs link privileges and is skipped on Windows | Windows | |
| Archives: register, update, sync, publish | yes | yes | yes | Windows | scheduling on Linux and macOS |
| Org copy: download, upload, migrate | yes | yes (it is where the project started) | partly: local parts and the security hold; not the GitHub calls | Windows | the security question in real use; a dry run; choosing single repositories |
| Inventory export and restore | yes | not confirmed | yes | | across two real machines |

## Security

| Capability | Built | Used | Tested | Run natively on | Not yet |
|---|---|---|---|---|---|
| Scan working files; scan history | yes | yes | yes | Windows | |
| `secure-commit`, `secure-push` (plan, then apply by id) | yes | yes | yes, the largest tests in the suite | Windows | |
| Review one exact finding; protected values; shared across the fleet | yes | yes | yes | Windows, Debian, macOS | |
| Audit from the page, in its own process, with Stop | yes | yes | yes | Windows | |
| Optional scanners: gitleaks | yes | yes | adapter tested with a stand-in | Windows | |
| Optional scanners: betterleaks, trufflehog | yes | no | adapters tested with stand-ins only | | run as real programs |
| History cleanup into a new mirror; follow; relink | yes | no | yes | | a real repository, end to end |

Coverage gaps are reported as gaps, never as a pass: PDF, 7z and RAR contents, Git LFS payloads,
submodules, oversized files.

## The fleet

| Capability | Built | Used | Tested | Run natively on | Not yet |
|---|---|---|---|---|---|
| Machines report to each other over Tailscale | yes | yes, four machines | yes | Windows, Debian, macOS | |
| A machine that is off stays on the map with its last report; reports are relayed to newcomers | yes | yes | yes | Windows, Debian | |
| One machine, two systems (dual boot): the same disk is not counted twice | yes | yes | yes | Windows, Debian | |
| Status through a synced folder | yes | not confirmed | yes | | between two real machines |
| Status through a private repository | yes | no | yes | | between two real machines; marked experimental |
| Requests: fast-forward or clone on another machine, run on arrival | yes | the earlier form (approve there) was used; the run-on-arrival form is new | yes | | between two real machines |
| Ask another machine what is uncommitted (file names and line counts) | yes | yes | yes | Windows | |
| Recovery snapshots of unfinished work | yes | no | yes | | capture on one real machine, restore on another |
| Attended remote commit and push ("that machine, commit these files") | no | | | | designed, not built |

## The app

| Capability | Built | Used | Tested | Run natively on | Not yet |
|---|---|---|---|---|---|
| Tray icon (Qt) | yes | yes | yes | Windows, Debian | |
| Menu-bar icon without Qt (Swift, built on first run) | yes | yes | build and start only | macOS 10.15 | newer macOS |
| The page: map, repositories, organizations, machines, clouds, security, reference, settings | yes | yes | the Python that feeds it is tested; the page's own scripts have no browser tests | Windows, Debian, macOS | keyboard, contrast and narrow-screen review |
| Resolve from the page: open, changes, commit, push, safe to delete, not counted | yes | new on 2026-11-17 | the operations are tested, including one whole journey; the buttons have not been clicked through | | a person's pass over every button |
| The same page on your phone (read-only, your Tailscale devices) | yes | not confirmed | yes | | |
| Setup walkthrough; start at sign-in; `gitso update` | yes | yes | yes | Windows, Debian, macOS | |
| The app window (Qt) | no | | | | a placeholder; the page is the full view |
| A packaged release (installer, signing) | no | | | | clone and `setup` is the way in |

## What "duplicate an organization" copies

Org copy copies **Git content**: branches, tags and notes, and on a migration the repository's
visibility and description. It does **not** copy issues, pull requests, releases, wikis,
permissions, repository settings, secrets, or Git LFS payloads. It is a copy of the code and
its history, not a backup of the organization.
