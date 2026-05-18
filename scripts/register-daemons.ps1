# register-daemons.ps1 — DESCONTINUADO. Use o comando manual em
# docs/windows-setup-manual.md §9.
#
# Em vez de um script que cria a entry, cole esta linha única no
# PowerShell (depois de instalar com o guia manual):
#
#   schtasks /create /tn win-runner-status `
#     /tr "cmd /c `"$env:USERPROFILE\.local\bin\win-runner.cmd`" serve >> `"$env:LOCALAPPDATA\win-runner\status.log`" 2>&1" `
#     /sc onlogon /rl limited /f
#
# Pra iniciar agora: schtasks /run /tn win-runner-status
# Pra remover:       schtasks /delete /tn win-runner-status /f

Write-Host "register-daemons.ps1 foi removido em v0.2.1." -ForegroundColor Yellow
Write-Host "Veja docs/windows-setup-manual.md §9 — uma linha de schtasks." -ForegroundColor White
