# Launch the archive manager. Prefer the repo's .venv (built by run_setup);
# fall back to `uv run` when .venv is absent. Run from anywhere.
$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..")
$venvPy = Join-Path $repo ".venv\Scripts\python.exe"
Push-Location $repo
try {
    if (Test-Path $venvPy) {
        & $venvPy gitArchiveUpdater/archive_manager.py @args
    } else {
        uv run python gitArchiveUpdater/archive_manager.py @args
    }
} finally {
    Pop-Location
}
exit $LASTEXITCODE
