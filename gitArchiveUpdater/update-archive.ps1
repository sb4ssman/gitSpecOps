# Launch the standalone archive updater. Prefer the repo's .venv (built by
# run_setup); fall back to `uv run` when .venv is absent. With no arguments,
# show --help so a bare double-click explains the tool instead of acting.
$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..")
$venvPy = Join-Path $repo ".venv\Scripts\python.exe"
$forward = if ($args.Count -eq 0) { @('--help') } else { $args }
Push-Location $repo
try {
    if (Test-Path $venvPy) {
        & $venvPy gitArchiveUpdater/archive_updater.py @forward
    } else {
        uv run python gitArchiveUpdater/archive_updater.py @forward
    }
} finally {
    Pop-Location
}
exit $LASTEXITCODE
