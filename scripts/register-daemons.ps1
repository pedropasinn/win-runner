# register-daemons.ps1 — registra status server e scheduler como
# tarefas user-level no Task Scheduler (sem admin).
#
# Trigger: logon do usuário. Quando você faz login no Windows, os
# daemons sobem automaticamente em janela oculta. Saída para
# %LOCALAPPDATA%\win-runner\logs\<task>.log.
#
# Rode: powershell -ExecutionPolicy Bypass -File register-daemons.ps1
#
# Para desregistrar: scripts\unregister-daemons.ps1

$ErrorActionPreference = "Stop"

$Venv  = Join-Path $env:USERPROFILE ".local\win-runner-venv\Scripts\python.exe"
$Logs  = Join-Path $env:LOCALAPPDATA "win-runner\logs"

if (-not (Test-Path $Venv)) {
    Write-Error "venv não encontrado em $Venv. Rode install.ps1 antes."
    exit 1
}
New-Item -ItemType Directory -Path $Logs -Force | Out-Null

function Register-Task($name, $module, $extraArgs) {
    $log = Join-Path $Logs "$name.log"
    # Quoting: schtasks /tr é finicky; passamos via cmd /c para encadear
    # redirect de log. As aspas internas precisam ser triple-escaped.
    $tr = "cmd /c `"`"$Venv`" -m $module $extraArgs >> `"$log`" 2>&1`""
    Write-Host "registrando $name → $module" -ForegroundColor Cyan
    $out = schtasks /create /tn $name /tr $tr /sc onlogon /rl limited /f 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ ok" -ForegroundColor Green
    } else {
        Write-Host "  ✗ falhou: $out" -ForegroundColor Red
    }
}

Register-Task "win-runner-status" "win_runner.status_server" ""

# Scheduler-daemon: V0.2 não tem daemon contínuo próprio — as filas
# recorrentes são registradas individualmente via `win-runner schedule
# register`. Pulamos por enquanto.

Write-Host ""
Write-Host "Para iniciar agora (sem esperar logoff/logon):" -ForegroundColor Yellow
Write-Host "  schtasks /run /tn win-runner-status"
Write-Host ""
Write-Host "Para parar:" -ForegroundColor Yellow
Write-Host "  schtasks /end /tn win-runner-status"
Write-Host ""
Write-Host "Para ver status:" -ForegroundColor Yellow
Write-Host "  http://127.0.0.1:9090"
