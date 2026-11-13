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
- **Setup:** running one command returns to the setup menu afterwards.

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
