# Changelog

Notable changes to gitSpecOps, newest first. Versions follow [semantic versioning](https://semver.org/);
while the version starts with 0, gitSpecOps is a development preview and anything may change.

## Unreleased

- **Requests between machines run on arrival.** A request can only ask for a fast-forward after
  a fresh fetch or a clone that replaces nothing, and only a machine of the same fleet can send
  one, so the receiving machine now runs it when it next checks in, without a second approval
  there (`auto_requests: false` restores Apply). A request acts on the copy in the library you
  chose, and ends as done, partly done or not done, never "done" over a failure. Other machines
  are told fixed sentences per repository; Git's own words stay in that machine's task log.
- **Push and pull do exactly what was approved.** `gitso push` names its remote and one plain
  refspec, so a configured force refspec, a mirror remote or `push.default` cannot widen or
  overwrite; `gitso pull` and catch-up name the remote and branch, and refuse a branch that
  tracks another remote.
- **Safe-to-wipe is never SAFE over a folder it could not read.** Such a folder is listed and
  blocks the verdict.
- **A clone lands inside the library that was approved:** the real target is checked, links
  included, before anything is created.
- **Org copy asks about security.** No (the default) is an exact copy. Yes reads each history
  first; a repository with a high-severity finding is held, nothing is created for it, and you
  are told how to make a clean copy. Uploads send branches, tags and notes only.
- **A namespace's repository list is complete or it is an error** (the limit is 20,000, and a
  list that fills it is refused).

- **Reference**, a new menu item between Security and Settings: the catalog of operations by
  layer, each with its manual (and Git's own, for the Basic ones), this project's documents, and
  the online manuals of the tools it drives. Reading only.
- **The map's repository view:** machine boxes fit their columns (five overlapped); clicking one
  opens the repository's details. There, a copy with uncommitted work has "Show the N
  uncommitted files": that machine answers with file names and line counts. A machine that is
  off cannot answer, and the page says so.

- **Second copies, found and retired with proof.** The live line's "N folders are second copies"
  opens the list (a new filter, "Several copies on one machine"). A repository with several
  folders here lets you choose which copy the Resolve buttons act on, and "Safe to delete this
  copy?" fetches, then proves it: every commit on a remote, nothing stashed, and every
  uncommitted or untracked file byte-identical in another copy here (ignored files are listed,
  not judged). gitSpecOps deletes nothing; it opens the folder. A not-counted entry now covers
  everything inside its folder, and Settings can add a folder by path.
- **The audit page:** scanners and protected values sit above what to audit; installed scanners
  are ticked by default; a status line shows the phase of the repository being read (working
  files, then every commit with their count) and for how long.
- **"On my other devices"** in the header shows this machine's address for your phone or another
  computer on your Tailscale account, or how to turn that on.
- **The header** says this machine and the fleet in a few words; the full line is its tooltip.
- **Fixes:** the page's commit and push now pass the app's settings profile; a Git read that
  fails is an error, never an empty answer; Settings' not-counted list read the wrong record.

- **The page, rebuilt around one menu and one vocabulary.** The menu is seven tiles, each with its
  number: Network map (the zoomable picture, now the first page), Repositories, Orgs/Archives,
  Machines, Clouds, Security, Settings (was "App & setup"; `#about` still opens it). Repositories
  and Orgs/Archives draw the same grid: a column per library under each machine, the provider
  and its commit, each copy's commit. Machines lists each machine's libraries; Clouds lists
  providers and how machines talk; any repository group has "Audit these". The display contract
  gains `libraries`, `providers` and new `summary` totals, and `docs/DISPLAY-CONTRACT.md` is
  rewritten around the vocabulary.
- **Libraries are always named with what holds them**: `Github (T:\)`, `Github (memory-lambda)`,
  `Github (~)` for a home folder (never the account's name).
- **A machine with a repository in two libraries reports each copy**, with the commit its
  provider was on at the last fetch; clone requests name the library, and refuse a folder that
  is not a plain name.
- **Security: Show reveals a finding's real value**, on this machine only, from the audit in
  the app's memory.
- **Older Macs:** each macOS gets the newest Qt built for it (macOS 11-13 too); a Mac older than
  11 runs without an icon instead of failing to install Qt. The menu-bar app shows no Dock icon.
  The page works in Safari 15. `gitso update` over SSH on Linux restarts the app inside the
  desktop session.
- `python _build/demo_fleet.py` serves the page with an invented, messy fleet, for demos and
  screenshots.

- **Fixed (Windows): two gitSpecOps processes logging at the same moment could stop with
  `logging_write`.** A lock file being deleted by one process now counts as busy for the other.
- **The web setup page approves like the commands:** it shows the plan, then "Yes, do it". The
  typed confirmation words are gone.
- **CI runs Ruff** (development only; gitSpecOps does not need it to run) with the rules that
  catch mistakes, not style.
- Setup's desktop-app question says what it does (installs Qt into this folder's `.venv`).
- **Commands renamed: `gitso <subject> <action>`.** The Git commands keep Git's names;
  `gitso <subject>` lists a subject's actions. Old to new: enroll-machine to `machine`
  (show/add/remove/find/presentation); suggest-sync, catch-up, audit-repos, materialize,
  list-live-buffers, check-safe-to-wipe to `machine check/catch-up/audit/materialize/buffers/
  safe-to-wipe`; name-repo to `repo name`/`repo list`; archive-manager to `archive
  add/remove/list/status/refresh/check` (its --install/--forget/--list/--status/--refresh/
  --refresh-all/--scan-only flags are now these actions); update-archive, sync-archive,
  schedule-archives to `archive update/sync/schedule`; export-inventory, restore-inventory to
  `inventory export/restore`; duplicate-org to `org copy`; scan-tree to `scan`; review-finding
  to `review`; scan-history, clean-history, follow-rewrite to `history scan/clean/follow` and
  `history relink`; setup-fleet to `fleet` (fleet-key is `fleet key`, peer is `fleet join`);
  doctor, preflight, publish-status, suggest-fleet-sync, converge to `fleet
  doctor/preflight/publish/suggest/converge`; peer to `peer run/rescan`; start-at-login to
  `start-at-sign-in`. The command files are renamed to match (Special/archive.py, ...).
  Archive launchers written before this run the old file and must be written again
  (`archive add` on the same folder).
- **First run:** on a machine with no settings file, `machine show` says it is not enrolled,
  and adding the first library creates the settings file instead of refusing.
- **One output for every command.** Without a terminal (a script, a scheduler, an AI agent)
  every command prints one JSON record, `{"command", "ok", ...}`; at a terminal it draws a
  station screen. `--json` asks for the record at a terminal too. Report `--format` and
  `--output-mode`/`--no-report` are gone.
- **One approval for every command that changes things.** It shows its plan with an id and
  changes nothing; at a terminal it asks, and a script applies exactly that plan with
  `--apply PLAN_ID` (exit 3 if the plan changed). Gone: `--yes`, `--approve`,
  `--dry-run`, `update-archive --scan-only`, `--acknowledge-initial-scan`,
  `--confirm-private-location`, `--confirm-relaxed-policy`. `--approved-remote-prefix` is now
  `--allowed-remote`. `clean-history apply` is now `clean-history rewrite`, and still needs a
  person who types REWRITE. Basic commands and single explicit settings act at once, like git.
- **Reports:** one choice, also save each run's report as a JSON file (`--save-report`,
  setting `output.save`). The counts-only log stays on unless `--no-log`.
- **Setup:** the "standalone updater preferences" item and its settings actions are gone. The
  walkthrough gains an Archives part (register folders of clones, optional monthly refresh);
  the menu and the command list speak plainly, in the station style.
- **Removed:** `archive-manager --force-sync`; the archive tools' own version numbers (one
  product, one version); settings format 1; old internal names on screens and folders (Sync
  Suggester, standalone updater, Archive Manager, org duplicator).
- **Moved:** the per-user folder is now `gitSpecOps` (Linux: rename `~/.config/gitspecops`);
  on macOS it is `~/Library/Application Support/gitSpecOps`. The fleet's runtime folder inside
  it is `fleet/`. The start-at-sign-in entry is named `gitSpecOps`.
- **Help** names the command as typed: `usage: gitso archive-manager ...`.
- **Renamed:** the checked `gitso commit` and `gitso push` are now `gitso secure-commit` and
  `gitso secure-push` (Special). `gitso commit` and `gitso push` are now the plain Basic
  operations, like `git commit` and `git push`: exactly the named files, never a forced push,
  no security check. Scripts and agents that relied on the checked behaviour must switch names.
- **Basic commands listed:** status, fetch, pull, clone, reset-keep, commit and push.
- **Tests on Windows, macOS and Linux** with GitHub Actions, and a generated command reference
  (`docs/COMMANDS.md`).
- **Setup:** every menu item returns to the setup menu afterwards. The prerequisite check
  shows whether the GitHub CLI is signed in and what each tool is for.
- **Removed:** settings migration and the existing-settings switch (`settings-migration-preview`,
  `settings-existing*`): there are no users with older settings to convert.
- **Removed:** every other older-settings path. `settings.json` is the only place settings live:
  no `--legacy-policy` or `security/never_publish.txt`; no fleet `config.json`, `fleet-app.json`
  or `setup-fleet convert`; no archive choices in the receipts file. `GITSPECOPS_SYNC_HOME`
  now only moves the fleet's runtime state. Fleet setup and the first archive registration on a
  machine with no settings file create an empty profile.
- **The map:** under each machine, its library (every organization and repository it holds,
  coloured by that copy's own state). A repository is flagged only for unfinished work: being
  absent from a machine is normal, and a clean copy on an old report is "unknown" but not
  flagged. Every view now counts a machine's flags from its own copies.

## 0.2.0 — 2026-11-13

The first tagged version: a development preview, developed and tested on Windows.

- **Commands by layer** through `gitso`: Basic (one Git or host operation), Special (this
  machine, once), Elaborate (other machines, or over time), and App (the tray and the map).
- **The fleet:** every machine publishes one status file and reads everyone's; shared over
  Tailscale and/or a synced folder. The map in the browser shows every copy of every repository,
  including machines that are switched off.
- **Protect:** scans of working files, staged bytes and full history, with built-in checks and
  optional Gitleaks, Betterleaks 1 or TruffleHog; checked commit and push; reviews of one exact
  finding; history cleanup into a new private mirror, and `follow-rewrite` for your clones.
- **Archives:** copy an organization; keep archive folders current with fast-forward pulls;
  publish ahead-only work without force.
- **Setup:** a walkthrough that finds what the computer already has and changes nothing until
  reviewed; run any one command without setting anything up; `gitso` as plain-text launchers on
  the command path, or as a shell alias; start at sign-in that follows Task Manager, Startup
  Applications and Login Items.
- **Tests:** offline and synthetic, run several files at once.

Known gaps: Linux and macOS are not yet verified; the managed-repository way to share is
experimental and untested; items marked *(planned)* in the README are not built.
