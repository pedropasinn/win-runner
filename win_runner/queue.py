"""Operações atômicas no arquivo .md da fila.

Lockfile dedicado `<queue>.lock` + `file_lock` cross-platform garantem
que read-modify-write seja serializado entre processos. Rename atômico
(`os.replace`) garante que crash no meio mantenha o original íntegro.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from .filelock import file_lock

VALID_MARKS = {" ", "~", "x", "!"}
_TASK_PREFIX_RE = re.compile(r"^- \[.\]")


def _lock_path(queue_path: Path) -> Path:
    return queue_path.with_suffix(queue_path.suffix + ".lock")


def _atomic_write(target: Path, text: str) -> None:
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=target.name + ".", suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def mark_line(queue_path: Path, line_num: int, mark: str) -> None:
    if mark not in VALID_MARKS:
        raise ValueError(f"mark inválida: {mark!r}")
    with file_lock(_lock_path(queue_path)):
        lines = queue_path.read_text(encoding="utf-8").splitlines(keepends=True)
        if not (1 <= line_num <= len(lines)):
            raise ValueError(f"line_num {line_num} fora do range 1..{len(lines)}")
        lines[line_num - 1] = _TASK_PREFIX_RE.sub(
            f"- [{mark}]", lines[line_num - 1], count=1,
        )
        _atomic_write(queue_path, "".join(lines))


def claim_next_pending_in_block(
    queue_path: Path,
    block_name: str,
    *,
    skip_lines: set[int] | None = None,
) -> int | None:
    """Marca a 1ª `- [ ]` do bloco como `[~]` e retorna line_num. None se nada."""
    target = block_name.strip().lower()
    skip = skip_lines or set()
    with file_lock(_lock_path(queue_path)):
        lines = queue_path.read_text(encoding="utf-8").splitlines(keepends=True)
        in_target = False
        in_comment = False
        claim_idx: int | None = None
        for idx, raw in enumerate(lines):
            if "<!--" in raw:
                in_comment = True
            if "-->" in raw:
                in_comment = False
                continue
            if in_comment:
                continue
            stripped = raw.strip()
            if stripped.startswith("## "):
                hdr = stripped[3:].strip()
                if hdr.lower().startswith("bloco: "):
                    hdr = hdr[7:].strip()
                in_target = hdr.lower() == target
                continue
            if not in_target:
                continue
            if re.match(r"^- \[ \]", stripped):
                line_num = idx + 1
                if line_num in skip:
                    continue
                claim_idx = idx
                break
        if claim_idx is None:
            return None
        lines[claim_idx] = re.sub(
            r"^- \[ \]", "- [~]", lines[claim_idx], count=1,
        )
        _atomic_write(queue_path, "".join(lines))
        return claim_idx + 1


def reclaim_zombies(queue_path: Path) -> int:
    """Reverte [~] → [ ]. Chamado no início de cada run."""
    text = queue_path.read_text(encoding="utf-8")
    new = re.sub(r"^- \[~\]", "- [ ]", text, flags=re.MULTILINE)
    if new == text:
        return 0
    n = sum(1 for line in text.splitlines() if line.startswith("- [~]"))
    with file_lock(_lock_path(queue_path)):
        _atomic_write(queue_path, new)
    return n
