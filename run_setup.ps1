param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $repoRoot
try {
    uv run python setup_gitspecops.py @Args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
