# probe.ps1 — versão curta. Notebooks corporativos com EDR estrito
# costumam bloquear o probe completo; este faz apenas 3 verificações
# óbvias sem APIs sensíveis em cadeia.
#
# Se ainda assim for bloqueado, use docs/windows-setup-manual.md
# (passos manuais, copia-e-cola).

Write-Host "win-runner probe (versão curta)" -ForegroundColor Cyan

Write-Host "`n1. Python:" -ForegroundColor Yellow
python --version 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host "  não encontrado" -ForegroundColor Red }

Write-Host "`n2. claude CLI:" -ForegroundColor Yellow
$c = Get-Command claude -ErrorAction SilentlyContinue
if ($c) { Write-Host "  $($c.Source)" -ForegroundColor Green } else { Write-Host "  não encontrado" -ForegroundColor Red }

Write-Host "`n3. Pasta do usuário gravável:" -ForegroundColor Yellow
try {
    New-Item -ItemType Directory -Path "$env:USERPROFILE\.local\bin" -Force -ErrorAction Stop | Out-Null
    Write-Host "  ok: $env:USERPROFILE\.local\bin" -ForegroundColor Green
} catch {
    Write-Host "  falhou: $_" -ForegroundColor Red
}

Write-Host "`nPara o resto da checagem (schtasks, proxy, etc), siga"
Write-Host "docs/windows-setup-manual.md  — cada comando isolado."
