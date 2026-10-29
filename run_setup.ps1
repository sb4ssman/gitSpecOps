param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ForwardedArgs
)

# Run the optional bootstrap. It needs *some* Python to start: prefer `uv run`
# (using an available Python without project sync/downloads), else `py`, else `python`.
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$setupScript = Join-Path $repoRoot "setup_gitspecops.py"
# Keep the caller's working directory so relative settings/root arguments retain their meaning.
if (Get-Command uv -ErrorAction SilentlyContinue) {
    uv run --no-project --no-python-downloads python $setupScript @ForwardedArgs
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    py $setupScript @ForwardedArgs
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    python $setupScript @ForwardedArgs
} else {
    Write-Error "No Python found. Install uv (https://docs.astral.sh/uv/) or Python (https://python.org)."
    exit 1
}
exit $LASTEXITCODE
