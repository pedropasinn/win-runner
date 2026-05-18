"""Dispatch unificado entre Claude e Gemini.

Spec sintaxe: `<alias>` ou `<provider>:<alias>`. Default provider = claude.

  opus           → claude / claude-opus-4-7
  sonnet         → claude / claude-sonnet-4-6
  haiku          → claude / claude-haiku-4-5
  claude:<id>    → claude / id literal
  gemini:pro     → gemini / gemini-3.1-pro-preview
  gemini:flash   → gemini / gemini-3-flash-preview
  gemini:<id>    → gemini / id literal

Resultado normalizado em `ProviderResult` para o runner.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import claude as claude_mod
from . import gemini as gemini_mod


PROVIDERS = ("claude", "gemini")

# Para warnings do parser.
MODELS_PER_PROVIDER = {
    "claude": claude_mod.MODEL_ALIASES,
    "gemini": gemini_mod.GEMINI_ALIASES,
}


@dataclass
class ProviderResult:
    provider: str
    model_id: str
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


def parse_spec(spec: str | None) -> tuple[str, str]:
    """Devolve (provider, alias). Default provider = claude."""
    if not spec:
        return ("claude", "")
    if ":" in spec:
        provider, _, alias = spec.partition(":")
        provider = provider.strip().lower()
        if provider not in PROVIDERS:
            # Prefixo desconhecido → trata o spec inteiro como alias claude
            return ("claude", spec)
        return (provider, alias.strip())
    return ("claude", spec.strip())


def model_id_for(provider: str, alias: str) -> str:
    if provider == "claude":
        return claude_mod.resolve_model(alias)
    if provider == "gemini":
        return gemini_mod.resolve_model(alias)
    return alias


def run(
    spec: str | None,
    prompt: str,
    work_dir: Path,
    *,
    use_continue: bool = False,
) -> ProviderResult:
    """Dispatch e normaliza o resultado."""
    provider, alias = parse_spec(spec)

    if provider == "gemini":
        r = gemini_mod.run_gemini(prompt, work_dir, model=alias)
        return ProviderResult(
            provider=provider,
            model_id=gemini_mod.resolve_model(alias),
            rc=r.rc, stdout=r.stdout, stderr=r.stderr,
            rate_limited=r.rate_limited, rate_limit_text=r.rate_limit_text,
            tokens_in=r.tokens_in, tokens_out=r.tokens_out,
            cache_read_tokens=None, cache_creation_tokens=None,
            cost_usd=r.cost_usd,
        )

    # default = claude
    r = claude_mod.run_claude(
        prompt, work_dir,
        model=alias, use_continue=use_continue, output_format="json",
    )
    return ProviderResult(
        provider="claude",
        model_id=claude_mod.resolve_model(alias),
        rc=r.rc, stdout=r.stdout, stderr=r.stderr,
        rate_limited=r.rate_limited, rate_limit_text=r.rate_limit_text,
        tokens_in=r.tokens_in, tokens_out=r.tokens_out,
        cache_read_tokens=r.cache_read_tokens,
        cache_creation_tokens=r.cache_creation_tokens,
        cost_usd=r.cost_usd,
    )
