# Archives: copy an organization, keep folders of clones current

### Copy an organization

```sh
gitso duplicate-org
```

Downloads every repository in an organization, uploads a folder of local repositories into one,
or migrates organization to organization. Previews, checks for name collisions before any remote
call, asks for typed confirmation, and writes resumable run files so an interrupted migration
continues instead of restarting.

### Keep archives current

```sh
gitso update-archive --root /path/to/archive
gitso archive-manager --list
gitso archive-manager --install /path/to/archive --mode update
```

**Fast-forward pulls only.** A repository that is dirty, diverged, or on an unapproved remote is
reported and skipped, never "fixed". `update-archive` uses only `git` and updates what is on
disk, with any host. `sync-archive` asks GitHub (via `gh`) what *should* be there, so it can
also clone what is missing, repair stale origins after a rename, and rename folders to match
upstream, each as a separate, explicitly approved kind of change. If discovery fails it falls
back to updating only; it never invents a clone, an orphan or a rename from a failed listing.
Identity is by stable provider id, never by folder name or URL.

`archive-manager` registers archives, refreshes them in their saved mode, and installs
per-archive launchers; `schedule-archives` sets up a monthly refresh. Registrations live in your
per-user gitSpecOps folder (`%APPDATA%\gitspecops` on Windows, `~/.config/gitspecops` elsewhere;
`GITSPECOPS_HOME` overrides), never in the checkout, so a scheduled refresh keeps working when
the code moves. Output goes to the terminal by default; reports and counts-only logs are opt-in.
Use `--scan-only` to look without changing anything.

### Publishing archives

```sh
gitso sync-archive --root /path/to/archive --publish --dry-run
```

`--publish` pushes without force, so Git itself refuses anything that is not a fast-forward.
Only clean, ahead-only repositories are eligible, the exact outgoing history is checked first,
and the remote is fetched again just before pushing. It cannot be combined with other changes,
or run by a launcher or a scheduled task. Nothing is ever committed automatically.

[Back to the README](../README.md)
