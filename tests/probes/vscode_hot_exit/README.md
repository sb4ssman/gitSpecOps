# VS Code backup timing

Checks whether an unsaved edit is written to VS Code's `Backups` directory while the editor
is still running. It verifies the backup contains a synthetic marker, the document remains
dirty, and the saved file remains unchanged. It records the VS Code version and elapsed time.

Prerequisites: Python 3.11+ and installed desktop VS Code. No npm packages or downloads.

If you have already made an unsaved edit, inspect its existing backup without launching an
editor or changing any file:

```sh
python tests/probes/vscode_hot_exit/probe.py --inspect-file README.md
```

On Windows this uses the standard `%APPDATA%/Code/Backups` directory. Other platforms or custom
profiles require `--backup-root /path/to/Backups`. Only the selected file's backup content is
read, identified by the backup header's file URI. Output contains lengths, age, and whether
content differs from the saved file; no source text or local paths. This snapshot cannot measure
typing-to-backup delay. Confirm the edit is still unsaved and the editor has not exited.

From the repository root:

```sh
python tests/probes/vscode_hot_exit/probe.py
```

The default only prepares a fresh directory under the OS temporary directory and prints its
location. It does **not** launch VS Code. To explicitly run the experiment:

```sh
python tests/probes/vscode_hot_exit/probe.py --run
```

Use the repository virtual environment when available. If VS Code is not on PATH, add
`--code /path/to/Code.exe` (or the platform's `code` launcher).

The run creates a separate user-data directory, extensions directory, and disposable workspace.
It launches VS Code's extension-test host with a small test harness that edits only `probe.txt`.
The harness is not installed in your normal editor and is not a proposed product extension.
Auto Save is disabled, Hot Exit is enabled, and telemetry is disabled in the disposable profile.
The probe never reads your normal profile or open documents. A separate editor window may
appear; the extension-test process normally exits when the probe completes.

The harness checks for a backup every 500 ms for up to 20 seconds. This bounded experiment
does not add a polling loop to gitSpecOps. The launcher allows 90 seconds for startup and
completion. On timeout it reports failure; if the isolated editor is still open, close it.

`result.json`, `stdout.log`, and `stderr.log` stay under the printed temporary directory.
The directory is retained for inspection; remove that exact directory when finished. Do not
commit raw logs or profiles. The result is printed as JSON and contains no local paths.

A successful result establishes behavior only for the tested version, profile settings, and
local-file case. It does not prove power-loss durability, a stable backup format, or support
for remote workspaces, other profiles, or every kind of editor buffer. A failure before the
test harness starts is an inconclusive environment failure, not evidence that backups are absent.

Reference: [VS Code Hot Exit](https://code.visualstudio.com/docs/editing/codebasics#_hot-exit).
