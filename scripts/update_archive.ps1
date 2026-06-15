param(
    [switch]$ScanOnly,
    [switch]$ShowRemoteUrls,
    [switch]$NoReport
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$outputDir = Join-Path $root "ArchAgent\_claude_notes\_claude_outputs\archive_updates"
$pyArgs = @(
    "-m", "git_spec_ops.archive_updater",
    "--root", $root,
    "--output-dir", $outputDir,
    "--approved-remote-prefix", "https://github.com/",
    "--approved-remote-prefix", "https://gitlab.com/"
)

if ($ScanOnly) { $pyArgs += "--scan-only" }
if ($ShowRemoteUrls) { $pyArgs += "--show-remote-urls" }
if ($NoReport) { $pyArgs += "--no-report" }

python @pyArgs
exit $LASTEXITCODE
