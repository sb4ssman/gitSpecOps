# New tool: Sync Suggester

_Research and concept record — 2026-08-06_

## Status

This is a design document, not an implementation plan that has been approved. It records the problem,
ideas, constraints, transport alternatives, and how the tool could fit the gitSpecOps family. The
current leading direction is to build a small status/advice vertical slice before a tray application,
watch service, automatic push, or WIP transfer.

## The problem

A person works across several Git repositories and several computers. Before leaving one machine or
starting on another, they want a reliable answer to questions Git cannot answer by itself:

- Did I leave staged, unstaged, or untracked work on another computer?
- Did I commit but forget to push?
- Does this clone need to fetch/pull before I start?
- Is the same repository dirty on two computers?
- Can I see my whole GitHub/archive folder as one map, including cloud and peer-machine state?
- Can the system distinguish “everything is known to be synchronized” from “another machine has not
  reported recently, so its state is unknown”?

Git only knows the current clone and its locally cached remote-tracking refs. Sync Suggester therefore
needs to combine three observations:

```text
current machine  +  real source remotes  +  last reports from peer machines
```

The first release should synchronize **status facts**, not unfinished source content. It should help a
person preserve and publish work without silently taking custody of it.

## Product model

gitSpecOps is distributed as source. A user forks the public repository, clones their fork on every
computer, and runs setup; there is no separately installed binary. Their fork gives them a personal
tool checkout and an `origin`, while the public project remains available as `upstream`.

Cloning alone cannot activate background behavior. Setup must still establish a machine identity,
authentication or a shared-folder location, roots to observe, and any optional scheduled/watch task.

Sync Suggester can acquire roots from:

1. Archive Updater's existing local managed-archive registry.
2. Additional explicitly registered roots.
3. A future bounded discovery/watch mode within those roots.

It must not crawl an entire home directory or disk by default.

## GitHub visibility constraint

There are no private branches in a public GitHub repository. Branch protection limits mutation; it
does not hide branch contents. All forks of public gitSpecOps are public, share the repository
network's visibility, and commits pushed into that network can remain accessible even after a branch
or fork is removed. See GitHub's documentation on
[fork visibility](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/working-with-forks/about-permissions-and-visibility-of-forks)
and [protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).

Consequences:

- Never place plaintext machine manifests in a user's public gitSpecOps fork.
- A “secret” gist is also unsuitable; GitHub explicitly says
  [secret gists are not private](https://docs.github.com/en/get-started/writing-on-github/editing-and-sharing-content-with-gists/creating-gists).
- A private companion repository is viable and free on GitHub Free, but it is only one possible
  transport. GitHub currently advertises
  [unlimited public and private repositories](https://github.com/pricing) on its free plan.
- An encrypted blob could technically live in a public fork, but encryption-key pairing, metadata
  leakage, public history, and a new crypto dependency make it a poor default.

## The sync object

The logical sync object should be a small private namespace containing one independently written
manifest per machine, not one shared JSON file:

```text
gitspecops-state/
├── schema.json
└── machines/
    ├── 7c29a5b1-laptop.json
    ├── a611b9de-desktop.json
    └── d9ea0032-macbook.json
```

One-writer-per-file avoids most cloud-file and Git concurrency conflicts. Readers list every machine
file and aggregate them. A machine writes to a temporary sibling and atomically replaces its own file
where the filesystem/backend supports it. Every manifest includes a generation time; stale reports
are never treated as current proof of cleanliness.

A stale dirty/ahead report remains a warning (“last known unfinished work”). A stale clean report
becomes unknown, not clean.

### Privacy-minimized manifest

Version 1 should contain facts and counts, never diffs or file contents:

```json
{
  "schema_version": 1,
  "machine_id": "7c29a5b1",
  "machine_label": "laptop",
  "observed_at": "2026-08-06T18:42:00Z",
  "repositories": [
    {
      "repo_id": "sha256-of-canonical-remote-identity",
      "display_name": "optional-opt-in-name",
      "branch": "feature/login",
      "head": "917da2...",
      "upstream": "origin/feature/login",
      "upstream_observed_at": "2026-08-06T18:40:00Z",
      "ahead": 1,
      "behind": 0,
      "staged": 2,
      "unstaged": 1,
      "untracked": 0,
      "stashes": 1,
      "operation": null
    }
  ]
}
```

Do not publish absolute paths, usernames, remote URLs, filenames, ignored-file inventories, diffs,
commit messages, or source content by default. Hashing canonical `host/owner/repository` identities
lets HTTPS and SSH clones match, but hashes of predictable public repository names can be guessed; it
is data minimization, not encryption.

## Transport alternatives

The observer, classifier, and UI should not depend on GitHub. Define a tiny transport boundary:

```text
list_manifests() -> names
read_manifest(name) -> bytes + version/freshness
write_own_manifest(bytes, expected_version?)
doctor() -> availability, privacy, auth, errors
```

### 1. User-selected cloud-synced folder — best first experiment

The user chooses an already synchronized directory, for example:

```text
OneDrive/gitSpecOps-state/
Dropbox/gitSpecOps-state/
Google Drive/gitSpecOps-state/
Nextcloud/gitSpecOps-state/
Syncthing/gitSpecOps-state/
```

Sync Suggester performs ordinary local file reads and atomic writes. The installed cloud client owns
authentication, encryption in transit, offline queuing, and cross-machine replication. There is no
new repository, provider SDK, OAuth implementation, or API token in gitSpecOps.

Advantages: smallest code, provider-neutral, inspectable JSON, works with an account/client the user
already trusts, and easy to test locally. Disadvantages: it requires the same sync provider/client on
each computer; provider conflicts and delays must be surfaced; Linux support varies by provider. The
one-file-per-machine layout greatly reduces conflict risk.

This is the leading MVP transport because it tests whether the status/advice behavior is valuable
before gitSpecOps becomes a cloud integration product.

### 2. Designated existing private GitHub repository — no required new repo

The user may point Sync Suggester at any private repository they already own. Store state on a
dedicated orphan branch/ref so the normal checkout and default branch remain untouched. Verify
visibility before publishing.

Advantages: reuses `git`/`gh`, existing authentication, history, and the project's strongest platform
knowledge. Disadvantages: adds automation and status history to a repository created for another
purpose; a user may not have a suitable private repository; custom refs/branches require more plumbing
than a folder.

### 3. Automatically created private GitHub state repository

Setup creates or connects `USER/gitSpecOps-state`. Inside that private repository, either use one
file per machine on a shared state branch with fetch/rebase/retry, or one branch per machine to remove
writer contention entirely. A small tool-owned clone/cache keeps state operations away from the
gitSpecOps checkout.

Advantages: predictable, Git-native, cross-platform, versioned, and naturally aligned with users who
already authenticated to GitHub. Disadvantages: another repository in the account, Git commit churn,
more machinery than the amount of data warrants, and GitHub-specific coupling.

This remains a good default GitHub backend, but it should not define the core architecture.

### 4. Direct cloud “application data folder” API

Major storage providers expose least-privilege locations designed for exactly this type of data:

- Google Drive's `appDataFolder` is hidden and accessible only to the app, using the narrow
  `drive.appdata` OAuth scope. See
  [Google Drive application data](https://developers.google.com/workspace/drive/api/guides/appdata).
- OneDrive exposes `Apps/{application name}` through `special/approot` and provides the
  `Files.ReadWrite.AppFolder` least-privilege scope across home and work/school accounts. See
  [OneDrive app folders](https://learn.microsoft.com/en-us/graph/onedrive-sharepoint-appfolder).
- Dropbox offers an App Folder permission limited to the application's folder. See the
  [Dropbox OAuth guide](https://developers.dropbox.com/oauth-guide).

Advantages: no Git repository, secure provider-managed object storage, narrow permissions, works when
desktop sync software is absent. Disadvantages: OAuth application registration, redirect/device-code
flows, refresh-token storage, provider review/policy maintenance, three separate implementations, and
likely non-stdlib dependencies. This is attractive for a mature product, not the first slice.

Free personal storage is vastly more than these tiny manifests: at research time Dropbox Basic
advertises [2 GB](https://help.dropbox.com/plans/dropbox-basic-faq), and Microsoft accounts include
[5 GB of OneDrive storage](https://support.microsoft.com/en-us/onedrive/microsoft-storage-faqs).
Quota is not the limiting factor; integration burden is.

### 5. Generic object storage (S3-compatible / Cloudflare R2)

Store `machines/<id>.json` objects in a private bucket with scoped credentials. Cloudflare R2 is
S3-compatible, strongly consistent, and currently includes a free tier far above this workload; see
[R2 architecture](https://developers.cloudflare.com/r2/how-r2-works/) and
[R2 pricing](https://developers.cloudflare.com/r2/pricing/).

Advantages: technically clean, direct conditional writes, no Git history, provider-neutral S3 model.
Disadvantages: cloud-account and bucket setup, access-key distribution to every machine, credential
rotation, possible billing onboarding, and an SDK/signing implementation. Better for advanced users
or a future hosted service than a friendly default.

### 6. Syncthing or peer-to-peer state folder

Synchronize only the tiny manifest directory, never working repositories or `.git`. This is free,
private, and avoids a central provider. It uses the same folder transport as option 1.

Advantages: no cloud data account, no API, user-controlled devices. Disadvantages: devices must be
paired, and state propagation needs overlapping availability or an always-on peer/NAS. A laptop left
offline cannot publish a final change after the fact. It is an excellent optional transport but does
not by itself guarantee an always-available cloud witness.

### 7. Existing private source repositories

Publish a custom ref/note or machine-status branch into every project's own remote. This creates no
central repository or cloud account.

Advantages: repo identity is inherent and Git auth already exists. Disadvantages: it spreads status
writes across every project, fails for public/read-only/non-GitHub repos, requires broad write access,
may trigger policy/automation, and offers no easy whole-folder inventory. Reject as a default.

### 8. Encrypted state in the public fork

Publish one encrypted blob per machine to the user's public gitSpecOps fork. This removes the private
repository but does not create private branches.

Advantages: self-contained fork-as-installation. Disadvantages: a strong cross-platform encryption
implementation and independent key-pairing channel are mandatory; losing the key loses the state;
commit timing/size remain public; ciphertext remains in public Git history. Reject for the MVP.

### Options not recommended

- Secret GitHub gist: unlisted, not private.
- One shared JSON document: concurrent writers and last-writer-wins loss.
- Google Sheet/database as the first backend: more auth/schema/concurrency work than a few files.
- Full working-tree Dropbox/Syncthing mirroring: solves a different problem and can create conflicts
  in source and `.git`; Sync Suggester should initially mirror status only.
- Automatic WIP patch upload: can exfiltrate secrets and requires recovery/merge policy.

## Current transport recommendation

Build in this order:

1. **Local folder transport** with one manifest per machine. Test it using a normal temporary/shared
   directory and manually using a user's existing cloud-synced folder.
2. **Private Git repository transport** accepting a designated existing repo or creating a dedicated
   one. Do not require creation if the user already has a suitable private repo.
3. Only after real use, decide whether direct Google/OneDrive/Dropbox OAuth backends justify their
   permanent maintenance cost.

This keeps the core honest: Sync Suggester needs a private, eventually consistent object namespace;
it does not inherently need GitHub.

## Observation and freshness

Use Git's script-oriented status output to obtain local facts. Porcelain v2 exposes branch/upstream,
ahead/behind, index, work-tree, and untracked state; see
[git-status](https://git-scm.com/docs/git-status.html). Avoid unintended optional index refreshes for
pure observation where practical (`GIT_OPTIONAL_LOCKS=0`) and bound subprocess timeouts.

There are two cadences:

- **Local observation:** cheap/debounced after meaningful filesystem events or periodic polling.
- **Cloud observation:** less-frequent `git fetch` against actual source remotes, with timeouts and
  per-repository errors. Fetch updates refs but not working files; still label it as network activity.

Ahead/behind without a recent fetch is cached knowledge and must be labeled with
`upstream_observed_at`. The dashboard must never render “all clear” when relevant cloud or peer data is
too stale to prove it.

Watch only configured roots. A true event watcher must watch work-tree files as well as `.git`—an
unstaged nested file edit may not alter `.git`. A simple periodic scan is more portable and should be
the first background implementation; an optional `watchdog`-style dependency can add native file
events later. Publish only on semantic state changes plus an occasional heartbeat to avoid churn.

## Classification and UI

Pure decision logic should classify at least:

- clean and synchronized;
- local/peer dirty, staged, or untracked;
- ahead-only (push suggested);
- behind-only and clean (fast-forward pull suggested);
- ahead and behind (diverged, human decision);
- detached/no upstream/missing remote (direction unknown);
- same repo dirty on two machines (highest-severity collision warning);
- stale clean peer (unknown);
- stale dirty/ahead peer (last-known unresolved work).

Example ASCII control-tower view:

```text
Repository      LAPTOP          CLOUD          DESKTOP          Advice
──────────────────────────────────────────────────────────────────────────
website         clean, behind 2 main @81ad2    clean, current    PULL ↓2
api             clean, current  feature @44bc  dirty: 3, ahead 1 STOP: desktop work
gitSpecOps      ahead 1, clean  main @77fa1    clean, current    PUSH laptop ↑1
experiments     dirty: 2        no upstream    not present       COMMIT or preserve
old-project     clean            current        last seen 9d ago  desktop unknown
```

Symbols can remain consistent across CLI, tray, and GUI:

```text
✓ clean/synchronized   ✎ dirty   ↑ push   ↓ pull   ↕ diverged   ⚠ collision   ? unknown
```

The first release is advisory. Later explicit apply actions may allow:

- clean + behind-only + fresh fetch -> `git pull --ff-only`;
- clean + ahead-only + fresh fetch -> normal non-force `git push`;
- dirty/diverged/detached/no-upstream -> never automatic.

Auto-commit, WIP branches, patch upload, and untracked/binary transfer belong to a separate explicit
**handoff** design. They must not hide inside the watcher or scheduled publisher.

## Tray application and background operation

Start with CLI and a visible scheduled/polling mode. Cross-platform service installation differs:

- Windows Task Scheduler;
- macOS LaunchAgent;
- Linux systemd user service/timer or documented cron fallback.

A simple Tk window may be possible, but a real cross-platform system tray is not stdlib-only and will
need optional GUI dependencies and platform testing. Treat it as a presenter over the same cached
model, never as the scanner or transport itself.

Potential tray states:

```text
green  verifiably synchronized
blue   safe pulls available
orange commits need pushing
red    unfinished peer work or collision risk
gray   peer/cloud state unknown or stale
```

## Taking a step back: gitSpecOps as a family

The tools are different operations over a common mental model:

```text
                         repository inventory
                                  │
                         read-only Git facts
                                  │
                    pure classification / planning
                       ┌──────────┼───────────┐
                       │          │           │
                archive update  suggest    duplicate org
                  pull/clone     status      migrate repos
                       │          │           │
                    explicit, bounded apply operations
```

### Shared capabilities

1. **Inventory:** configured roots, direct-child repo discovery, canonical remote identity, machine
   and collection labels.
2. **Inspection:** branch, HEAD, upstream, dirty/index/untracked/stash/operation state, ahead/behind,
   remote freshness.
3. **Provider seam:** GitHub discovery and authentication where needed, while local Git facts remain
   host-neutral.
4. **Pure planning:** facts in, classifications/actions out; self-testable without GitHub or a disk.
5. **Apply safety:** preview, explicit confirmation, fast-forward pull, non-force push, graceful
   per-repository failure, no ambiguous automation.
6. **Reporting:** stable JSON schema, ASCII rendering, logs, timestamps/freshness, eventual GUI/tray.
7. **Runtime:** common timeout/error conventions, optional scheduled runners, visible local registry
   and ignored `runs/` state.

### Tool responsibilities

- **Archive Updater:** keep known collections present and fast-forward current; optionally discover
  and clone authoritative org inventory.
- **Sync Suggester:** observe local/cloud/peer states and recommend the next safe human action.
- **GitHub Org Duplicator:** perform a confirmation-heavy, resumable one-time transfer between orgs.
- **Future Publisher:** explicitly publish ahead-only committed work; do not conflate it with the
  observer or archive pull schedule.
- **Future Handoff:** deliberately preserve/move unfinished work; separate privacy and merge policy.

Do not create a large common framework prematurely. The Archive Updater's `git_inspect.py` is the
obvious first reuse point. Add the richer facts needed by Sync Suggester behind clear read-only
functions, keep cross-machine classification pure, and extract neutral shared modules only after two
real consumers prove the boundary. Preserve the repo's flat, stdlib-first, static-launcher model.

## Smallest useful vertical slice

1. Add two configured roots or reuse Archive Updater's registry.
2. Inspect direct-child repositories and produce a local manifest.
3. Read/write per-machine manifests through a user-selected folder.
4. Aggregate two fixture/machine reports into the ASCII dashboard.
5. Self-test dirty, ahead, behind, diverged, double-dirty, stale-clean, and stale-dirty rules.
6. Perform no source pull, push, commit, stash, or patch transfer.

This slice answers the product question—whether the reminder/map changes behavior—without committing
the project to GitHub repositories, OAuth providers, tray dependencies, or a daemon architecture.

## Open decisions

- Is a user-selected cloud-synced folder acceptable as the initial “installation pairing” story?
- Should repository display names be published by default inside a private transport, or remain an
  explicit opt-in?
- What freshness thresholds define current, stale-warning, and expired?
- Do intentional long-lived stashes prevent an “all clear” result or merely appear as information?
- Should cloud fetch be manual by default, scheduled opt-in, or part of every `check`?
- Is Sync Suggester limited to direct children of registered roots initially?
- When the Git transport arrives, should it prefer a designated existing private repo or offer to
  create `gitSpecOps-state` first?
- What does “installed” mean on each OS: manual launcher, login task, periodic timer, watcher, tray, or
  selectable combinations?

