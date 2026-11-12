<!-- DRAFT of the eventual README (2026-11-12). It describes the finished product, so parts
     are not built yet: see README.md for what works today, and .agents/WORKING-NOTES.md for
     what is left. Replace README.md with this once its promises are true. -->

# gitSpecOps

**Every copy of every Git repository you have, on every machine you own: seen, kept current,
protected and coordinated. From a tray icon, or from an AI agent.**

You have repositories on a laptop, a desktop, a server, maybe an old machine in a closet. Some
have work you never pushed. Some are behind. Some exist on one machine only. Some contain a
value that must never be published. gitSpecOps knows, shows you on one map, keeps what is safe
current by itself, and asks you one clear question about the rest.

It sits beside tools like GitHub Desktop and SourceTree. They work *deeply* in one repository;
gitSpecOps works *broadly*, across all of them and all your machines, and opens any repository
in your desktop client when you want to go deep.

---

## Install

Download the app for your system from the [releases page](../../releases), run it, and follow
the first-run screen. That is the whole installation:

- **Windows, macOS, Linux.** One download each. No Python, no terminal, no administrator rights.
- **It updates itself** (see [Updates](#updates)), with your consent, and can roll back.
- **It installs `gitso`** on your command path: the same app, for scripts and AI agents.
- **Requires Git.** Everything else is optional and only for the features that need it:
  the GitHub CLI (`gh`), Tailscale, a file-sync client, a secret scanner.

## The tray

One icon, one colour, one meaning:

| Colour | Means |
|---|---|
| Green | The app and every repository it can safely keep current are current. |
| Amber | Something waits for one decision from you. |
| Red | Something is wrong; the tooltip says what. |

Double-click opens the app's face: a window, or the same view in your browser (your choice).
Right-click for rescan, catch-up preview, start at login, updates and quit.

## The map

Your machines and the copies they hold. Copies of the same repository line up across
machines, so "ahead here, behind there, missing on that one" is visible at a glance. Switch
views to shift focus:

- **Machines together**: who holds what, and how many copies they share or disagree on.
- **Libraries**: each machine's library folders, by organization.
- **One organization** across every machine.
- **One repository** across every machine: branch, commit, uncommitted work, on each.

Choose any machine as the point of view, and the rest are read against it.
Anything that needs you appears as a plan: what would happen, then "confirm?".

## Grow as you go

gitSpecOps is useful the moment it is installed, and every step you add multiplies what came
before: a fleet of four machines turns "see my repositories" into "see every copy, on all four,
even the ones switched off".

| | **Installed** | **+ This machine** | **+ A fleet** | **+ A managed repository** | **+ Tailscale** |
|---|---|---|---|---|---|
| **What you add** | nothing | your library folders | a fleet key and a way to share | a private GitHub repo gitSpecOps manages | your own tailnet |
| **See** | any folder you name | always on, live, a map of this machine | every machine on one map | machines that are off still appear | live, and from your phone |
| **Keep current** | fetch and safe fast-forward on request | automatically, with your consent | know where work is unpushed; clone what is missing | | |
| **Protect** | scans, checked commit and push, history cleanup | findings on the map | every machine's repositories audited | one privacy policy everywhere | |
| **Coordinate** | | | | ask another machine to act; it does when it next wakes | ask live, approve, watch it happen |
| **Agents can** | work on folders | work on this machine | observe the whole fleet | queue work for any machine | act live, with you watching |

Ways to share between machines, use any or all:

- **A synced folder** (OneDrive, Dropbox, Syncthing, a network share): fast, no account.
- **A managed repository**: a private GitHub repository that gitSpecOps creates or adopts, used
  for status that survives every machine being off, your shared privacy policy, and each
  machine's inbox of requests. Never cloned; never holds source code.
- **Tailscale**: machines talk directly, live; your phone can watch, and act on previews.

## Protect

Publishing a repository publishes its whole history, not just today's files. gitSpecOps checks
before anything leaves:

- **Scans** the working tree, the staged bytes, or the full history, with built-in checks and,
  if you have them, Gitleaks, Betterleaks or TruffleHog.
- **Checked commit and push.** A commit carries exactly the files you named; a push sends exactly
  the planned commits. Both are blocked by a secret, a value on your never-publish list, or an
  unreviewed binary.
- **Reviews.** Accept one finding at one exact place, once; it is not a blanket exception.
- **History cleanup.** Rewrite history into a new private copy, prove what changed, rescan, and
  only then publish; afterwards every clone on every machine follows the new history and the
  commit ids quoted in your files are updated.
- **One never-publish list** for all your machines through the managed repository, with
  machine-only additions that never leave.

## For AI agents

`gitso` is the same app as the tray, built so an agent can work with your repositories as
safely as you can:

```sh
gitso suggest-sync --json          # this machine: what needs attention
gitso suggest-fleet-sync           # every machine
gitso scan-tree <repo> --json      # findings, masked
gitso commit <repo> <files> -m "…" # a plan with an id; nothing happens yet
gitso commit <repo> <files> -m "…" --apply --approve <plan id>
gitso docs <command>               # what a command reads, may change, and returns
```

- **Every command says what it does** before it does it: what it reads, what it may change,
  where results go. An agent reads that instead of guessing.
- **Plans, then approval.** Anything that changes a repository first returns a plan with an id;
  applying requires that exact plan. A changed repository invalidates the plan.
- **The same gates as you.** An agent's commit and push pass the same security checks. That is
  what makes it safe to say "commit and push this repository you've never seen, with a fitting
  message": the agent can read the diff, the work log and the notes, write the message, and
  gitSpecOps refuses anything that must not leave.
- **Machine-readable** results with `--json`, and no prompts when every choice is a flag.

## Updates

- **The app** checks for releases, downloads in the background, verifies the signature, and
  offers "restart to update". A failed start rolls back to the previous version. Your settings
  live outside the app, so an update never touches them; if a release changes their format, it
  says so, keeps a backup, and asks.
- **Across your fleet**, one machine updates first; the others follow once it has run cleanly.
  The map shows each machine's version, and mixed versions keep working together.
- **Your repositories** stay current through standing consents you choose and can revoke:
  fetch and fast-forward clean, behind-only checkouts; optionally push ahead-only work.
  Anything else waits for you.

## What never happens

- No force push, no `reset --hard`, no rebase, merge or delete as an automatic action, ever.
- Nothing is scanned before you name the folders, and "find my libraries" looks only where
  you say, after you say so.
- No credentials stored: Git, `gh` and Tailscale use your own logins.
- Nothing leaves your machine except what you chose to share: status facts, and repository names
  only if you allow them. Never paths, diffs, file contents or commit messages.
- A background action happens only under a consent you set, for the repositories you chose.

## Commands

Every command runs on its own (`gitso <command>`), and lists itself with `gitso commands`.

| Layer | Meaning | Commands |
|---|---|---|
| **Basic** | one Git or host operation, done carefully | clone, commit, discover, fetch, pull, push, reset-keep, status |
| **Special** | this machine, once | enroll-machine, suggest-sync, catch-up, audit-repos, materialize, list-live-buffers, name-repo, update-archive, sync-archive, archive-manager, duplicate-org, export-inventory, restore-inventory, scan-tree, scan-history, review-finding, clean-history, follow-rewrite, commit, push |
| **Elaborate** | other machines, or over time | setup-fleet, peer, publish-status, suggest-fleet-sync, converge, check-safe-to-wipe, recovery, doctor, preflight, start-at-login, schedule-archives, request |
| **App** | presence | tray, serve-web, window, setup, update |

Each layer builds only on the ones before it, so every operation also works without the app.

## Building from source

For contributors. `uv sync --extra app` (or `python -m venv .venv` and
`pip install -r requirements.txt`), then run any command by its path, for example
`python Special/suggest_sync.py --help`. Releases are built and signed by CI on every
supported system; nobody needs to build their own.

## License

GPL-3.0-only, with a commercial license available. See [LICENSE](../../LICENSE) and
[NOTICE](../../NOTICE).
