# probe.ps1 — checa o que o notebook corporativo permite ANTES de tentar instalar.
#
# Gera um relatório com cada verificação verde/vermelha. Sem mudar nada
# no sistema (read-only exceto criar/apagar 1 task de teste no Task
# Scheduler — atividade reversível e user-level).
#
# Rode: powershell -ExecutionPolicy Bypass -File probe.ps1

$ErrorActionPreference = "Continue"
$results = @()

function Add-Result($name, $ok, $detail) {
    $script:results += [PSCustomObject]@{
        Check  = $name
        Status = if ($ok) { "OK" } else { "FAIL" }
        Detail = $detail
    }
    $color = if ($ok) { "Green" } else { "Red" }
    $icon  = if ($ok) { "✓" } else { "✗" }
    Write-Host "  $icon $name" -ForegroundColor $color
    if ($detail) { Write-Host "    $detail" -ForegroundColor DarkGray }
}

Write-Host "win-runner — probe de ambiente Windows" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

# ─── 1. Escrita em %USERPROFILE%\.local ────────────────────────────────
Write-Host "1. Escrita user-mode" -ForegroundColor Yellow
$localDir = Join-Path $env:USERPROFILE ".local"
try {
    New-Item -ItemType Directory -Path "$localDir\probe-test" -Force -ErrorAction Stop | Out-Null
    "test" | Out-File "$localDir\probe-test\test.txt" -ErrorAction Stop
    Remove-Item -Recurse -Force "$localDir\probe-test"
    Add-Result "escrita em $localDir" $true ""
} catch {
    Add-Result "escrita em $localDir" $false $_.Exception.Message
}

# ─── 2. Escrita em %LOCALAPPDATA% ──────────────────────────────────────
try {
    New-Item -ItemType Directory -Path "$env:LOCALAPPDATA\win-runner-probe" -Force -ErrorAction Stop | Out-Null
    Remove-Item -Recurse -Force "$env:LOCALAPPDATA\win-runner-probe"
    Add-Result "escrita em $env:LOCALAPPDATA" $true ""
} catch {
    Add-Result "escrita em $env:LOCALAPPDATA" $false $_.Exception.Message
}

# ─── 3. Task Scheduler user-level ──────────────────────────────────────
Write-Host ""
Write-Host "2. Task Scheduler (user-level, sem admin)" -ForegroundColor Yellow
$probeName = "win-runner-probe-test"
try {
    $out = schtasks /create /tn $probeName /tr "cmd /c echo probe" /sc once /st 23:59 /sd 12/31/2099 /f 2>&1
    if ($LASTEXITCODE -eq 0) {
        Add-Result "criar tarefa user-level" $true ""
        $out = schtasks /delete /tn $probeName /f 2>&1
        if ($LASTEXITCODE -eq 0) {
            Add-Result "deletar tarefa" $true ""
        } else {
            Add-Result "deletar tarefa" $false ($out -join "; ")
        }
    } else {
        Add-Result "criar tarefa user-level" $false ($out -join "; ")
    }
} catch {
    Add-Result "criar tarefa user-level" $false $_.Exception.Message
}

# ─── 4. Ferramentas no PATH ────────────────────────────────────────────
Write-Host ""
Write-Host "3. Ferramentas pré-instaladas" -ForegroundColor Yellow
foreach ($tool in @("python", "py", "git", "node", "npm", "claude", "winget")) {
    $cmd = Get-Command $tool -ErrorAction SilentlyContinue
    if ($cmd) {
        $ver = & $cmd.Source --version 2>&1 | Select-Object -First 1
        Add-Result "$tool no PATH" $true "$ver"
    } else {
        Add-Result "$tool no PATH" $false "não encontrado"
    }
}

# ─── 5. Proxy ──────────────────────────────────────────────────────────
Write-Host ""
Write-Host "4. Rede / proxy" -ForegroundColor Yellow
$proxyOut = netsh winhttp show proxy 2>&1 | Out-String
if ($proxyOut -match "Direct access \(no proxy server\)") {
    Add-Result "winhttp proxy" $true "acesso direto"
} elseif ($proxyOut -match "Proxy Server\(s\)\s*:\s*(\S+)") {
    Add-Result "winhttp proxy" $true "proxy: $($Matches[1])"
} else {
    Add-Result "winhttp proxy" $true "saída: $($proxyOut.Trim().Split("`n")[0])"
}

if ($env:HTTPS_PROXY) {
    Add-Result "HTTPS_PROXY env" $true $env:HTTPS_PROXY
} else {
    Add-Result "HTTPS_PROXY env" $true "não setado"
}

try {
    $r = Invoke-WebRequest -Uri "https://api.anthropic.com" -Method Head -UseBasicParsing -TimeoutSec 10
    Add-Result "HTTPS api.anthropic.com" $true "status $($r.StatusCode)"
} catch {
    Add-Result "HTTPS api.anthropic.com" $false $_.Exception.Message
}

# ─── 6. UTF-8 ──────────────────────────────────────────────────────────
Write-Host ""
Write-Host "5. Console + encoding" -ForegroundColor Yellow
$enc = [Console]::OutputEncoding.WebName
Add-Result "encoding atual" $true $enc
if ($enc -eq "utf-8") {
    Add-Result "console UTF-8" $true "ok para acentos pt-BR"
} else {
    Add-Result "console UTF-8" $false "encoding $enc — install.ps1 vai ajustar via `$PROFILE"
}

# ─── 7. PowerShell version ─────────────────────────────────────────────
$psVer = $PSVersionTable.PSVersion
Add-Result "PowerShell version" $true "$psVer"
if ($psVer.Major -lt 7) {
    Write-Warning "  PowerShell 5.x detectado — considere instalar PowerShell 7+ via winget para melhor suporte UTF-8."
}

# ─── Resumo ────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
$failed = ($results | Where-Object { $_.Status -eq "FAIL" }).Count
$total  = $results.Count
if ($failed -eq 0) {
    Write-Host "  $total/$total verificações passaram. Bom pra instalar." -ForegroundColor Green
} else {
    Write-Host "  $failed/$total verificações falharam." -ForegroundColor Red
    Write-Host "  Revise os FAILs acima antes de rodar install.ps1." -ForegroundColor Yellow
}

# Salva relatório
$reportPath = Join-Path $PSScriptRoot "..\probe-report.txt"
$results | Format-Table -AutoSize | Out-String | Set-Content -Path $reportPath -Encoding UTF8
Write-Host ""
Write-Host "Relatório salvo em: $reportPath" -ForegroundColor DarkGray
