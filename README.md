<p align="center"><img src="docs/images/gitspecops-mark.svg" width="96" height="96" alt="The gitSpecOps mark: a hub joined to a ring of machines"></p>

# gitSpecOps

**Git Special Operations: every copy of every Git repository you have, on every machine you
own, seen on one map, kept current, protected and coordinated.**

You have repositories on a laptop, a desktop, a server, maybe an old machine in a closet. Some
have work you never pushed. Some are behind. Some exist on one machine only. Some contain a
value that must never be published. gitSpecOps knows, shows you on one map, and asks you one
clear question about anything that needs you.

It sits beside tools like GitHub Desktop and Sourcetree. They work *deeply* in one repository;
gitSpecOps works *broadly*, across all of them and all your machines, and opens any repository
in your desktop Git app when you want to go deep.

![The network map: a menu of seven tiles (Network map, Repositories, Orgs/Archives, Machines, Clouds, Security, Settings), each with its number; below, three clouds (GitHub, GitLab, No remote) above four machines (Desktop, Home server, Laptop, Old laptop), lines showing how many repositories each machine holds from each cloud and how many need attention, and under each machine every organization and repository it holds, amber where that copy has unfinished work](docs/images/network-map.png)

*A made-up, messy fleet: every machine, owner and repository name in these pictures is invented.
See it yourself with `python _build/demo_fleet.py` (no setup; it reads nothing on your computer).*

> **Development preview.** Everything below marked *(planned)* is not built yet. Development and
> testing happen on Windows first; Linux and macOS are being verified now.

---

## How it works

1. **Every machine writes one small status file about its own repositories:** names, branches,
   and how far ahead, behind or uncommitted each copy is. Never file contents, never folder paths.
2. **Every machine reads everyone's files and draws the same map.** A machine that is switched
   off still appears, with its last report and how old that report is.
3. **The files travel however you like:** directly between your machines over Tailscale, through
   a folder your sync client already shares (OneDrive, Dropbox, Syncthing, a network share), or both.
4. **Git and the GitHub CLI do every real operation.** gitSpecOps looks, plans, checks and asks.

That is the whole system. Everything else is built on it in three layers, each using only the
one before:

| Layer | Means | For example |
|---|---|---|
| **Basic** | one Git or host operation, done carefully | commit, push, pull, clone; find every repository under a folder |
| **Special** | this machine, once | what needs attention here; catch up safely; secure-commit and secure-push |
| **Elaborate** | other machines, or over time | the fleet map; is this machine safe to wipe; start at sign-in |

Security sits alongside: `secure-commit` and `secure-push` check before anything leaves, and so
does every publish gitSpecOps makes on its own. Basic `commit` and `push` are plain, like git's.

## The page

Seven pages, one menu: each menu tile carries its number. The **Network map** is the picture;
every other page is a table that says each copy the same way, against its provider: "matches
GitHub", "12 behind GitHub", "4 uncommitted files", with the commit it is on beside it.

**Repositories and Orgs/Archives line every copy up**: one row per repository, one column per
library under each machine (a machine with two libraries gets two columns), and the provider
with its own commit. From the same row you can ask any machine to fast-forward what is simply
behind, or clone what it is missing, into the library you choose; the machine checks again
before it does anything. On another machine the request waits for Apply unless that machine
has opted in to running incoming requests automatically.

![One organization across the fleet: "acme-tools: 1 of 4 are the same on every machine that has them. 3 need a decision", the three listed with their advice; below, a grid with a row per repository and a column per library under each machine (Desktop; Home server with two libraries, backup and srv; Laptop; Old laptop, stale), each cell saying how that copy compares with GitHub, with "Fast-forward 1" and "Clone 1 missing" buttons above the libraries that need them](docs/images/organization.png)

**Machines** lists each machine with the libraries under it; **Clouds** lists the providers and
how the machines talk (Tailscale, a shared folder, a gitso-managed repository); **Security**
audits chosen repositories, files and every commit, and any group of repositories has an
a "Walk through" walkthrough that takes them one repository at a time; **Settings** changes this
machine's setup. From the Security page you can filter repositories by GitHub visibility
(Public, Private, Internal, Unknown) and choose **Select all public repos** for a first pass.

![Machines: four cards, each machine with its libraries under it and how many repositories, organizations and copies needing attention each holds; the Home server shows two libraries, and the Old laptop is marked stale](docs/images/machines.png)

## What never happens

- No force push, no rebase, no merge, no delete, and no `reset --hard` in any repository of
  yours. (Restoring a recovery snapshot works in a throwaway checkout of its own and may roll
  that back; it never touches your checkout.)
- Nothing changes a repository by itself. Watching only watches. A change is a command you ran,
  shown as a plan first, or one of the two things you can ask another of your own machines to
  do, which cannot lose work: a fast-forward after a fresh fetch, and a clone that replaces
  nothing.
- Nothing is scanned before you name the folders, and "find my libraries" looks only where you
  say, after you say so.
- No credentials stored: Git, `gh` and Tailscale use your own sign-ins.
- Nothing leaves your machine except what you chose to share: status facts, and repository names
  only if you allow them. Never paths, diffs or commit messages. File contents leave only in
  recovery snapshots, which are off until you enrol them.
  [Exactly what travels, and who can read it](docs/DATA-FLOWS.md).

---

## Get started

You need **Python 3.11 or later** and **Git**. Everything else is optional and only for the
features that use it: the GitHub CLI (`gh`), Tailscale, a file-sync client, a secret scanner.

```sh
git clone https://github.com/sb4ssman/gitSpecOps
cd gitSpecOps
./run_setup.sh          # Windows: run_setup.bat; macOS: double-click run_setup.command
```

On macOS 11 and later setup installs the Qt build made for that macOS, for the menu-bar icon (not
yet tried on a Mac: so far only the icon-less mode has run there). Older Macs run without an icon
and the page is the way in (`gitso tray --open`).

![Setup's menu in a terminal: the gitSpecOps banner, then "Walk me through everything", "Set up one part", "Use the commands without installing anything" and "Check this computer"](docs/images/setup-menu.png)

Choose **Walk me through everything**: it finds what this computer already has, asks about each
part, and changes nothing until you have reviewed the whole list. Or set up, change or repair one
part on its own, or use the commands without installing anything. [Setup in detail](docs/SETUP.md).

---

## Grow as you go

gitSpecOps is useful with nothing set up, and every step multiplies what came before: a fleet of
four machines turns "see my repositories" into "see every copy, on all four, even the ones
switched off".

| | **Nothing set up** | **+ This machine** | **+ A fleet** | **+ Tailscale** |
|---|---|---|---|---|
| **You add** | nothing | your library folders | a fleet key and a way to share | your own tailnet |
| **Basic** | find repositories; status, fetch, pull, clone, commit, push, on any you name | | | |
| **Special** | check what needs attention; catch up; archives; copy an organization | an always-on map of this machine; recovery snapshots of unfinished work | | |
| **Elaborate** | | start at sign-in | every machine on one map; where work is unpushed; clone what is missing; prove a machine safe to wipe | live status between machines; the map on your phone |
| **Protect** | scans; secure-commit and secure-push; history cleanup | findings on the map, on request | audit every machine *(planned)* | |
| **Agents can** | work on folders you name | work on this machine | observe the whole fleet | |

Built: ask another of your machines to fast-forward or clone and see the result when it runs.
Requests wait for Apply by default. Each receiving machine can opt in under Settings → Requests and the task log.
Use the **Visibility** filter to find public or private repositories. On **Orgs**, open
an individual issue or walk through the checkouts that need attention.

### Resolve work on another machine

Open a repository's details and choose **Request diff** under the machine that has the work.
Both devices need this build and a live Tailscale fleet connection. The receiving machine
approves disclosure in **Requests**. Open the resulting receipt to see staged and unstaged
diffs, or request a preview of a particular untracked file.

Choose the checkout and files, write a message, and request a commit check. The receiving
machine applies the checked commit only after a separate approval. A push has its own preview
of the branch, destination, and outgoing security checks. The checked push revalidates the
destination before sending any commits. The receiver's automatic clone and fast-forward mode
does not apply to Resolve requests. Resolve also offers branch and divergence inspection,
a stash list, and fetch. Stash creation previews the tracked files and requires a separate
apply request. Untracked files stay in the checkout.

### Enroll in security

Start in **Fleet Security**. Set **Protected values**, select your scanners, and use
**Select all public repos** for a first audit. Filter by visibility (Public, Private,
Internal, Unknown) to work through results one group at a time. Audits support up to
eight runners. Use **Export masked report** and **Open masked report** to revisit a run.
**Settings → Audit history storage** can save reusable scans locally when you opt in.
Coverage exports to a folder or private state repo are HMAC-signed receipts; receiving
machines verify the signature before using another machine's snapshot, and each machine
still applies its own policy and makes its own release decision.

For a checkout where routine Git commands should be checked, use `gitso commit-gate <checkout>`
to inspect its hook setup and `gitso commit-gate <checkout> --mode scan` to review the install.
Resolve any existing-hook integration on that checkout. For explicit outbound checks, use
`gitso secure-push <checkout>`. [Security and cleanup](docs/PROTECT.md).

A private GitHub state repository is another way to share fleet status.
[What works today, and what has only been tested](docs/STATUS.md).

## Commands

`gitso commands` lists them. At a terminal each shows a screen; run by a script or an AI agent,
each answers with one JSON record. Anything that changes things shows its plan first and acts
only on approval. [The command reference](docs/COMMANDS.md) has every command's own
description, generated from its source; [for AI agents](docs/FOR-AI-AGENTS.md) explains plans
and records.

Commands are `gitso <subject> <action>`; the Git ones keep Git's names. `gitso <subject>` lists
a subject's actions.

| Layer | Commands |
|---|---|
| **Basic** | discover, status, fetch, pull, clone, reset-keep, commit, push |
| **Special** | `machine` show / add / remove / find / presentation / check / catch-up / audit / materialize / buffers; `repo` name / list; `archive` add / remove / list / status / refresh / check / update / sync; `inventory` export / restore; `org copy`; `scan`; `review`; `history` scan / clean / follow / relink; `secure-commit`; `secure-push` |
| **Elaborate** | `machine safe-to-wipe`; `archive schedule`; `fleet` setup / status / transports / leave / key / baskets / git-client / join / doctor / preflight / publish / suggest / converge; `peer` run / rescan; `recovery`; `start-at-sign-in` |
| **App** | tray, serve-web, setup |

## Guides

- [Setup and requirements](docs/SETUP.md): installing, what gitSpecOps needs, the `gitso`
  command, setup without the walkthrough, updates.
- [The fleet](docs/FLEET.md): the tray and the map, how machines share, setting up and running
  a fleet, catching up, recovery.
- [Protect](docs/PROTECT.md): scans, secure-commit and secure-push, reviews, history cleanup.
- [Archives](docs/ARCHIVES.md): copying an organization, keeping folders of clones current.
- [For AI agents](docs/FOR-AI-AGENTS.md): plans, approvals and machine-readable results.
- [Command reference](docs/COMMANDS.md): every command's own description.
- [Architecture, safety model and tests](docs/ARCHITECTURE.md).
- [What works today](docs/STATUS.md): built, used, tested and run natively, per capability.
- [What leaves a machine](docs/DATA-FLOWS.md): per route, what travels and who can read it.
- [One operation, end to end](docs/ONE-OPERATION.md): a commit from the page, from the click
  to the test.
- [Three problems, and how they were solved](docs/CASE-STUDIES.md).

## License

GPL-3.0-only, with a commercial license available; see [`LICENSE`](LICENSE) and
[`NOTICE`](NOTICE). Changes: [`CHANGELOG.md`](CHANGELOG.md). Security problems: report them
privately, as [`SECURITY.md`](SECURITY.md) describes. Working on this repository, human or
agent? Start with [`.agents/README.md`](.agents/README.md).
