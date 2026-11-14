# Changelog

Notable changes to gitSpecOps, newest first. Versions follow [semantic versioning](https://semver.org/);
while the version starts with 0, gitSpecOps is a development preview and anything may change.

## Unreleased

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
