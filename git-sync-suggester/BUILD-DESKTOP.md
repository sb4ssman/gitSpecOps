# Desktop preview build

Build on the operating system that will run the app; PyInstaller does not cross-compile.
The output embeds Python and the dashboard assets, while Git, GitHub CLI and Tailscale remain
explicit system prerequisites.

From the repository root, in a disposable build environment with PyInstaller installed:

```sh
python -m PyInstaller --noconfirm --clean git-sync-suggester/GitSpecOpsSync.spec
```

The one-folder result is `dist/GitSpecOpsSync/`. Run `GitSpecOpsSync.exe` on Windows or
`GitSpecOpsSync` on Linux/macOS. The preview retains a console because first-run setup and
diagnostics are still terminal-driven. It opens the private fleet dashboard automatically.

This is build input, not a public installer. The next packaging layer must copy the complete
one-folder result, register a per-user startup entry only with consent, add uninstall support,
and preserve configuration under the normal OS application-data directory across upgrades.
