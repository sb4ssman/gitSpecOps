# Setup and requirements

How to install and run gitSpecOps, what it needs, and how to set it up without the walkthrough.

## Get started

You need **Python 3.11 or later** and **Git**. Everything else is optional and only for the
features that use it: the GitHub CLI (`gh`), Tailscale, a file-sync client, a secret scanner.

```sh
git clone https://github.com/sb4ssman/gitSpecOps
cd gitSpecOps
./run_setup.sh          # Windows: run_setup.bat
```

Double-clicking works too. On Linux, choosing Execute in the file manager opens setup in a
terminal window (the first of x-terminal-emulator, Konsole, GNOME Terminal, Xfce Terminal, MATE
Terminal or xterm it finds), and the window waits for Enter before it closes.

![Setup's menu in a terminal: the gitSpecOps banner, then "Walk me through everything", "Set up one part", "Use the commands without installing anything" and "Check this computer"](images/setup-menu.png)

Setup's menu:

1. **Walk me through everything.** It finds what this computer already has and asks about each
   part, built up in gitSpecOps' own order: Basic (Git, the GitHub CLI and its sign-in, the
   `gitso` command), Special (library folders, protected values, secret scanners, archives),
   Elaborate (a fleet: Tailscale, a synced folder, and the experimental state repository, which
   defaults to no), then the App (the desktop app, a desktop Git app, start at sign-in). Nothing
   changes until you have reviewed the whole list. Afterwards it asks about a **first scan**:
   start the app, which reads your library and shows the map; read it right there in the
   terminal (`gitso machine check`, with progress); or not now, the default. Nothing starts
   unless you choose it.
2. **Update gitSpecOps.** Brings it up to date and keeps everything you chose: it shows what is
   new, fast-forwards this folder (never a merge or a reset), then refreshes the desktop app and
   the `gitso` command from the new version. It refuses, saying why, when this folder has its
   own changes or commits. Also `setup update`.
3. **Set up one part.** Any one of those ten parts on its own: set it up, change it, or repair
   it. It shows what is there now, and nothing changes until you review it.
4. **Use the commands without installing anything.** Any Basic, Special or Elaborate command,
   straight from the folder: registering archive folders to keep updated, say.
5. **Check this computer.** Git, the GitHub CLI and uv: what is there and what each is for.
6. **Uninstall.** Stops the app and removes what setup added, in the reverse order (start at
   sign-in, the desktop app's Qt, fleet membership, the monthly refresh task, downloaded
   scanners, the `gitso` alias and command), after showing the list. Your settings (protected values, library folders, logs) are deleted only if
   you say so. This folder, your repositories and programs installed with your package manager
   stay; it says which.

**The `gitso` command** is a command of its own, beside `git` and `gh`, in any terminal. The
   walkthrough can put it on your command path (small text launchers in `~/.gitspecops/bin`, on
   every system), and optionally add it to your shells as an alias; it removes both just as
   easily. On Windows the command path alone already reaches cmd, PowerShell and Git Bash, and
   Windows may refuse the alias (Controlled Folder Access protects Documents, where PowerShell
   keeps its profiles): setup then marks that step skipped and shows the line to add yourself.
   Without either, every command runs as `python gitso.py <command>`.

**The same from the app.** The web view's App & setup tab changes this machine's setup without a
terminal: join one of your fleets by its name on Tailscale (or, without Tailscale, with its key),
start one with a name, rename it or leave it, turn each connection on or off (Tailscale and how often it asks, a synced folder,
the state repository, and whether each carries repository names), the GitHub fetch schedule, and
start at sign-in. Changes to the fleet show what they will do first and happen only on Apply.
The tab appears on this computer only, never on the Tailscale view.

**Checking GitHub for new commits.** The app fetches every repository's remote, read-only, so the
map can say what is behind: once a day by default, every hour, or only when you ask (the tray's
menu: Preview catch-up). Setup asks; the first fetch comes one full interval after the app starts.

```sh
gitso commands             # every command, by layer
gitso docs machine check    # what a command reads, may change, and returns
gitso machine check         # this machine: what needs attention
gitso machine map           # the same, drawn as a folder tree
```

## Requirements and hard assumptions

| | |
|---|---|
| **Python 3.11+** | The command-line tools use only the standard library. The tray needs Qt (PySide6), which setup installs into this folder's `.venv` with `uv`. |
| **`git` on PATH** | Every Git operation runs your real `git`. |
| **`gh`, already signed in** | Only for anything that talks to GitHub. |

**Secret scanners** are optional. Setup installs one with your package manager (winget, Homebrew,
apt). Where none has it (TruffleHog on Windows), setup downloads the project's official GitHub
release, refuses it unless its SHA-256 matches the release's checksum file, and puts only the
program in `~/.gitspecops/tools`, where gitSpecOps looks as well as on PATH.

**Authentication is yours and stays yours.** gitSpecOps stores no token, writes no credential
file, configures no keyring, and never prompts for a password. It runs CLIs you have already
signed in to (`gh auth login` is yours to run). If `gh` is not signed in, GitHub features decline
to run; they never ask you for a secret.

- Anything GitHub-specific (organization listing, repository creation, following renames) needs
  `gh`. Plain archive updating needs only `git`, and works against any host.
- `GIT_TERMINAL_PROMPT=0` is forced everywhere, so a repository with expired credentials fails in
  under a second instead of hanging on an invisible prompt.
- Every subprocess has a timeout. Nothing blocks unbounded.

## Setup without the walkthrough

Every part of the walkthrough is also a command, for scripts and for agents:

| Part | Command |
|---|---|
| This machine's library folders | `gitso machine add FOLDER` (`find` suggests some) |
| Archives | `gitso archive add FOLDER --mode update` |
| A monthly archive refresh | `gitso archive schedule --install-monthly-task` |
| Start at sign-in | `gitso start-at-sign-in enable` |
| A fleet | `gitso fleet` (guided), or `fleet transports ...` |

A command that changes things shows its plan first: at a terminal it asks, and a script runs
it again with `--apply PLAN_ID` (see [For AI agents](FOR-AI-AGENTS.md)).

Settings live in one file, `settings.json`, in your per-user gitSpecOps folder:
`%APPDATA%\gitSpecOps` on Windows, `~/Library/Application Support/gitSpecOps` on macOS,
`~/.config/gitSpecOps` on Linux. `GITSPECOPS_HOME` (or `--settings-home`) points a run at
another folder instead, for a scratch profile or a first-run test; nothing else is changed.

## Updates

Run setup and choose **Update gitSpecOps** (or `setup update`): it fast-forwards this folder and
refreshes what depends on it. A plain `git pull --ff-only` does the first half by hand. Your
settings live outside the folder, so an update never touches them. If the app is running, quit it
from its tray menu and start it again to use the new version. Downloadable releases that update
themselves are *(planned)*.

[Back to the README](../README.md)
