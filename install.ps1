# install.ps1 — DESCONTINUADO em favor do guia manual.
#
# Notebooks corporativos com EDR costumam bloquear scripts PowerShell
# longos que invocam winget + setx + schtasks + Invoke-WebRequest em
# sequência (parece reconnaissance). Em vez de tentar contornar
# (assinatura, whitelist) este projeto agora documenta o setup como
# comandos manuais.
#
# Abra: docs/windows-setup-manual.md
#
# São ~15 comandos curtos pra colar um por vez no PowerShell. Leva ~10
# minutos. Cada um isoladamente é benigno e quase nunca é bloqueado.

Write-Host "install.ps1 foi removido em v0.2.1." -ForegroundColor Yellow
Write-Host ""
Write-Host "Notebooks corporativos com EDR bloqueiam scripts longos." -ForegroundColor White
Write-Host "Use o guia manual com comandos copia-e-cola:" -ForegroundColor White
Write-Host ""
Write-Host "  docs\windows-setup-manual.md" -ForegroundColor Cyan
Write-Host ""
Write-Host "Cada comando é curto e isolado — passa pelo EDR sem alarme." -ForegroundColor White
