param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ForwardedArgs
)

# Run the optional bootstrap. It needs *some* Python to start: prefer `uv run`
# (uv provides its own Python), else the `py` launcher, else `python`.
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $repoRoot
try {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        uv run python setup_gitspecops.py @ForwardedArgs
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        py setup_gitspecops.py @ForwardedArgs
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        python setup_gitspecops.py @ForwardedArgs
    } else {
        Write-Error "No Python found. Install uv (https://docs.astral.sh/uv/) or Python (https://python.org)."
        exit 1
    }
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
