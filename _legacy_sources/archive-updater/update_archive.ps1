param(
    [switch]$ScanOnly,
    [switch]$ShowRemoteUrls,
    [switch]$NoReport
)

$tool = "T:\Github\sb4ssman\PythonTools\ArchiveUpdater\archive_updater.py"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

$outputDir = Join-Path $root "ArchAgent\_claude_notes\_claude_outputs\archive_updates"
$pyArgs = @(
    $tool,
    "--root", $root,
    "--output-dir", $outputDir,
    "--approved-remote-prefix", "https://github.com/",
    "--approved-remote-prefix", "https://gitlab.com/"
)

if ($ScanOnly) {
    $pyArgs += "--scan-only"
}

if ($ShowRemoteUrls) {
    $pyArgs += "--show-remote-urls"
}

if ($NoReport) {
    $pyArgs += "--no-report"
}

python @pyArgs
exit $LASTEXITCODE
