# install.ps1 — bootstrap user-mode do win-runner em Windows.
#
# Não exige admin. Faz:
#   1. Verifica Python 3.11+ e claude CLI no PATH.
#   2. Cria venv em %USERPROFILE%\.local\win-runner-venv.
#   3. pip install -e . (modo dev — para receber updates via git pull sem reinstalar).
#   4. Cria shim win-runner.cmd em %USERPROFILE%\.local\bin.
#   5. Adiciona %USERPROFILE%\.local\bin ao PATH user (sem admin).
#   6. Cria diretórios de state.
#   7. Adiciona UTF-8 ao $PROFILE.
#
# Rode com: powershell -ExecutionPolicy Bypass -File install.ps1

[CmdletBinding()]
param(
    [switch]$SkipPython,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host "▶ $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  ✓ $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  ! $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "  ✗ $msg" -ForegroundColor Red }

$RepoRoot = $PSScriptRoot
$VenvDir  = Join-Path $env:USERPROFILE ".local\win-runner-venv"
$BinDir   = Join-Path $env:USERPROFILE ".local\bin"
$StateDir = Join-Path $env:LOCALAPPDATA "win-runner"

# ─── 1. Verifica Python ────────────────────────────────────────────────
Write-Step "verificando Python 3.11+"
$pythonExe = $null
foreach ($cmd in @("python3.11", "python3.12", "python3", "python", "py")) {
    $p = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($p) {
        $verRaw = & $p.Source --version 2>&1
        if ($verRaw -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -eq 3 -and $minor -ge 11) {
                $pythonExe = $p.Source
                Write-Ok "encontrado: $pythonExe ($verRaw)"
                break
            }
        }
    }
}
if (-not $pythonExe -and -not $SkipPython) {
    Write-Err "Python 3.11+ não encontrado no PATH."
    Write-Host @"

  Instale (user-mode, sem admin):
    winget install Python.Python.3.11 --scope user

  ou baixe de https://www.python.org/downloads/ e marque "Install for me only".

  Se quiser pular essa verificação (caso instale manualmente depois),
  rode: install.ps1 -SkipPython
"@
    exit 1
}

# ─── 2. Verifica claude CLI ────────────────────────────────────────────
Write-Step "verificando claude CLI"
$claude = Get-Command claude -ErrorAction SilentlyContinue
if (-not $claude) {
    Write-Warn "claude CLI não está no PATH."
    Write-Host @"

  Instale o CLI (user-mode):
    npm config set prefix "$env:USERPROFILE\.npm-global"
    npm install -g @anthropic-ai/claude-code
    # adicione $env:USERPROFILE\.npm-global ao PATH user

  Defina ANTHROPIC_API_KEY como variável de ambiente do usuário antes de rodar.
  Setup pode continuar — claude será cobrado só quando você der win-runner run.
"@
} else {
    Write-Ok "encontrado: $($claude.Source)"
}

# ─── 3. Cria venv ──────────────────────────────────────────────────────
Write-Step "criando venv em $VenvDir"
if ((Test-Path $VenvDir) -and -not $Force) {
    Write-Ok "venv já existe (use -Force para recriar)"
} else {
    if (Test-Path $VenvDir) { Remove-Item -Recurse -Force $VenvDir }
    & $pythonExe -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Err "falha ao criar venv"
        exit 1
    }
    Write-Ok "venv criado"
}

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    # Linux/WSL (dev): venv usa bin/
    $VenvPython = Join-Path $VenvDir "bin/python"
}

# ─── 4. pip install ────────────────────────────────────────────────────
Write-Step "instalando dependências (pip install -e .)"
# Respeita proxy corporativo se HTTPS_PROXY estiver setado
$pipArgs = @("install", "--upgrade", "pip")
if ($env:HTTPS_PROXY) {
    Write-Ok "usando proxy HTTPS_PROXY=$env:HTTPS_PROXY"
    $pipArgs += "--proxy", $env:HTTPS_PROXY
}
& $VenvPython -m pip $pipArgs
if ($LASTEXITCODE -ne 0) { Write-Err "pip upgrade falhou"; exit 1 }

$installArgs = @("install", "-e", $RepoRoot)
if ($env:HTTPS_PROXY) { $installArgs += "--proxy", $env:HTTPS_PROXY }
& $VenvPython -m pip $installArgs
if ($LASTEXITCODE -ne 0) {
    Write-Err "pip install -e . falhou"
    exit 1
}
Write-Ok "pacote instalado"

# ─── 5. Shim em ~/.local/bin ───────────────────────────────────────────
Write-Step "criando shim win-runner.cmd em $BinDir"
if (-not (Test-Path $BinDir)) { New-Item -ItemType Directory -Path $BinDir | Out-Null }

$ShimPath = Join-Path $BinDir "win-runner.cmd"
$shimContent = @"
@echo off
"$VenvPython" -m win_runner %*
"@
Set-Content -Path $ShimPath -Value $shimContent -Encoding ASCII
Write-Ok "shim criado: $ShimPath"

# ─── 6. PATH user ──────────────────────────────────────────────────────
Write-Step "adicionando $BinDir ao PATH user"
$currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($currentPath -split ";" -notcontains $BinDir) {
    $newPath = if ($currentPath) { "$BinDir;$currentPath" } else { $BinDir }
    [Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
    Write-Ok "PATH user atualizado (reabra terminal pra valer)"
} else {
    Write-Ok "PATH user já contém $BinDir"
}

# ─── 7. Diretórios de state ────────────────────────────────────────────
Write-Step "criando diretórios de state em $StateDir"
New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $StateDir "logs") -Force | Out-Null
Write-Ok "ok"

# ─── 8. UTF-8 no $PROFILE ──────────────────────────────────────────────
Write-Step "ajustando $PROFILE para UTF-8 (acentos pt-BR)"
$ProfileDir = Split-Path $PROFILE -Parent
if (-not (Test-Path $ProfileDir)) {
    New-Item -ItemType Directory -Path $ProfileDir -Force | Out-Null
}
if (-not (Test-Path $PROFILE)) { New-Item -ItemType File -Path $PROFILE | Out-Null }

$utf8Block = @"
# win-runner: garante console UTF-8 (pt-BR sem mojibake)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
`$OutputEncoding = [System.Text.Encoding]::UTF8
"@
$profileContent = if (Test-Path $PROFILE) { Get-Content $PROFILE -Raw } else { "" }
if ($profileContent -notmatch "win-runner: garante console UTF-8") {
    Add-Content -Path $PROFILE -Value "`n$utf8Block`n"
    Write-Ok "bloco UTF-8 adicionado a $PROFILE"
} else {
    Write-Ok "$PROFILE já tem o bloco UTF-8"
}

Write-Host ""
Write-Host "═════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  ✓ win-runner instalado." -ForegroundColor Green
Write-Host "═════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host "  Abra uma NOVA janela PowerShell e teste:" -ForegroundColor Yellow
Write-Host "    win-runner --help"
Write-Host "    win-runner list"
Write-Host "    win-runner run hello"
Write-Host ""
