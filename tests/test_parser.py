"""Tests do parser de fila."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from win_runner.parser import (
    completed_lines,
    count_summary,
    expected_workspace,
    parse_queue,
    resolve_depends,
)


def _write(tmp_path: Path, content: str) -> Path:
    f = tmp_path / "q.md"
    f.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")
    return f


def test_parse_blocks_and_tasks(tmp_path):
    q = _write(tmp_path, """
        ## Bloco: extração

        - [ ] (model=sonnet) extrair X
        - [x] (model=opus) extrair Y
        - [~] (model=haiku) extrair Z

        ## limpeza

        - [!] tarefa que falhou
    """)
    blocks = parse_queue(q)
    assert len(blocks) == 2
    assert blocks[0].name == "extração"
    assert blocks[1].name == "limpeza"
    assert len(blocks[0].tasks) == 3
    assert blocks[0].tasks[0].status == "pending"
    assert blocks[0].tasks[1].status == "done"
    assert blocks[0].tasks[2].status == "running"
    assert blocks[1].tasks[0].status == "failed"


def test_annotations_extracted(tmp_path):
    q = _write(tmp_path, """
        ## bloco

        - [ ] (model=opus, verify="cd $WORK && pytest", escalate=sonnet,haiku) tarefa rica
    """)
    blocks = parse_queue(q)
    t = blocks[0].tasks[0]
    assert t.model == "opus"
    assert t.verify == "cd $WORK && pytest"
    assert t.escalate == ["sonnet", "haiku"]
    assert "tarefa rica" in t.description
    assert "model=" not in t.description


def test_depends_resolution(tmp_path):
    q = _write(tmp_path, """
        ## bloco

        - [ ] (id=primeiro, model=haiku) faça A
        - [ ] (depends=primeiro,3, model=haiku) faça B
        - [x] (model=opus) tarefa pronta
    """)
    blocks = parse_queue(q)
    deps_map = resolve_depends(blocks)
    # Linha 4 (faz B) depende da linha 3 (id=primeiro) e linha 3 numérica.
    # As linhas reais são: header=1, blank=2, task1=3, task2=4, task3=5.
    # (parse_queue conta linhas do arquivo)
    # id=primeiro está na linha 3; depends inclui "primeiro" (resolve para 3) e "3"
    b_line = blocks[0].tasks[1].line_num
    deps = deps_map[b_line]
    assert 3 in deps


def test_completed_lines(tmp_path):
    q = _write(tmp_path, """
        ## a
        - [x] tarefa 1
        - [ ] tarefa 2
        ## b
        - [x] tarefa 3
    """)
    blocks = parse_queue(q)
    done = completed_lines(blocks)
    assert len(done) == 2


def test_count_summary(tmp_path):
    q = _write(tmp_path, """
        ## a
        - [x] done
        - [ ] pend
        - [~] running
        - [!] fail
    """)
    blocks = parse_queue(q)
    done, running, failed, pending = count_summary(blocks)
    assert (done, running, failed, pending) == (1, 1, 1, 1)


def test_workspace_extracted(tmp_path):
    q = _write(tmp_path, """
        <!-- workspace: C:\\Users\\pedro\\projeto -->
        # Fila

        ## bloco
        - [ ] tarefa
    """)
    assert expected_workspace(q) == "C:\\Users\\pedro\\projeto"


def test_html_comments_ignored(tmp_path):
    q = _write(tmp_path, """
        ## bloco
        <!--
        - [ ] tarefa comentada que não deve ser parseada
        -->
        - [ ] tarefa real
    """)
    blocks = parse_queue(q)
    assert len(blocks[0].tasks) == 1


def test_invalid_cron_warns(tmp_path):
    q = _write(tmp_path, """
        ## bloco
        - [ ] (cron="abc") tarefa cron quebrado
    """)
    blocks = parse_queue(q)
    t = blocks[0].tasks[0]
    assert t.cron is None
    assert any("cron" in w for w in t.warnings)


def test_unknown_model_warns(tmp_path):
    q = _write(tmp_path, """
        ## bloco
        - [ ] (model=sonnnet) tarefa com typo
    """)
    blocks = parse_queue(q)
    t = blocks[0].tasks[0]
    assert any("sonnnet" in w for w in t.warnings)


def test_known_model_no_warn(tmp_path):
    q = _write(tmp_path, """
        ## bloco
        - [ ] (model=opus) tarefa válida
        - [ ] (model=sonnet) outra
        - [ ] (model=haiku) outra
    """)
    blocks = parse_queue(q)
    for t in blocks[0].tasks:
        assert not t.warnings, t.warnings
