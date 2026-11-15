# Architecture, safety model and tests

## Safety model

- **Fast-forward only, everywhere.** Pulls are `--ff-only`; every push is a non-force push.
- **Detect, show the plan, approve, run, review.** Failures are collected and reported at the
  end. Nothing ambiguous is applied automatically.
- **Destructive-adjacent actions are interactive only** and need typed confirmation; scheduled
  and launcher runs cannot reach them.
- **A tray item or a map button runs the same command as the terminal**, with the same plan and
  confirmation. Operations that change repositories refuse to run beside a live peer.
- **Bounded everything:** timeouts, bounded discovery and thread pools, non-interactive Git.
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
