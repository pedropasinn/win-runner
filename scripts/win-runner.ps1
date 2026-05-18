# win-runner.ps1 — wrapper opcional para rodar sem o shim instalado.
#
# Útil para teste local antes do install.ps1, ou para CI.
# Equivalente a: python -m win_runner $args
#
# Uso:
#   .\scripts\win-runner.ps1 list
#   .\scripts\win-runner.ps1 run hello

[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Args
)

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Venv     = Join-Path $env:USERPROFILE ".local\win-runner-venv\Scripts\python.exe"

if (Test-Path $Venv) {
    $python = $Venv
} else {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) { $cmd = Get-Command py -ErrorAction SilentlyContinue }
    if (-not $cmd) { Write-Error "Python não encontrado"; exit 1 }
    $python = $cmd.Source
}

$env:PYTHONPATH = "$RepoRoot;$env:PYTHONPATH"
& $python -m win_runner @Args
exit $LASTEXITCODE
