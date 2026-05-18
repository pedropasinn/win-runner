"""Tests das operações atômicas no .md."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from win_runner.queue import (
    claim_next_pending_in_block,
    mark_line,
    reclaim_zombies,
)


def _write(tmp_path: Path, content: str) -> Path:
    f = tmp_path / "q.md"
    f.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")
    return f


def test_mark_line(tmp_path):
    q = _write(tmp_path, """
        ## a
        - [ ] um
        - [ ] dois
    """)
    mark_line(q, 2, "x")
    content = q.read_text(encoding="utf-8")
    assert "- [x] um" in content
    assert "- [ ] dois" in content


def test_mark_line_invalid_mark(tmp_path):
    q = _write(tmp_path, "## a\n- [ ] t\n")
    with pytest.raises(ValueError):
        mark_line(q, 2, "Q")


def test_mark_line_out_of_range(tmp_path):
    q = _write(tmp_path, "## a\n- [ ] t\n")
    with pytest.raises(ValueError):
        mark_line(q, 99, "x")


def test_claim_next_pending_in_block(tmp_path):
    q = _write(tmp_path, """
        ## bloco-a
        - [x] já feito
        - [ ] pendente um
        - [ ] pendente dois
        ## bloco-b
        - [ ] outro bloco
    """)
    line = claim_next_pending_in_block(q, "bloco-a")
    assert line == 3  # primeira pendente do bloco-a
    content = q.read_text(encoding="utf-8")
    assert "- [~] pendente um" in content
    assert "- [ ] pendente dois" in content


def test_claim_respects_skip(tmp_path):
    q = _write(tmp_path, """
        ## a
        - [ ] um
        - [ ] dois
        - [ ] tres
    """)
    line = claim_next_pending_in_block(q, "a", skip_lines={2})
    assert line == 3


def test_claim_returns_none_when_empty(tmp_path):
    q = _write(tmp_path, """
        ## a
        - [x] feito
        - [x] feito
    """)
    assert claim_next_pending_in_block(q, "a") is None


def test_claim_unknown_block_returns_none(tmp_path):
    q = _write(tmp_path, "## a\n- [ ] t\n")
    assert claim_next_pending_in_block(q, "inexistente") is None


def test_reclaim_zombies(tmp_path):
    q = _write(tmp_path, """
        ## a
        - [~] zumbi um
        - [x] feito
        - [~] zumbi dois
    """)
    n = reclaim_zombies(q)
    assert n == 2
    content = q.read_text(encoding="utf-8")
    assert "- [ ] zumbi um" in content
    assert "- [ ] zumbi dois" in content
    assert "- [x] feito" in content


def test_reclaim_zombies_zero_when_none(tmp_path):
    q = _write(tmp_path, "## a\n- [ ] um\n- [x] dois\n")
    assert reclaim_zombies(q) == 0


def test_block_with_bloco_prefix(tmp_path):
    q = _write(tmp_path, """
        ## Bloco: meu_bloco
        - [ ] tarefa
    """)
    line = claim_next_pending_in_block(q, "meu_bloco")
    assert line == 2
