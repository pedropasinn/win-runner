"""Auto-resume após rate-limit do Claude — equivalente Windows do `at`.

Estratégia: extrai horário de retomada da mensagem do CLI, agenda uma
tarefa one-shot no Task Scheduler user-level via `schtasks /create /sc
once /st HH:MM /sd dd/MM/yyyy /tn win-runner-resume-<id> /tr "..."`.

Não usa `/ru` — fica na conta do user logado, sem exigir admin.

Quando dispara, executa `win-runner run <fila>` e morre. Como é `/sc
once`, o Task Scheduler remove a entry automaticamente — mas como
algumas builds de Windows mantêm "completed tasks" no histórico,
oferecemos `cleanup_completed()` para listar e remover entries
expiradas.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path


RESUME_TASK_PREFIX = "win-runner-resume-"


def parse_when(text: str) -> datetime | None:
    """Extrai horário de retomada do texto do rate-limit. None = não encontrou."""
    if not text:
        return None

    # Forma intervalo: "try again in 2 hours" / "available in 45 minutes".
    # Testada PRIMEIRO porque "in 2 hours" colide com "at HH" se o regex
    # de horário aceitar números nus.
    m = re.search(
        r"(?:try again|retry|resets?|available)\s+in\s+"
        r"(\d+)\s+(hours?|minutes?|min)\b",
        text, re.IGNORECASE,
    )
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith("hour"):
            return datetime.now() + timedelta(hours=n)
        return datetime.now() + timedelta(minutes=n)

    # Forma horário absoluto: "resets at 3:45pm" / "try again at 15:45" /
    # "available at 8am". Exige presença explícita de ':MM' ou sufixo am/pm
    # para não casar com números nus de intervalo.
    m = re.search(
        r"(?:resets?|try again|available)\s+at\s+"
        r"(\d{1,2})(?::(\d{2}))?\s*([ap]m)?",
        text, re.IGNORECASE,
    )
    if m and (m.group(2) or m.group(3)):
        hour = int(m.group(1))
        minute = int(m.group(2) or "0")
        period = (m.group(3) or "").lower()
        if period == "pm" and hour < 12:
            hour += 12
        if period == "am" and hour == 12:
            hour = 0
        if not 0 <= hour <= 23:
            return None
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target

    return None


def _shim_command(queue_name: str, work_dir: Path) -> str:
    """Comando que o schtasks vai disparar quando o horário chegar.

    Usa o próprio `win-runner` do PATH user (criado pelo install.ps1).
    Define WIN_RUNNER_TASKS via env só se o caller passou um workspace
    explícito não-default.
    """
    if sys.platform == "win32":
        # `cmd /c` para encadear setlocal + chamada (schtasks /tr aceita até 261 chars)
        return f'cmd /c "cd /d {work_dir} && win-runner run {queue_name}"'
    # POSIX fallback (dev/testing) — usa shell padrão
    return f'sh -c "cd {work_dir} && win-runner run {queue_name}"'


def schedule_resume(
    rate_limit_text: str,
    queue_name: str,
    work_dir: Path,
    *,
    fallback_minutes: int = 60,
) -> tuple[bool, str, str]:
    """Agenda retomada. Retorna (sucesso, mensagem, task_name)."""
    when = parse_when(rate_limit_text)
    if when is None:
        when = datetime.now() + timedelta(minutes=fallback_minutes)

    # +1 min de margem — schtasks rejeita horários no passado
    if when <= datetime.now():
        when = datetime.now() + timedelta(minutes=1)

    run_id = uuid.uuid4().hex[:8]
    task_name = f"{RESUME_TASK_PREFIX}{queue_name}-{run_id}"

    if sys.platform != "win32":
        # Em dev (WSL/Linux), só logamos. Não temos schtasks.
        return (
            True,
            f"[dev mode] retomada simulada para {when:%Y-%m-%d %H:%M}",
            task_name,
        )

    tr = _shim_command(queue_name, work_dir)
    st = when.strftime("%H:%M")
    sd = when.strftime("%m/%d/%Y")  # schtasks aceita locale-dependent — MM/dd/yyyy é o mais comum

    cmd = [
        "schtasks", "/create",
        "/tn", task_name,
        "/tr", tr,
        "/sc", "once",
        "/st", st,
        "/sd", sd,
        "/f",  # overwrite se existir
    ]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        return False, "timeout chamando schtasks", task_name
    except FileNotFoundError:
        return False, "schtasks não encontrado no PATH", task_name

    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "falha desconhecida").strip()
        return False, f"schtasks /create falhou: {msg}", task_name

    return True, f"agendado para {when:%Y-%m-%d %H:%M} (tarefa: {task_name})", task_name


def list_pending_resumes() -> list[dict]:
    """Lista tarefas de resume registradas. Vazio em dev mode."""
    if sys.platform != "win32":
        return []
    try:
        proc = subprocess.run(
            ["schtasks", "/query", "/fo", "csv", "/nh"],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    rows: list[dict] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or RESUME_TASK_PREFIX not in line:
            continue
        # CSV: "TaskName","Next Run Time","Status"
        parts = [p.strip().strip('"') for p in line.split('","')]
        if len(parts) >= 3:
            rows.append({
                "task_name": parts[0].strip('"'),
                "next_run": parts[1],
                "status": parts[2].strip('"'),
            })
    return rows


def delete_resume(task_name: str) -> bool:
    if sys.platform != "win32":
        return True
    try:
        proc = subprocess.run(
            ["schtasks", "/delete", "/tn", task_name, "/f"],
            capture_output=True, text=True, timeout=10,
        )
        return proc.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def cleanup_completed() -> int:
    """Remove tarefas de resume com status 'Could not start' ou que já rodaram."""
    removed = 0
    for entry in list_pending_resumes():
        # Heurística: status vazio ou contendo "Could not" indica que pode limpar.
        # Em V0.1, conservador: só removemos quando explicitamente solicitado.
        if "could not" in entry.get("status", "").lower():
            if delete_resume(entry["task_name"]):
                removed += 1
    return removed
