# Desktop preview build

Build on the operating system that will run the app; PyInstaller does not cross-compile.
The output embeds Python and the dashboard assets, while Git, GitHub CLI and Tailscale remain
external tools: Git is required, GitHub CLI is needed for the GitHub transport, and
Tailscale is optional for direct peer access.

From the repository root, in a disposable build environment with PyInstaller installed:

```sh
python -m PyInstaller --noconfirm --clean git-sync-suggester/packaging/GitSpecOpsSync.spec
```

First run the read-only local release gate:

```sh
python git-sync-suggester/packaging/release_check.py
```

It checks the declared version/tag relationship, worktree and patch whitespace, the build recipe
and assets, and whether PyInstaller is installed. It never creates a tag, changes a checkout,
builds an artifact or publishes a release.

The one-folder result is `dist/GitSpecOpsSync/`. Run `GitSpecOpsSync.exe` on Windows or
`GitSpecOpsSync` on Linux/macOS. The preview retains a console because first-run setup and
diagnostics are still terminal-driven. It opens the private fleet dashboard automatically.

With no arguments the bundle runs first-run setup (once) and then hands the process to the
tray. **It is also the full CLI** — `GitSpecOpsSync.exe doctor`, `... autostart enable`,
`... transports --folder PATH` — which is how the login entry re-launches it (`... tray`) and
how the build is smoke-tested without a configured fleet.

Two things in the spec are load-bearing:

- `hiddenimports` names the tray/autostart shells plus lazily imported recovery, action and
  live-buffer modules. PyInstaller's static analysis cannot see those imports, so omitting one
  would produce a build that fails only after a user reaches that feature.
- The build must run on the target OS. Verified builds: Linux (PyInstaller 6.22.2, 24 MiB) and
  Windows (PyInstaller 6.22.3, 2026-09-19). The current Windows artifact completed the
  configuration-free `GitSpecOpsSync.exe preflight` smoke test.

This is build input, not a public installer. Start-at-login now exists (`fleet autostart`,
per-user only, reversible), so the remaining packaging work is copying the one-folder result
into a durable location, uninstall support, and preserving configuration across upgrades.
