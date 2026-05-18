"""Wrapper sobre `gemini` CLI (Google).

Diferente do claude:
- sessão sempre fresca (sem `--continue` equivalente);
- tokens não vêm no stdout — telemetry log opcional, não implementado V0.2;
- rate-limit raro mas pode acontecer; detectamos via regex similar.

CLI esperado no PATH: `gemini` (Google Cloud / OAuth pré-autenticado).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


GEMINI_ALIASES = {
    "pro": "gemini-3.1-pro-preview",
    "flash": "gemini-3-flash-preview",
    # IDs completos passam direto
}

_RATE_LIMIT_RE = re.compile(
    r"(quota|rate limit|too many requests|resource exhausted|429|"
    r"try again (?:later|in)|retry (?:after|in))",
    re.IGNORECASE,
)


@dataclass
class GeminiResult:
    rc: int
    stdout: str
    stderr: str
    rate_limited: bool
    rate_limit_text: str
    tokens_in: int | None
    tokens_out: int | None
    cost_usd: float | None


def resolve_model(spec: str | None) -> str:
    if not spec:
        return ""
    bare = spec.split(":", 1)[-1] if ":" in spec else spec
    return GEMINI_ALIASES.get(bare, bare)


def find_gemini_bin() -> str | None:
    return shutil.which("gemini")


def run_gemini(
    prompt: str,
    work_dir: Path,
    *,
    model: str | None = None,
) -> GeminiResult:
    bin_path = find_gemini_bin()
    if bin_path is None:
        return GeminiResult(
            rc=127, stdout="", stderr="gemini CLI não encontrado no PATH",
            rate_limited=False, rate_limit_text="",
            tokens_in=None, tokens_out=None, cost_usd=None,
        )

    cmd: list[str] = [bin_path, "--prompt", prompt, "--yolo"]
    resolved = resolve_model(model)
    if resolved:
        cmd.extend(["--model", resolved])

    timeout_env = os.environ.get("WIN_RUNNER_TIMEOUT")
    timeout = int(timeout_env) if timeout_env else None

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        return GeminiResult(
            rc=124, stdout=e.stdout or "",
            stderr=f"[gemini timeout após {timeout}s]",
            rate_limited=False, rate_limit_text="",
            tokens_in=None, tokens_out=None, cost_usd=None,
        )
    except FileNotFoundError:
        return GeminiResult(
            rc=127, stdout="", stderr="gemini CLI não pôde ser invocado",
            rate_limited=False, rate_limit_text="",
            tokens_in=None, tokens_out=None, cost_usd=None,
        )

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    rate_match = _RATE_LIMIT_RE.search(stderr) or _RATE_LIMIT_RE.search(stdout)
    rate_limited = rate_match is not None and proc.returncode != 0
    rate_limit_text = (stderr if _RATE_LIMIT_RE.search(stderr) else stdout) if rate_match else ""

    return GeminiResult(
        rc=proc.returncode,
        stdout=stdout,
        stderr=stderr,
        rate_limited=rate_limited,
        rate_limit_text=rate_limit_text,
        tokens_in=None,
        tokens_out=None,
        cost_usd=None,
    )
