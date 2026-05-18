"""Tests do módulo memory."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from win_runner import memory as mem


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("WIN_RUNNER_STATE", str(tmp_path))
    yield tmp_path


def test_record_then_latest(isolated_state):
    mem.record_completion(
        "queue1", line=10, block="alpha", model="sonnet",
        desc="primeira", summary="resumo 1",
    )
    mem.record_completion(
        "queue1", line=20, block="alpha", model="sonnet",
        desc="segunda", summary="resumo 2",
    )
    entries = mem.latest_for("queue1", block="alpha", model="sonnet")
    assert len(entries) == 2
    assert entries[-1].line == 20
    assert entries[-1].summary == "resumo 2"


def test_isolation_between_blocks(isolated_state):
    mem.record_completion(
        "q", line=1, block="A", model="sonnet", desc="x", summary="X",
    )
    mem.record_completion(
        "q", line=2, block="B", model="sonnet", desc="y", summary="Y",
    )
    a = mem.latest_for("q", block="A", model="sonnet")
    b = mem.latest_for("q", block="B", model="sonnet")
    assert len(a) == 1 and a[0].summary == "X"
    assert len(b) == 1 and b[0].summary == "Y"


def test_isolation_between_models(isolated_state):
    mem.record_completion(
        "q", line=1, block="A", model="sonnet", desc="x", summary="S",
    )
    mem.record_completion(
        "q", line=2, block="A", model="opus", desc="y", summary="O",
    )
    s = mem.latest_for("q", block="A", model="sonnet")
    o = mem.latest_for("q", block="A", model="opus")
    assert len(s) == 1 and s[0].summary == "S"
    assert len(o) == 1 and o[0].summary == "O"


def test_build_context_truncates(isolated_state):
    big = "x" * 5000
    for i in range(10):
        mem.record_completion(
            "q", line=i, block="A", model="sonnet",
            desc=f"tarefa {i}", summary=big,
        )
    entries = mem.latest_for("q", block="A", model="sonnet", limit=10)
    ctx = mem.build_context(entries)
    # Truncado pelo MAX_BYTES_TOTAL
    assert len(ctx.encode("utf-8")) <= mem.MAX_BYTES_TOTAL + 200  # margem


def test_inject_into_prompt(isolated_state):
    prompt = "faça X"
    ctx = "[contexto]"
    out = mem.inject_into_prompt(prompt, ctx)
    assert out.startswith("[contexto]")
    assert prompt in out


def test_inject_empty_context_returns_prompt(isolated_state):
    assert mem.inject_into_prompt("prompt", "") == "prompt"


def test_latest_empty_when_no_records(isolated_state):
    assert mem.latest_for("nada", block="X", model="opus") == []
