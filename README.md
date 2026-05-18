# win-runner

Task runner **Windows-native** para filas de tarefas em `.md` disparando
o `claude` CLI (Anthropic) e o `gemini` CLI (Google). Pensado para rodar
em notebook corporativo sem WSL e sem permissão de admin — tudo vive em
`%USERPROFILE%`, daemons via Task Scheduler user-level, auto-resume após
rate-limit via `schtasks`.

Compatível em formato com o runner do monorepo Linux: uma fila escrita
para um roda no outro sem ajuste.

## O que tem (v0.2.0)

- **Runner** — parse de filas `.md`, dispatch para Claude/Gemini,
  marcação atômica `[ ]`/`[~]`/`[x]`/`[!]`, depends DAG, escalate chain.
- **Multi-provider** — Claude (opus/sonnet/haiku) + Gemini (pro/flash);
  sem codex/discord.
- **`model=auto`** — router heurístico baseado em palavras-chave da
  descrição + categoria. Sem KNN, sem ML — explicável em 1 linha.
- **`memory=queue`** — injeta as últimas N tarefas concluídas (mesmo
  bloco/modelo) no prompt da próxima. Strict.
- **Auto-resume schtasks** — quando bate rate-limit, agenda retomada
  one-shot no horário do reset.
- **Cron scheduler** — `(cron="m h dom mês dow")` vira entry no Task
  Scheduler via `win-runner schedule register`.
- **Status server** — `win-runner serve` em `http://127.0.0.1:9090`,
  dashboard HTML embutido + `/api/state` JSON + `/api/health`.
- **TUI Textual** — `win-runner tui`, lista de filas + log de execução +
  slash commands.

## Requisitos

- Windows 10/11
- Python 3.11+ user-mode (`winget install Python.Python.3.11 --scope user` ou python.org)
- `claude` CLI autenticado (`npm install -g @anthropic-ai/claude-code`)
- `gemini` CLI autenticado (Google Cloud / OAuth) — opcional, só se você
  usar `(model=gemini:*)` em alguma fila.
- `ANTHROPIC_API_KEY` em env user

Não precisa de admin para nenhuma das instalações acima — todas suportam modo user.

## Instalação

EDR corporativo bloqueia scripts PowerShell longos que invocam
`winget + setx + schtasks` em sequência (parece reconnaissance).
Em vez de tentar contornar com assinatura, o setup é **manual** —
~15 comandos curtos pra colar um por vez no PowerShell.

**Siga**: [`docs/windows-setup-manual.md`](docs/windows-setup-manual.md)

Resumão (~10 min total):

1. Verificar Python 3.11+, claude CLI, schtasks user-level.
2. Instalar Python via winget user-scope (ou python.org manual).
3. Instalar `@anthropic-ai/claude-code` via npm user-scope.
4. `git clone` deste repo em `%USERPROFILE%\repo\win-runner`.
5. Criar venv e `pip install -e .`.
6. Criar shim `win-runner.cmd` em `%USERPROFILE%\.local\bin`.
7. Adicionar `%USERPROFILE%\.local\bin` ao PATH (via GUI).
8. Configurar UTF-8 no `$PROFILE`.
9. `win-runner run hello`.

## Uso

```powershell
# Listar filas disponíveis
win-runner list

# Rodar uma fila
win-runner run hello

# Encadear múltiplas filas
win-runner run hello refactor docs

# Status da última execução
win-runner status hello

# Histórico recente
win-runner history --limit 10

# Re-rodar todos os (verify=...) de uma fila concluída
win-runner verify-all hello

# Agendar tarefas recorrentes (lê (cron=...) das filas)
win-runner schedule register sync
win-runner schedule list
win-runner schedule unregister sync

# Status server local
win-runner serve                  # http://127.0.0.1:9090
# (Ctrl-C para parar; persistir como daemon: scripts\register-daemons.ps1)

# TUI interativa
win-runner tui
# /run hello, /status hello, /stop, /quit
```

## Formato de fila

```markdown
<!-- workspace: C:\Users\pedro\repo\meu-projeto -->
# Fila: refatoração do módulo auth

## Bloco: extração

- [ ] (model=sonnet) extrair middleware para arquivo próprio
- [ ] (model=opus, verify="cd $WORK_DIR && python -m pytest tests/auth") testar token expirado
- [ ] (model=sonnet, escalate=opus, depends=2) atualizar README

## Bloco: limpeza

- [ ] (model=sonnet, category=cleanup) remover imports não usados
- [ ] (id=backup, cron="0 3 * * *") backup diário do state
```

### Anotações suportadas

| Anotação | Função |
|---|---|
| `(model=X)` | `sonnet`/`opus`/`haiku` (Claude), `gemini:pro`/`gemini:flash`, `auto` (router decide), ou ID completo. |
| `(verify="cmd")` | Comando executado após a tarefa; exit ≠ 0 = falha. Em Windows é `cmd.exe`; o runner detecta bashisms e usa `bash -c` automaticamente se Git Bash estiver no PATH. |
| `(escalate=a,b,...)` | Cadeia de fallback. Pode misturar providers: `(escalate=sonnet,gemini:pro,opus)`. |
| `(memory=queue)` | Injeta resumo das últimas tarefas `[x]` do mesmo bloco/modelo no prompt da próxima. |
| `(id=tag)` | Tag estável para `depends`. |
| `(depends=N|tag,...)` | Aguarda essas linhas/tags ficarem `[x]` antes de rodar. |
| `(category=X)` | Rótulo livre; também influencia o router quando `model=auto`. |
| `(cron="m h dom mês dow")` | Recorrência; `win-runner schedule register <fila>` cria entry no Task Scheduler. |

### Router `model=auto`

Heurística simples (sem ML):
- `category=refactor`/`design`/`architecture`/`research` → **opus**
- `category=cleanup`/`rename`/`format`/`docs`/`typo` → **haiku**
- Descrição contém "refator/arquitetura/prove/otimize/algoritmo/..." → **opus**
- Descrição contém "renomeie/mova/formate/remova/imprima/echo/..." → **haiku**
- Descrição > 400 chars → **opus**
- Default → **sonnet**

A decisão é logada no JSONL (`auto_route` event) com `rule` e `reason`
para você poder auditar depois.

### Marcadores

| Marca | Significado |
|---|---|
| `- [ ]` | Pendente |
| `- [~]` | Em execução |
| `- [x]` | Concluída |
| `- [!]` | Falhou em todos os tiers |

## Auto-resume após rate-limit

Quando o `claude` CLI retorna mensagem de "usage limit / resets at ...", o
runner:

1. Reverte a tarefa atual para `[ ]`.
2. Extrai o horário de reset.
3. Cria uma tarefa única no Task Scheduler (`schtasks /create /sc once
   /st HH:MM /sd dd/MM/yyyy /tn win-runner-resume-<id>`).
4. Encerra limpo. No horário marcado, a tarefa dispara `win-runner run
   <fila>` automaticamente.

Veja com `schtasks /query /tn "win-runner-resume-*"` ou via
`win-runner resume list`.

## Filas recorrentes (cron)

Tarefas com `(cron=...)` são registradas no Task Scheduler user-level pelo
comando `win-runner schedule register <fila>`. Tradução de cron para
schtasks:

| Cron | schtasks |
|---|---|
| `0 3 * * *` | `/sc daily /st 03:00` |
| `0 9 * * 1` | `/sc weekly /d MON /st 09:00` |
| `0 6 1 * *` | `/sc monthly /d 1 /st 06:00` |
| `*/15 * * * *` | `/sc minute /mo 15` |

Expressões mais complexas (ranges em campos diferentes de dia-da-semana,
listas com vírgula em hora, etc.) levantam erro com mensagem clara.

## Onde os dados vivem

| Tipo | Linux (dev) | Windows |
|---|---|---|
| Filas `.md` | `<repo>/tasks/` | `<repo>\tasks\` |
| Eventos JSONL | `~/.local/share/win-runner/` | `%LOCALAPPDATA%\win-runner\` |
| Logs | `~/.local/share/win-runner/logs/` | `%LOCALAPPDATA%\win-runner\logs\` |
| Outcome temp | `/tmp/` | `%TEMP%\` |

## Compatibilidade com monorepo Linux

As filas usam **o mesmo formato** do `runner` do monorepo (mesmas
anotações, mesmos marcadores, mesmo `<!-- workspace: ... -->`). Você pode
mover `.md` entre os dois projetos sem ajuste. O que **não** é
compartilhado:

- `tasks/.state/` (eventos JSONL ficam em paths diferentes por SO).
- Bash scripts secundários do monorepo (doctor, gradus, sync-drive) **não
  têm equivalente** aqui — esses ficam exigindo WSL/Linux.
- Provedores extras (`gemini:*`, `codex:*`) **não** estão presentes — só
  Claude (Anthropic).

## Troubleshooting

### "claude: command not found"

Instale o CLI: `npm install -g @anthropic-ai/claude-code` (npm user-mode
sem admin: `npm config set prefix "$env:USERPROFILE\.npm-global"` antes).

### Erro de proxy corporativo

Defina `HTTPS_PROXY` e `HTTP_PROXY` em variáveis de ambiente do user
(System Properties → Environment Variables → User). `pip`, `npm` e
`claude` respeitam.

### Acentos quebram no terminal

Use Windows Terminal + PowerShell 7+. Em PowerShell 5, adicione ao
`$PROFILE`:

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
```

### Task Scheduler nega criar tarefa user-level

Rodar `schtasks /create /tn test /tr cmd /sc once /st 23:59` no
PowerShell deve funcionar sem admin. Se falhar com "Access denied", TI
provavelmente desabilitou — não há contorno user-mode; abrir ticket.

## Daemons persistentes (opcional)

Pra subir o status server no logon, ver `docs/windows-setup-manual.md`
§9 — é uma linha de `schtasks /create` que você cola direto, sem
script.

## Estado atual

v0.2.0 — runner básico + auto-resume + cron + multi-provider
(claude/gemini) + memory + router auto + status server + TUI. Sem
Discord, sem codex, sem Slack — V3+ se aparecer demanda.
