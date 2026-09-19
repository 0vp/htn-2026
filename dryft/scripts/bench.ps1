param(
    [ValidateSet('check', 'run', 'watch', 'status', 'rerun')]
    [string]$Action = 'watch'
)

$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    & uv run --locked scripts/benchmark.py $Action
    $benchmarkExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $benchmarkExitCode
