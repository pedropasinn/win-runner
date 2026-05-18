"""Memória entre tarefas — feature `(memory=queue)`.

Quando uma tarefa declara `(memory=queue)`:
- após o sucesso, gravamos `{ts, line, desc, summary}` em
  `state_dir/memory/<queue>_<block>_<model>.jsonl`.
- a próxima tarefa do MESMO (queue, block, model) com `(memory=queue)`
  recebe as últimas N entradas como contexto pré-prepended ao prompt.

Strict: só lê de runs anteriores que também opt-in. Nunca cruza filas
ou modelos diferentes — evita contexto "vazado" silenciosamente.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .paths import state_dir


MAX_ENTRIES = 5         # quantas entradas anteriores injetar
MAX_BYTES_TOTAL = 6000  # corte de segurança (descarta entradas mais velhas)


def _slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", s.strip()).strip("_")
    return s[:80] or "default"


def memory_path(queue: str, block: str, model: str | None) -> Path:
    d = state_dir() / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{_slug(queue)}__{_slug(block)}__{_slug(model or 'default')}.jsonl"


@dataclass
class Entry:
    ts: str
    line: int
    desc: str
    summary: str


def record_completion(
    queue: str,
    *,
    line: int,
    block: str,
    model: str | None,
    desc: str,
    summary: str,
) -> None:
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "line": line,
        "desc": desc[:400],
        "summary": summary[:2000],
    }
    p = memory_path(queue, block, model)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def latest_for(
    queue: str,
    *,
    block: str,
    model: str | None,
    limit: int = MAX_ENTRIES,
) -> list[Entry]:
    p = memory_path(queue, block, model)
    if not p.exists():
        return []
    entries: list[Entry] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        entries.append(Entry(
            ts=obj.get("ts", ""),
            line=obj.get("line", 0),
            desc=obj.get("desc", ""),
            summary=obj.get("summary", ""),
        ))
    return entries[-limit:]


def build_context(entries: Iterable[Entry]) -> str:
    if not entries:
        return ""
    parts: list[str] = ["[Memória da fila — últimas tarefas concluídas no mesmo bloco/modelo:]"]
    running_bytes = len(parts[0].encode("utf-8"))
    for e in list(entries):
        block = (
            f"\n— L{e.line} ({e.ts}): {e.desc}\n  resumo: {e.summary}"
        )
        bsize = len(block.encode("utf-8"))
        if running_bytes + bsize > MAX_BYTES_TOTAL:
            break
        parts.append(block)
        running_bytes += bsize
    parts.append("\n[Fim da memória. A tarefa atual segue abaixo.]\n")
    return "".join(parts)


def inject_into_prompt(prompt: str, context: str) -> str:
    if not context:
        return prompt
    return f"{context}\n\n{prompt}"
