"""Router heurístico para `(model=auto)`.

Classifica a descrição da tarefa por sinais lexicais simples (sem
embeddings, sem KNN, sem DB de histórico — V0.2 enxuto). Custo zero,
explica a decisão.

Regras:

1. Verbos/substantivos de **alta complexidade** → opus.
   (refactor, arquitetura, design, prove, demonstre, otimize, modelo,
   algoritmo, deriv*, prov*, teorema...)
2. Verbos/substantivos de **baixa complexidade** → haiku.
   (renomeie, mova, formate, remova, liste, atualize README, fix typo...)
3. Descrição > 400 chars → opus (provavelmente tarefa rica em contexto).
4. Default → sonnet.

Saída inclui `reason` curto para logar no JSONL e no terminal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Decision:
    spec: str
    rule: str
    reason: str
    score: float


_OPUS_KEYWORDS = [
    "refator", "refactor", "arquitetura", "architecture",
    "design", "modelo formal", "modele", "model the",
    "prove", "demonstr", "derive", "deriv", "teorema", "theorem",
    "otimiz", "optimi", "algoritm", "algorithm", "complexidade",
    "advoga", "argumente contra", "critique",
    "estratégia", "strategy", "racioc", "reason about",
    "trade-off", "tradeoffs", "implicações",
]

_HAIKU_KEYWORDS = [
    "renomei", "rename ", "mova ", "move ",
    "formate", "format ", "remova ", "remove ",
    "liste ", "list ", "imprima ", "print ",
    "saudação", "saudaç",
    "fix typo", "corrigir typo",
    "atualize o readme", "update readme",
    "comente ", "add comment", "remove comment",
    "ajuste imports", "fix imports", "organize imports",
    "echo", "olá", "hello",
]


_WORD_BOUNDARY_OPUS = [re.compile(r"\b" + re.escape(k), re.IGNORECASE) for k in _OPUS_KEYWORDS]
_WORD_BOUNDARY_HAIKU = [re.compile(r"\b" + re.escape(k), re.IGNORECASE) for k in _HAIKU_KEYWORDS]


def explain(
    description: str,
    *,
    category: str | None = None,
    language: str | None = None,  # placeholder p/ futuro
) -> Decision:
    desc = description or ""
    desc_len = len(desc)

    # Sinal por categoria explícita ganha prioridade.
    if category:
        cat = category.lower()
        if cat in ("refactor", "design", "architecture", "research"):
            return Decision(
                spec="opus", rule="category",
                reason=f"category={category} → opus",
                score=1.0,
            )
        if cat in ("cleanup", "rename", "format", "docs", "typo"):
            return Decision(
                spec="haiku", rule="category",
                reason=f"category={category} → haiku",
                score=1.0,
            )

    n_opus = sum(1 for r in _WORD_BOUNDARY_OPUS if r.search(desc))
    n_haiku = sum(1 for r in _WORD_BOUNDARY_HAIKU if r.search(desc))

    if n_opus and n_opus >= n_haiku:
        return Decision(
            spec="opus", rule="keywords",
            reason=f"{n_opus} keyword(s) de alta complexidade",
            score=min(1.0, 0.5 + 0.1 * n_opus),
        )
    if n_haiku > n_opus:
        return Decision(
            spec="haiku", rule="keywords",
            reason=f"{n_haiku} keyword(s) mecânicas/rápidas",
            score=min(1.0, 0.5 + 0.1 * n_haiku),
        )
    if desc_len > 400:
        return Decision(
            spec="opus", rule="length",
            reason=f"descrição com {desc_len} chars (>400) → opus",
            score=0.6,
        )
    return Decision(
        spec="sonnet", rule="default",
        reason="sem sinal forte → sonnet",
        score=0.4,
    )
