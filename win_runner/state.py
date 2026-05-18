"""state.jsonl — eventos append-only por fila.

Cada fila tem um arquivo `<queue>.jsonl` em `state_dir()` com 1 evento
por linha. Eventos típicos:

  run_start, run_end, block_start, block_done,
  task_start, task_done, task_failed, verify_pass, verify_fail,
  escalation, rate_limit.

Lock no fd do arquivo durante o write atômico para serializar com
runners paralelos (improvável neste runner V0.1 mas barato e defensivo).
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .paths import state_dir

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    import msvcrt  # type: ignore[import-not-found]
else:
    import fcntl


def state_path(queue_name: str) -> Path:
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{queue_name}.jsonl"


def _lock_fd(fd: int) -> None:
    if _IS_WINDOWS:
        try:
            os.lseek(fd, 0, 0)
        except OSError:
            pass
        deadline = time.monotonic() + 10.0
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    return  # desistiu — segue sem lock (write ainda é < 4KB atômico)
                time.sleep(0.05)
    else:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError:
            pass


def _unlock_fd(fd: int) -> None:
    try:
        if _IS_WINDOWS:
            try:
                os.lseek(fd, 0, 0)
            except OSError:
                pass
            try:
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
    except OSError:
        pass


def append_event(queue_name: str, event: str, **fields: Any) -> dict:
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": event,
        **fields,
    }
    path = state_path(queue_name)
    with path.open("a", encoding="utf-8") as f:
        fd = f.fileno()
        try:
            _lock_fd(fd)
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            f.flush()
        finally:
            _unlock_fd(fd)
    return rec


def read_events(queue_name: str) -> Iterator[dict]:
    path = state_path(queue_name)
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def list_queues_with_state() -> list[str]:
    d = state_dir()
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.jsonl"))


def last_run_summary(queue_name: str) -> dict | None:
    """Resumo da última run: status, contagens, duração."""
    events = list(read_events(queue_name))
    if not events:
        return None
    # Última run = entre o último run_start e o run_end correspondente
    last_start_idx = None
    for i in range(len(events) - 1, -1, -1):
        if events[i].get("event") == "run_start":
            last_start_idx = i
            break
    if last_start_idx is None:
        return None
    run_events = events[last_start_idx:]
    end = next(
        (e for e in run_events if e.get("event") == "run_end"), None,
    )
    return {
        "started_at": events[last_start_idx].get("ts"),
        "ended_at": end.get("ts") if end else None,
        "exit": end.get("exit") if end else None,
        "duration_s": end.get("duration_s") if end else None,
        "reason": end.get("reason") if end else None,
        "task_done": sum(1 for e in run_events if e.get("event") == "task_done"),
        "task_failed": sum(1 for e in run_events if e.get("event") == "task_failed"),
        "events": len(run_events),
    }
