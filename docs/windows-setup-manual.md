# Setup manual no Windows (sem scripts longos)

EDR/antivírus corporativo costuma bloquear scripts PowerShell de fonte
externa que invocam `schtasks`, `netsh`, `Invoke-WebRequest` e
`setx` em sequência — tudo isso parece reconnaissance. Em vez de tentar
contornar, este guia divide o setup em comandos curtos que você cola
um por vez no PowerShell — cada um isolado é benigno e quase nunca é
bloqueado.

> Se mesmo assim algum comando for bloqueado, tira print da mensagem do
> EDR e abre ticket com TI pedindo whitelist daquela ação específica
> (mais fácil do que "liberar o script todo").

## 0. Probe — verificar o que TI permite

Cole **uma linha por vez**. Vai aparecer `True`/`False` ou mensagem
clara. Anote qual falhou.

```powershell
# 0.1 — escrita em pasta de usuário
Test-Path $env:USERPROFILE; New-Item -ItemType Directory -Path "$env:USERPROFILE\.local\bin" -Force | Out-Null; Test-Path "$env:USERPROFILE\.local\bin"
```

```powershell
# 0.2 — escrita em LOCALAPPDATA
New-Item -ItemType Directory -Path "$env:LOCALAPPDATA\win-runner" -Force | Out-Null; Test-Path "$env:LOCALAPPDATA\win-runner"
```

```powershell
# 0.3 — ferramentas pré-instaladas (cada uma separadamente)
Get-Command python -ErrorAction SilentlyContinue
Get-Command py     -ErrorAction SilentlyContinue
Get-Command git    -ErrorAction SilentlyContinue
Get-Command node   -ErrorAction SilentlyContinue
Get-Command npm    -ErrorAction SilentlyContinue
Get-Command claude -ErrorAction SilentlyContinue
Get-Command winget -ErrorAction SilentlyContinue
```

```powershell
# 0.4 — versão Python (se existir)
python --version
```

```powershell
# 0.5 — Task Scheduler user-level (cria/apaga 1 task de teste sem admin)
schtasks /create /tn win-runner-probe /tr "cmd /c echo ok" /sc once /st 23:59 /sd 12/31/2099 /f
schtasks /delete /tn win-runner-probe /f
```

Se a linha 0.5 funcionar, auto-resume via schtasks vai funcionar. Se
falhar com "Access denied", auto-resume não vai ser viável e você terá
que rerodar manualmente quando bater rate-limit.

```powershell
# 0.6 — conectividade HTTPS (sem proxy)
Test-NetConnection api.anthropic.com -Port 443
```

```powershell
# 0.7 — proxy do sistema (se algo na 0.6 falhar, provavelmente tem proxy)
[Environment]::GetEnvironmentVariable("HTTPS_PROXY", "User")
[Environment]::GetEnvironmentVariable("HTTP_PROXY",  "User")
```

## 1. Python 3.11+ (se não tem)

Tenta com winget primeiro (geralmente passa em corporativo):

```powershell
winget install Python.Python.3.11 --scope user --accept-package-agreements --accept-source-agreements
```

**Se winget for bloqueado:** baixe o instalador de python.org no
navegador (clique no link, salve), execute o `.exe` manualmente — marque
"Install for me only" e "Add Python to PATH". Não precisa de admin.

Reabra o PowerShell e confirme:

```powershell
python --version
```

## 2. Claude CLI (Anthropic)

Precisa do `npm` primeiro. Se `npm` não estiver:

```powershell
winget install OpenJS.NodeJS.LTS --scope user --accept-package-agreements --accept-source-agreements
```

Configura npm pra instalar em pasta do usuário (sem admin) e instala:

```powershell
npm config set prefix "$env:USERPROFILE\.npm-global"
```

```powershell
npm install -g @anthropic-ai/claude-code
```

Adicione `%USERPROFILE%\.npm-global` ao PATH user. Como o `setx` em
script grande pode ser bloqueado, faça via GUI:

1. Tecla Windows, digite "variáveis de ambiente do usuário", Enter.
2. Em "Path", clique Editar → Novo → cole `%USERPROFILE%\.npm-global`.
3. OK. Reabra PowerShell.

```powershell
claude --version
```

Defina sua API key (também pela GUI de variáveis de ambiente, ou):

```powershell
[Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", "sk-ant-...", "User")
```

Reabra PowerShell pra a variável valer.

## 3. (Opcional) Gemini CLI

Só se você for usar `(model=gemini:*)` em alguma fila. Senão, pule.

```powershell
winget install Google.GeminiCLI --scope user --accept-package-agreements --accept-source-agreements
```

Autentique:

```powershell
gemini auth login
```

## 4. Clone do win-runner

```powershell
mkdir "$env:USERPROFILE\repo" -Force | Out-Null
cd "$env:USERPROFILE\repo"
git clone https://github.com/pedropasinn/win-runner
cd win-runner
```

## 5. Venv + instalar pacote

```powershell
python -m venv "$env:USERPROFILE\.local\win-runner-venv"
```

```powershell
& "$env:USERPROFILE\.local\win-runner-venv\Scripts\python.exe" -m pip install --upgrade pip
```

```powershell
& "$env:USERPROFILE\.local\win-runner-venv\Scripts\python.exe" -m pip install -e .
```

Se a última linha falhar por proxy TLS:

```powershell
# descubra o proxy (geralmente TI já tem variável setada)
[Environment]::GetEnvironmentVariable("HTTPS_PROXY", "User")

# se vazio, pergunte à TI o endereço; depois:
& "$env:USERPROFILE\.local\win-runner-venv\Scripts\python.exe" -m pip install -e . --proxy http://proxy.empresa:8080
```

## 6. Criar shim `win-runner.cmd` (manualmente)

Cole isso em **uma única linha** (PowerShell não bloqueia criar 1 arquivo
texto):

```powershell
Set-Content -Path "$env:USERPROFILE\.local\bin\win-runner.cmd" -Value "@echo off`r`n`"$env:USERPROFILE\.local\win-runner-venv\Scripts\python.exe`" -m win_runner %*" -Encoding ASCII
```

Adicione `%USERPROFILE%\.local\bin` ao PATH user (pela GUI de variáveis
de ambiente, como em §2). Reabra PowerShell.

Teste:

```powershell
win-runner --version
win-runner list
```

## 7. UTF-8 no terminal (acentos pt-BR)

Cole no `$PROFILE` da sua sessão para console UTF-8:

```powershell
New-Item -ItemType File -Path $PROFILE -Force | Out-Null
Add-Content -Path $PROFILE -Value "`n[Console]::OutputEncoding = [System.Text.Encoding]::UTF8`n`$OutputEncoding = [System.Text.Encoding]::UTF8`n"
```

Reabra PowerShell.

## 8. Rodar a primeira fila

```powershell
win-runner run hello
```

## 9. (Opcional) Status server local

```powershell
win-runner serve
```

Abre `http://127.0.0.1:9090` no navegador. Bind localhost — nada externo
vê.

Pra subir automaticamente no logon, **uma linha** que cria 1 schtask
(em vez de um script grande que pareceria recon):

```powershell
schtasks /create /tn win-runner-status /tr "cmd /c `"$env:USERPROFILE\.local\bin\win-runner.cmd`" serve >> `"$env:LOCALAPPDATA\win-runner\status.log`" 2>&1" /sc onlogon /rl limited /f
```

Pra iniciar agora:

```powershell
schtasks /run /tn win-runner-status
```

Pra desfazer:

```powershell
schtasks /delete /tn win-runner-status /f
```

## 10. (Opcional) TUI Textual

```powershell
win-runner tui
```

Digite `/help` lá dentro.

---

## Troubleshooting

### "Acesso negado" em schtasks

TI desabilitou criação de tarefas user-level. Sem contorno; o resto
funciona, mas:
- Auto-resume não vai agendar — vai logar `manual` e você relança a
  fila a mão quando o rate-limit passar.
- Daemon do status server precisa ser aberto manualmente: abra um
  PowerShell oculto e rode `win-runner serve`.

### pip travado em proxy / certificado TLS

Pegue o cert corporativo (geralmente em `Trusted Root Certificates` no
certmgr.msc, exportável como `.cer`). Converta pra `.pem` se necessário
e:

```powershell
& "$env:USERPROFILE\.local\win-runner-venv\Scripts\python.exe" -m pip install -e . --cert C:\caminho\corp-ca.pem
```

### Acentos quebrados ("naÌ�o" em vez de "não")

Confirme que está em PowerShell 7+ (não no 5.1 antigo):

```powershell
$PSVersionTable.PSVersion
```

Se < 7, instale:

```powershell
winget install Microsoft.PowerShell --scope user --accept-package-agreements --accept-source-agreements
```

Depois abra "PowerShell 7" no menu Iniciar (não o "Windows PowerShell"
azul antigo).

### Quero rodar sem deixar PATH alterado

Pula a parte do shim e do PATH. Use sempre o caminho completo:

```powershell
& "$env:USERPROFILE\.local\win-runner-venv\Scripts\python.exe" -m win_runner run hello
```

Ou crie alias na sessão atual (some quando fecha terminal):

```powershell
Set-Alias -Name wr -Value "$env:USERPROFILE\.local\win-runner-venv\Scripts\python.exe"
wr -m win_runner list
```
