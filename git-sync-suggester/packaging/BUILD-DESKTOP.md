# Desktop preview build

Build on the operating system that will run the app; PyInstaller does not cross-compile.
The output embeds Python and the dashboard assets, while Git, GitHub CLI and Tailscale remain
external tools: Git is required, GitHub CLI is needed for the GitHub transport, and
Tailscale is optional for direct peer access.

From the repository root, in a disposable build environment with PyInstaller installed:

```sh
python -m PyInstaller --noconfirm --clean git-sync-suggester/packaging/GitSpecOpsSync.spec
```

The one-folder result is `dist/GitSpecOpsSync/`. Run `GitSpecOpsSync.exe` on Windows or
`GitSpecOpsSync` on Linux/macOS. The preview retains a console because first-run setup and
diagnostics are still terminal-driven. It opens the private fleet dashboard automatically.

With no arguments the bundle runs first-run setup (once) and then hands the process to the
tray. **It is also the full CLI** — `GitSpecOpsSync.exe doctor`, `... autostart enable`,
`... transports --folder PATH` — which is how the login entry re-launches it (`... tray`) and
how the build is smoke-tested without a configured fleet.

Two things in the spec are load-bearing:

- `hiddenimports` names `fleet_tray`, `fleet_autostart` and `shared.console`. All three are
  imported lazily inside functions, so PyInstaller's static analysis never sees them and the
  frozen build would fail only at the moment a user clicked a tray menu item.
- The build must run on the target OS. Verified builds: Linux (PyInstaller 6.22.2, 24 MiB) and
  Windows (PyInstaller 6.22.2, 25 MiB, built on `machine-c` 2026-09-11).

This is build input, not a public installer. Start-at-login now exists (`fleet autostart`,
per-user only, reversible), so the remaining packaging work is copying the one-folder result
into a durable location, uninstall support, and preserving configuration across upgrades.
