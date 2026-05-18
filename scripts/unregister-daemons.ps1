# unregister-daemons.ps1 — remove tarefas user-level criadas por register-daemons.ps1.

$tasks = @("win-runner-status")
foreach ($t in $tasks) {
    Write-Host "removendo $t..." -ForegroundColor Cyan
    $out = schtasks /delete /tn $t /f 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ removida" -ForegroundColor Green
    } else {
        Write-Host "  ✗ $out" -ForegroundColor Red
    }
}
