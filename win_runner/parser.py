"""Parse das filas .md em (Block, Task) preservando o formato do monorepo.

Anotações suportadas:
  (model=X)           — alias claude (opus/sonnet/haiku) ou ID Anthropic
  (verify="cmd")      — comando shell rodado após a tarefa
  (escalate=a,b,...)  — cadeia de fallback
  (id=tag)            — tag estável para depends
  (depends=N|tag,...) — dependências (line numbers ou tags)
  (category=X)        — rótulo livre (refactor, fix, cleanup...)
  (cron="m h dom mês dow") — recorrência; consumido por scheduler.py

Diferenças vs parser do monorepo Linux:
- sem (gemini:*) / (codex:*): só Claude.
- sem (memory=queue) / (ask_timeout=...): features fora do escopo V0.1.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

TASK_RE = re.compile(r"^- \[(.)\]\s*(.+)$")
BLOCK_RE = re.compile(r"^## (.+)$")
GROUPED_ANNOT_RE = re.compile(r"\(([^()]+)\)")
_KEY_RE = re.compile(r"^[a-z_][a-z0-9_]*$", re.IGNORECASE)
_CRON_FIELD_RE = re.compile(r"^[\d\*/,\-]+$")

STATUS_MAP = {
    " ": "pending",
    "~": "running",
    "x": "done",
    "!": "failed",
}

KNOWN_MODELS = {"opus", "sonnet", "haiku", "auto"}
KNOWN_GEMINI = {"pro", "flash"}


@dataclass
class Task:
    line_num: int
    status: str
    description: str
    model: str | None = None
    verify: str | None = None
    escalate: list[str] = field(default_factory=list)
    task_id: str | None = None
    depends: list[str] = field(default_factory=list)
    category: str | None = None
    cron: str | None = None
    memory: str | None = None  # 'queue' = injeta tarefas anteriores no prompt
    raw_annotations: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class Block:
    name: str
    line_num: int
    tasks: list[Task] = field(default_factory=list)

    @property
    def done(self) -> int:
        return sum(1 for t in self.tasks if t.status == "done")

    @property
    def total(self) -> int:
        return len(self.tasks)


def _split_annot_pairs(inner: str) -> list[str]:
    """Quebra `inner` por vírgula apenas quando o que vem depois é `<key>=`."""
    parts: list[str] = []
    cur: list[str] = []
    quote: str | None = None
    i = 0
    n = len(inner)
    while i < n:
        c = inner[i]
        if quote:
            cur.append(c)
            if c == quote:
                quote = None
            i += 1
            continue
        if c in ("'", '"'):
            quote = c
            cur.append(c)
            i += 1
            continue
        if c == ",":
            j = i + 1
            while j < n and inner[j].isspace():
                j += 1
            k = j
            while k < n and (inner[k].isalnum() or inner[k] == "_"):
                k += 1
            if k > j and k < n and inner[k] == "=":
                parts.append("".join(cur).strip())
                cur = []
                i += 1
                continue
        cur.append(c)
        i += 1
    if cur:
        parts.append("".join(cur).strip())
    return parts


def _extract_annotations(text: str) -> tuple[dict[str, str], str]:
    annots: dict[str, str] = {}

    def _consume(grouped_inner: str) -> None:
        for part in _split_annot_pairs(grouped_inner):
            if "=" not in part:
                continue
            k, _, v = part.partition("=")
            k = k.strip().lower()
            if not _KEY_RE.match(k):
                continue
            annots[k] = v.strip().strip("\"'")

    def _replace_grouped(m: re.Match) -> str:
        inner = m.group(1)
        first_eq = inner.find("=")
        if first_eq < 0:
            return m.group(0)
        first_key = inner[:first_eq].strip()
        if not _KEY_RE.match(first_key):
            return m.group(0)
        _consume(inner)
        return ""

    cleaned = GROUPED_ANNOT_RE.sub(_replace_grouped, text)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return annots, cleaned


def _validate_model(spec: str | None) -> list[str]:
    if not spec:
        return []
    if spec == "auto":
        return []
    if ":" in spec:
        prefix = spec.partition(":")[0].lower()
        if prefix not in ("claude", "gemini"):
            return [
                f"model spec '{spec}': prefixo '{prefix}:' não é suportado "
                f"em win-runner (apenas claude/gemini). Use 'opus'/'sonnet'/"
                f"'haiku' ou 'gemini:pro'/'gemini:flash'."
            ]
        bare = spec.partition(":")[2]
        known = KNOWN_GEMINI if prefix == "gemini" else KNOWN_MODELS
        if bare not in known and "-" not in bare and len(bare) <= 12:
            return [
                f"model spec '{spec}' não é apelido conhecido em {prefix} "
                f"({sorted(known)}); será passado como ID literal ao CLI"
            ]
        return []
    bare = spec
    if bare not in KNOWN_MODELS and "-" not in bare and len(bare) <= 12:
        return [
            f"model spec '{spec}' não é apelido conhecido "
            f"({sorted(KNOWN_MODELS)}); será passado como ID literal ao CLI"
        ]
    return []


def _validate_cron(spec: str) -> str | None:
    parts = spec.strip().split()
    if len(parts) != 5:
        return (
            f"cron inválido: '{spec}' (esperado 5 campos: "
            f"min hora dia mês dia-da-semana)"
        )
    for p in parts:
        if not _CRON_FIELD_RE.match(p):
            return f"cron com campo inválido: '{p}' em '{spec}'"
    return None


def _parse_task_line(line_num: int, marker: str, rest: str) -> Task:
    annots, desc = _extract_annotations(rest)
    warnings: list[str] = []

    model = annots.get("model")
    warnings.extend(_validate_model(model))

    escalate_raw = annots.get("escalate", "")
    escalate = [s.strip() for s in escalate_raw.split(",") if s.strip()]
    for tier in escalate:
        warnings.extend(_validate_model(tier))

    task_id = annots.get("id")
    if task_id and not _KEY_RE.match(task_id):
        warnings.append(f"id inválido: '{task_id}'")
        task_id = None

    depends_raw = annots.get("depends", "")
    depends: list[str] = []
    if depends_raw:
        for ref in [s.strip() for s in depends_raw.split(",") if s.strip()]:
            if ref.isdigit() or _KEY_RE.match(ref):
                depends.append(ref)
            else:
                warnings.append(f"depends inválido: '{ref}'")

    category = annots.get("category")
    if category and not _KEY_RE.match(category):
        warnings.append(f"category inválida: '{category}'")
        category = None

    cron = annots.get("cron")
    if cron:
        cron_warning = _validate_cron(cron)
        if cron_warning:
            warnings.append(cron_warning)
            cron = None

    memory = annots.get("memory")
    if memory and memory != "queue":
        warnings.append(
            f"memory spec '{memory}' desconhecido — use 'queue'"
        )
        memory = None

    return Task(
        line_num=line_num,
        status=STATUS_MAP.get(marker, "pending"),
        description=desc,
        model=model,
        verify=annots.get("verify"),
        escalate=escalate,
        task_id=task_id,
        depends=depends,
        category=category,
        cron=cron,
        memory=memory,
        raw_annotations=annots,
        warnings=warnings,
    )


def parse_queue(path: Path) -> list[Block]:
    if not path.exists():
        return []

    blocks: list[Block] = []
    current: Block | None = None
    in_comment = False

    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if "<!--" in line:
            in_comment = True
        if "-->" in line:
            in_comment = False
            continue
        if in_comment:
            continue

        bm = BLOCK_RE.match(line)
        if bm:
            name = bm.group(1).strip()
            if name.lower().startswith("bloco: "):
                name = name[7:].strip()
            current = Block(name=name, line_num=i)
            blocks.append(current)
            continue

        tm = TASK_RE.match(line)
        if tm and current is not None:
            current.tasks.append(_parse_task_line(i, tm.group(1), tm.group(2).strip()))

    return blocks


def expected_workspace(queue_path: Path) -> str | None:
    """Lê `<!-- workspace: ... -->` da fila, se houver."""
    if not queue_path.exists():
        return None
    text = queue_path.read_text(encoding="utf-8")
    m = re.search(r"<!--\s*workspace:\s*(\S+?)\s*-->", text)
    return m.group(1) if m else None


def list_queues(tasks_path: Path) -> list[Path]:
    if not tasks_path.exists():
        return []
    return sorted(
        f for f in tasks_path.glob("*.md") if not f.name.startswith(".")
    )


def count_summary(blocks: list[Block]) -> tuple[int, int, int, int]:
    done = running = failed = pending = 0
    for b in blocks:
        for t in b.tasks:
            if t.status == "done":
                done += 1
            elif t.status == "running":
                running += 1
            elif t.status == "failed":
                failed += 1
            else:
                pending += 1
    return done, running, failed, pending


def completed_lines(blocks: list[Block]) -> set[int]:
    return {t.line_num for b in blocks for t in b.tasks if t.status == "done"}


def resolve_depends(blocks: list[Block]) -> dict[int, list[int]]:
    """Para cada task com depends, resolve refs (tags ou números) para line_nums.

    Refs inválidas são silenciosamente ignoradas (já viraram warning no parser).
    """
    tag_to_line: dict[str, int] = {}
    for b in blocks:
        for t in b.tasks:
            if t.task_id:
                tag_to_line[t.task_id] = t.line_num
    out: dict[int, list[int]] = {}
    for b in blocks:
        for t in b.tasks:
            if not t.depends:
                continue
            lines: list[int] = []
            for ref in t.depends:
                if ref.isdigit():
                    lines.append(int(ref))
                elif ref in tag_to_line:
                    lines.append(tag_to_line[ref])
            out[t.line_num] = lines
    return out
