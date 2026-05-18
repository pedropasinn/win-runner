"""Scheduler recorrente — traduz `(cron=...)` para entries do Task Scheduler.

Quando uma tarefa de uma fila tem `(cron="m h dom mês dow")`, o usuário
roda `win-runner schedule register <fila>` para criar uma entry no Task
Scheduler que dispara `win-runner run <fila>` no horário definido.

Tradução suportada (subset pragmático do cron):

| Cron                | schtasks                                  |
|---------------------|-------------------------------------------|
| `M H * * *`         | `/sc daily /st HH:MM`                     |
| `M H * * D`         | `/sc weekly /d <DOW> /st HH:MM`           |
| `M H D * *`         | `/sc monthly /d D /st HH:MM`              |
| `*/N * * * *`       | `/sc minute /mo N`                        |
| `0 */N * * *`       | `/sc hourly /mo N`                        |

Casos com vírgulas, ranges, ou múltiplos campos com `*/N` não são
suportados e levantam `ValueError` com mensagem clara — esses casos são
raros em filas reais e a alternativa seria escrever um interpretador
cron completo.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .parser import Task, parse_queue
from .paths import tasks_dir

SCHEDULE_TASK_PREFIX = "win-runner-cron-"


@dataclass
class CronTranslation:
    args: list[str]  # argumentos extras para schtasks após /tn e /tr
    human: str       # descrição em pt-BR


_DOW_MAP = {
    "0": "SUN", "7": "SUN", "1": "MON", "2": "TUE",
    "3": "WED", "4": "THU", "5": "FRI", "6": "SAT",
}


def translate_cron(spec: str) -> CronTranslation:
    """Cron → flags schtasks. Levanta ValueError em casos não suportados."""
    parts = spec.strip().split()
    if len(parts) != 5:
        raise ValueError(f"cron precisa de 5 campos, recebi {len(parts)}: {spec!r}")
    minute, hour, dom, month, dow = parts

    # */N em minutos: "*/15 * * * *"
    m = re.fullmatch(r"\*/(\d+)", minute)
    if m and hour == "*" and dom == "*" and month == "*" and dow == "*":
        n = int(m.group(1))
        return CronTranslation(
            args=["/sc", "minute", "/mo", str(n)],
            human=f"a cada {n} minutos",
        )

    # */N em horas: "0 */N * * *"
    if minute == "0" and dom == "*" and month == "*" and dow == "*":
        m = re.fullmatch(r"\*/(\d+)", hour)
        if m:
            n = int(m.group(1))
            return CronTranslation(
                args=["/sc", "hourly", "/mo", str(n)],
                human=f"a cada {n} horas",
            )

    # Campos fixos
    if not minute.isdigit() or not hour.isdigit():
        raise ValueError(
            f"cron {spec!r}: campos de minuto/hora precisam ser inteiros "
            f"para tradução automática (ranges/listas não suportados em V0.1)"
        )
    st = f"{int(hour):02d}:{int(minute):02d}"

    # M H * * D — semanal
    if dom == "*" and month == "*" and dow != "*":
        if dow not in _DOW_MAP:
            raise ValueError(
                f"cron {spec!r}: dia-da-semana {dow!r} não suportado "
                f"(use 0-6 ou 7=domingo, sem listas)"
            )
        return CronTranslation(
            args=["/sc", "weekly", "/d", _DOW_MAP[dow], "/st", st],
            human=f"semanal toda {_DOW_MAP[dow]} às {st}",
        )

    # M H D * * — mensal
    if dom != "*" and month == "*" and dow == "*":
        if not dom.isdigit():
            raise ValueError(
                f"cron {spec!r}: dia-do-mês {dom!r} precisa ser inteiro"
            )
        return CronTranslation(
            args=["/sc", "monthly", "/d", str(int(dom)), "/st", st],
            human=f"mensal no dia {int(dom)} às {st}",
        )

    # M H * * * — diário
    if dom == "*" and month == "*" and dow == "*":
        return CronTranslation(
            args=["/sc", "daily", "/st", st],
            human=f"diariamente às {st}",
        )

    raise ValueError(
        f"cron {spec!r} usa combinação não suportada (combinar dom+dow, "
        f"month != *, etc.)"
    )


def task_id_for(queue_name: str, line: int) -> str:
    return f"{SCHEDULE_TASK_PREFIX}{queue_name}-L{line}"


def _shim_command(queue_name: str, work_dir: Path) -> str:
    if sys.platform == "win32":
        return f'cmd /c "cd /d {work_dir} && win-runner run {queue_name}"'
    return f'sh -c "cd {work_dir} && win-runner run {queue_name}"'


def register_cron_task(
    queue_name: str, task: Task, work_dir: Path,
) -> tuple[bool, str]:
    if not task.cron:
        return False, f"linha {task.line_num} não tem (cron=...)"
    try:
        trans = translate_cron(task.cron)
    except ValueError as e:
        return False, str(e)

    name = task_id_for(queue_name, task.line_num)

    if sys.platform != "win32":
        return True, f"[dev mode] registraria {name}: {trans.human}"

    cmd = [
        "schtasks", "/create",
        "/tn", name,
        "/tr", _shim_command(queue_name, work_dir),
        *trans.args,
        "/f",
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return False, f"schtasks falhou: {e}"
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "erro desconhecido").strip()
    return True, f"registrado: {name} ({trans.human})"


def register_queue(queue_name: str, work_dir: Path) -> list[tuple[bool, str]]:
    """Registra todas as tarefas com (cron=...) de uma fila."""
    queue_path = tasks_dir() / f"{queue_name}.md"
    if not queue_path.exists():
        return [(False, f"fila {queue_name} não existe em {queue_path}")]
    blocks = parse_queue(queue_path)
    results: list[tuple[bool, str]] = []
    found_any = False
    for b in blocks:
        for t in b.tasks:
            if t.cron:
                found_any = True
                results.append(register_cron_task(queue_name, t, work_dir))
    if not found_any:
        results.append((False, f"fila {queue_name} não tem nenhuma tarefa com (cron=...)"))
    return results


def list_registered() -> list[dict]:
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
    rows: list[dict] = []
    for line in proc.stdout.splitlines():
        if SCHEDULE_TASK_PREFIX not in line:
            continue
        parts = [p.strip().strip('"') for p in line.split('","')]
        if len(parts) >= 3:
            rows.append({
                "task_name": parts[0].strip('"'),
                "next_run": parts[1],
                "status": parts[2].strip('"'),
            })
    return rows


def unregister_queue(queue_name: str) -> list[tuple[bool, str]]:
    """Remove todas as entries cron de uma fila."""
    prefix = f"{SCHEDULE_TASK_PREFIX}{queue_name}-L"
    results: list[tuple[bool, str]] = []
    for entry in list_registered():
        name = entry["task_name"]
        if not name.startswith(prefix):
            continue
        if sys.platform != "win32":
            results.append((True, f"[dev mode] removeria {name}"))
            continue
        try:
            proc = subprocess.run(
                ["schtasks", "/delete", "/tn", name, "/f"],
                capture_output=True, text=True, timeout=10,
            )
            if proc.returncode == 0:
                results.append((True, f"removido: {name}"))
            else:
                results.append((False, f"{name}: {proc.stderr.strip()}"))
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            results.append((False, f"{name}: {e}"))
    return results
