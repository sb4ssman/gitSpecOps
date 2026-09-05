# Distribution and updates

_Decision direction recorded 2026-09-05. Packaging is not yet implemented._

## The user promise

A normal user installs **gitSpecOps Sync-Suggester Fleet Management** from a trusted release,
launches it from the operating system's app list, and completes graphical first-run setup.
They do not clone this repository, install Python, extract source, choose a shell, or keep a
VS Code terminal open. Developer source execution remains supported, but it is a development
workflow rather than the product's onboarding path.

The installed app owns four pieces:

1. a self-contained executable containing the Python runtime and application resources;
2. a native launcher/tray shell that starts the local observer and opens the standard UI;
3. per-user configuration and SQLite state in the OS application-data directory;
4. an updater appropriate to the distribution channel.

Git remains a prerequisite because the product manages Git repositories. `gh auth` is the
first provider prerequisite chosen by the user: first run checks `git --version` and
`gh auth status`, explains a failure, and links to the provider's installer/login. It does
not silently install Git/GitHub CLI or manage their credentials. Tailscale is required only
for live-tailnet mode; folder and GitHub state modes remain alternative transports.

First run should perform these checks itself and provide targeted help. Asking Alice to study a
prerequisite list and prepare every optional provider before installation shifts our setup work
onto her. Git and working `gh auth` are hard gates. Tailscale is a gate only when she chooses live
mode. Obsidian is never a general prerequisite: synchronized-folder mode accepts any suitable
folder replicated by Obsidian Sync, Syncthing, OneDrive or another client. If she chooses GitHub
state and has no state repository, setup may offer to create a private repository under an owner
or organization she selects, with an explicit remote-write confirmation.

## Build shape

Keep the repository's flat source architecture. A release pipeline can use PyInstaller in
one-folder mode first: it embeds Python, produces one OS-specific application directory, and
makes missing resources/debugging more visible than a self-extracting one-file binary. Build
Windows on Windows, macOS on macOS, and Linux on Linux. Packaging dependencies are release
tooling, not runtime dependencies and do not enter the user's environment.

The foreground Python engine, versioned display contract and web presentation remain reusable.
The first native shell can be small: app lifecycle, tray/menu-bar integration, open-dashboard,
pause/resume, first-run forms and update status. It should speak the same local API and must not
duplicate Git policy. A later native UI or LCARS skin can replace the browser surface without
rewriting the engine.

## Release stages

1. **Developer preview:** source checkout and direct Python invocation. Current state.
2. **Portable preview:** unsigned, versioned one-folder bundles attached to GitHub Releases,
   with SHA-256 checksums and a clear development warning. Suitable for the developer's own
   three-machine validation; it will trigger OS reputation warnings.
3. **Public desktop beta:** signed Windows installer and notarized macOS app, plus a Linux
   AppImage or native package. First-run UI and uninstall are required before this stage.
4. **Store channels:** Microsoft Store/MSIX after app identity and update behavior stabilize;
   evaluate Mac App Store sandbox feasibility independently; consider Flathub after testing its
   filesystem and host-Git access constraints.

Certificates are not needed to write the app or produce local development builds. They become
part of a smooth public trust path: Windows requires MSIX packages to be signed, although the
Microsoft Store can sign an accepted MSIX; broadly distributed macOS builds should use Developer
ID signing and notarization. A random user's first-run experience should not ask them to trust a
self-signed certificate.

## Update model

There is one release manifest per channel (`stable`, `beta`, `development`) containing version,
minimum compatible database/report/display versions, per-platform artifact URL, size and SHA-256.
The manifest itself is signed with a release key embedded in the installed application. Transport
TLS and artifact hashes are necessary but do not replace signed release metadata.

The app checks no more often than the user's selected cadence, defaults to once daily, adds
jitter, and honors offline/rate-limit backoff. It downloads to a staging location, verifies the
signed metadata and artifact hash, and asks before installing except where an OS store owns
updates. The updater never replaces a running binary in place: stage, exit, atomically switch,
retain one previous version, start the new version, and roll back if its health check fails.
Database migrations take a backup first and must declare whether rollback remains possible.

Store-managed installations use the store updater and disable the app's installer path. Direct
installations use the signed release feed. Portable builds notify but do not self-modify until
the installer/updater is implemented. Source checkouts continue using Git explicitly and are
never rewritten by the application.

GitHub Releases is a reasonable first artifact and update host because checking once per day is
small, cacheable traffic. It is separate from fleet state publication: status activity never
causes release checks, and update checks never write to the fleet state repository.

## Work required before Alice's release

- Establish a product/application ID, semantic version source, icon set and real license file.
- Build a graphical first-run flow for repository roots, mode/transport and startup behavior.
- Create native lifecycle integration for Windows first, then macOS/Linux.
- Add reproducible OS-specific builds, checksums, release provenance and malware scanning.
- Add installer/uninstaller tests that preserve user data across upgrades and remove binaries
  cleanly without deleting repositories or Git configuration.
- Implement the signed update manifest and rollback-aware migration framework.
- Publish privacy, threat-model and diagnostics documentation suitable for non-developers.
- Remove the `Environment :: Console`/alpha-only product metadata when the desktop product earns it.

Until those items exist, documentation and the UI must call this a development preview. It must
not imply that cloning or downloading source is the intended experience for general users.
