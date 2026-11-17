# Architecture, safety model and tests

## Safety model

- **Fast-forward only, everywhere.** Pulls are `--ff-only`; every push is a non-force push. Both
  name their remote and branch, so Git's configuration cannot widen or redirect them.
- **One operation, two faces.** An operation is a Python function; a `gitso` command and a
  button on the page both call it, with the settings profile and the target given explicitly.
  [One operation, end to end](ONE-OPERATION.md) follows a click down to its tests.
- **Detect, show the plan, approve, run, review.** A command that changes things works out its
  plan, with an id that is a digest of its content, and changes nothing. A person at a terminal
  is asked; a program applies it with `--apply PLAN_ID`, and a plan that changed in between is
  refused (exit 3). Failures are collected and reported at the end. Nothing ambiguous is applied
  automatically. Basic commands and single explicit settings act at once, like `git`.
- **Destructive-adjacent actions need a person**: a history rewrite needs an attended terminal,
  the plan id and the typed word REWRITE. Scheduled and launcher runs cannot reach them.
- **A tray item or a map button runs the same command as the terminal**, with the same plan and
  confirmation. Operations that change repositories refuse to run beside a live peer.
- **Bounded everything:** timeouts, bounded discovery and thread pools, non-interactive Git.

## Output

`Basic/_cli.py` is the one place that decides how a command answers. With no terminal attached
(a script, a scheduler, an AI agent), a command prints exactly one JSON record:
`{"command": ..., "ok": ..., ...}`, or `{"ok": false, "error": "one plain sentence"}`. At a
terminal it draws a station screen (`Basic/_station.py`, after Sb4ssport's station script
design). `--json` asks for the record at a terminal; `GITSPECOPS_OUTPUT=json|screen` overrides
the detection (the tests use `screen`, to read what a person would see).

Version numbers appear only on what gitSpecOps saves or sends and later reads back: the
settings file, fleet manifests, inventories, recovery snapshots, saved plans and reviews. Each
lets a reader refuse a format it does not understand instead of misreading it. Command output
carries none; it names its command instead, and the product has one version, in
`pyproject.toml`.
- **Your credentials stay yours.** No token is read, stored, forwarded or logged.

## Layout

```text
gitso.py      the front door: every command, by name
Basic/        one Git or host operation, done carefully
Special/      this machine, once
Elaborate/    other machines, or over time
App/          the tray (Qt) and the map (web view)
_os/          per-system pieces, the same files for Windows, Linux and macOS
docs/         the fleet guide, the display contract, recovery design, README images
_build/       setup, the desktop packaging recipe and release check
tests/        offline and synthetic; no network, no real repositories
.agents/      project brief, working notes, work log, durable knowledge
```

A file without an underscore is a command, runnable by its own path and listed by `gitso`;
anything with one is plumbing. Everything below `App/` is standard-library Python.
`Elaborate/_fleet/display.py` is the only module that turns fleet state into what the map and
tray show; every face reads that versioned contract.

**Kept out of the checkout:** settings, registrations, fleet state and logs live in your
per-user gitSpecOps folder (`GITSPECOPS_HOME` or `GITSPECOPS_SYNC_HOME` override). Generated and
never committed: `.venv/`, `Special/duplicate_org/runs/`, `.agents/output/`.

## Tests

Every test is offline and synthetic: no network, no real repository, no personal name.

```sh
python3 tests/run_all.py            # several files at once (up to 4), each in its own process
python3 tests/run_all.py --jobs 1   # one at a time, output as it happens
```

## Contributing and license

Working on this repository, human or agent? Start with [`.agents/README.md`](../.agents/README.md)
and the living [`.agents/WORKING-NOTES.md`](../.agents/WORKING-NOTES.md). What changed in each
version: [`CHANGELOG.md`](../CHANGELOG.md). Found a security problem? Report it privately, as
[`SECURITY.md`](../SECURITY.md) describes.

Licensed under the GNU General Public License, version 3 only (GPL-3.0-only): use it, study it,
change it and share it, and share anything you distribute that builds on it under the same terms.
To build gitSpecOps into a product that is not GPL-3.0, ask for a commercial license by opening
an issue on this repository. Versions up to commit `cacee74` were released under Apache 2.0 and
remain so. See [`LICENSE`](../LICENSE) and [`NOTICE`](../NOTICE).

Contributions are welcome. Because gitSpecOps is also offered under a commercial license, a
contribution can be accepted only with the contributor's agreement that it may be distributed
under both.

[Back to the README](../README.md)
