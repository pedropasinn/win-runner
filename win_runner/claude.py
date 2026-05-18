"""Wrapper sobre `claude --print` (Anthropic CLI).

Suporte a:
- output JSON estruturado (`--output-format json`) com tokens + custo;
- detecção de rate-limit no stderr/stdout (regex sobre mensagens
  conhecidas do CLI);
- `--continue` para reuso de sessão entre tarefas do mesmo modelo;
- timeout configurável via env `WIN_RUNNER_TIMEOUT` (default: sem
  timeout — Claude é lento e o usuário pode rodar tarefas longas).

Não inclui codex/gemini — V0.1 é só Claude (decisão do usuário).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


MODEL_ALIASES = {
    "opus": "claude-opus-4-7",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5",
}

# Mensagens do CLI quando bate limite (padrões observados em 2026).
_RATE_LIMIT_RE = re.compile(
    r"(usage limit|rate limit|too many requests|"
    r"resets? at|try again (?:at|in)|available (?:at|in))",
    re.IGNORECASE,
)


@dataclass
class ClaudeResult:
    rc: int
    stdout: str
    stderr: str
    rate_limited: bool
    rate_limit_text: str
    tokens_in: int | None
    tokens_out: int | None
    cache_read_tokens: int | None
    cache_creation_tokens: int | None
    cost_usd: float | None


def resolve_model(spec: str | None) -> str:
    """Apelido → ID Anthropic. ID completo passa direto. None = default do CLI."""
    if not spec:
        return ""
    bare = spec.split(":", 1)[-1] if ":" in spec else spec
    return MODEL_ALIASES.get(bare, bare)


def find_claude_bin() -> str | None:
    """Localiza o binário do claude CLI no PATH."""
    return shutil.which("claude")


def run_claude(
    prompt: str,
    work_dir: Path,
    *,
    model: str | None = None,
    use_continue: bool = False,
    output_format: str = "json",
    extra_args: list[str] | None = None,
) -> ClaudeResult:
    """Executa `claude --print` com prompt via stdin.

    Em Windows, `shell=False` invoca direto o `.cmd` (npm install global
    cria `claude.cmd` em `%APPDATA%\\npm`). Funciona se o PATH user tiver
    sido configurado.
    """
    bin_path = find_claude_bin()
    if bin_path is None:
        return ClaudeResult(
            rc=127, stdout="", stderr="claude CLI não encontrado no PATH",
            rate_limited=False, rate_limit_text="",
            tokens_in=None, tokens_out=None,
            cache_read_tokens=None, cache_creation_tokens=None, cost_usd=None,
        )

    cmd: list[str] = [bin_path, "--print"]
    if use_continue:
        cmd.append("--continue")
    if model:
        resolved = resolve_model(model)
        if resolved:
            cmd.extend(["--model", resolved])
    if output_format == "json":
        cmd.extend(["--output-format", "json"])
    cmd.append("--dangerously-skip-permissions")
    if extra_args:
        cmd.extend(extra_args)

    timeout_env = os.environ.get("WIN_RUNNER_TIMEOUT")
    timeout = int(timeout_env) if timeout_env else None

    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        return ClaudeResult(
            rc=124,
            stdout=e.stdout or "",
            stderr=f"[claude timeout após {timeout}s]",
            rate_limited=False, rate_limit_text="",
            tokens_in=None, tokens_out=None,
            cache_read_tokens=None, cache_creation_tokens=None, cost_usd=None,
        )
    except FileNotFoundError:
        return ClaudeResult(
            rc=127, stdout="", stderr="claude CLI não pôde ser invocado",
            rate_limited=False, rate_limit_text="",
            tokens_in=None, tokens_out=None,
            cache_read_tokens=None, cache_creation_tokens=None, cost_usd=None,
        )

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    rate_match = _RATE_LIMIT_RE.search(stderr) or _RATE_LIMIT_RE.search(stdout)
    rate_limited = rate_match is not None and proc.returncode != 0
    rate_limit_text = ""
    if rate_match:
        # Junta as ~3 linhas em volta do match para extrair horário.
        haystack = stderr if _RATE_LIMIT_RE.search(stderr) else stdout
        rate_limit_text = haystack

    tokens_in = tokens_out = None
    cache_read = cache_create = None
    cost = None
    parsed_result_text = ""

    if output_format == "json" and stdout.strip():
        # claude --output-format json pode emitir múltiplos objetos JSON
        # (stream events). O último/maior costuma ter o usage final.
        # Tentativa: parse linha-a-linha; pegar o envelope com usage.
        for line in stdout.splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            usage = obj.get("usage") or {}
            if usage:
                tokens_in = usage.get("input_tokens", tokens_in)
                tokens_out = usage.get("output_tokens", tokens_out)
                cache_read = usage.get("cache_read_input_tokens", cache_read)
                cache_create = usage.get("cache_creation_input_tokens", cache_create)
            if "total_cost_usd" in obj:
                cost = obj["total_cost_usd"]
            if "result" in obj and isinstance(obj["result"], str):
                parsed_result_text = obj["result"]
        # Tentativa parse global se nada veio linha-a-linha
        if not (tokens_in or tokens_out) and stdout.strip().startswith("{"):
            try:
                obj = json.loads(stdout)
                usage = obj.get("usage") or {}
                tokens_in = usage.get("input_tokens")
                tokens_out = usage.get("output_tokens")
                cache_read = usage.get("cache_read_input_tokens")
                cache_create = usage.get("cache_creation_input_tokens")
                cost = obj.get("total_cost_usd")
                if isinstance(obj.get("result"), str):
                    parsed_result_text = obj["result"]
            except json.JSONDecodeError:
                pass

    display_stdout = parsed_result_text if parsed_result_text else stdout

    return ClaudeResult(
        rc=proc.returncode,
        stdout=display_stdout,
        stderr=stderr,
        rate_limited=rate_limited,
        rate_limit_text=rate_limit_text,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cache_read_tokens=cache_read,
        cache_creation_tokens=cache_create,
        cost_usd=cost,
    )
