"""CLI `win-runner` (Click)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from . import __version__, runner, scheduler, state, status_server
from .parser import count_summary, list_queues, parse_queue
from .paths import ensure_dirs, state_dir, tasks_dir
from .resume import (
    delete_resume as delete_resume_task,
    list_pending_resumes,
)
from .verify import run_verify

console = Console()


@click.group()
@click.version_option(__version__, prog_name="win-runner")
def cli() -> None:
    """win-runner — runner Windows-native para filas .md.

    Use `win-runner <comando> --help` para ver opções de cada subcomando.
    """
    ensure_dirs()


# ─── run ───────────────────────────────────────────────────────────────
@cli.command()
@click.argument("queues", nargs=-1, required=True)
def run(queues: tuple[str, ...]) -> None:
    """Executa uma ou mais filas em sequência."""
    rc = runner.run_queues(list(queues))
    sys.exit(rc)


# ─── list ──────────────────────────────────────────────────────────────
@cli.command("list")
def list_cmd() -> None:
    """Lista filas .md disponíveis em tasks/."""
    queues = list_queues(tasks_dir())
    if not queues:
        console.print(f"[yellow]nenhuma fila em {tasks_dir()}[/]")
        return
    table = Table(title=f"filas em {tasks_dir()}")
    table.add_column("nome", style="cyan")
    table.add_column("blocos", justify="right")
    table.add_column("pendente", justify="right", style="yellow")
    table.add_column("done", justify="right", style="green")
    table.add_column("failed", justify="right", style="red")
    for q in queues:
        blocks = parse_queue(q)
        done, running, failed, pending = count_summary(blocks)
        table.add_row(q.stem, str(len(blocks)), str(pending), str(done), str(failed))
    console.print(table)


# ─── status ────────────────────────────────────────────────────────────
@cli.command()
@click.argument("queue")
def status(queue: str) -> None:
    """Resumo da fila + última execução."""
    queue_path = tasks_dir() / f"{queue}.md"
    if not queue_path.exists():
        console.print(f"[red]fila {queue!r} não existe em {queue_path}[/]")
        sys.exit(1)
    blocks = parse_queue(queue_path)
    done, running, failed, pending = count_summary(blocks)
    console.print(f"[cyan]fila[/]: [bold]{queue}[/]")
    console.print(f"  blocos: {len(blocks)}")
    console.print(f"  done: [green]{done}[/]  pending: [yellow]{pending}[/]  "
                  f"running: {running}  failed: [red]{failed}[/]")

    last = state.last_run_summary(queue)
    if last:
        console.print("\n[cyan]última execução[/]:")
        console.print(f"  iniciou: {last.get('started_at')}")
        console.print(f"  terminou: {last.get('ended_at')}")
        console.print(f"  exit: {last.get('exit')}  duração: {last.get('duration_s')}s")
        if last.get("reason"):
            console.print(f"  motivo: [yellow]{last['reason']}[/]")
        console.print(
            f"  task_done: {last.get('task_done')}  "
            f"task_failed: {last.get('task_failed')}"
        )


# ─── history ───────────────────────────────────────────────────────────
@cli.command()
@click.option("--limit", default=20, help="Número de runs a mostrar.")
def history(limit: int) -> None:
    """Últimas runs de todas as filas."""
    rows: list[tuple[str, dict]] = []
    for q in state.list_queues_with_state():
        for ev in state.read_events(q):
            if ev.get("event") == "run_end":
                rows.append((q, ev))
    rows.sort(key=lambda r: r[1].get("ts", ""), reverse=True)
    rows = rows[:limit]
    if not rows:
        console.print("[yellow]sem histórico[/]")
        return
    table = Table(title=f"últimas {len(rows)} runs")
    table.add_column("ts", style="dim")
    table.add_column("fila", style="cyan")
    table.add_column("exit", justify="right")
    table.add_column("dur_s", justify="right")
    table.add_column("motivo")
    for q, ev in rows:
        exit_v = ev.get("exit")
        style = "green" if exit_v == 0 else "red"
        table.add_row(
            ev.get("ts", "").replace("+00:00", "Z"),
            q,
            f"[{style}]{exit_v}[/]",
            str(ev.get("duration_s", "")),
            ev.get("reason") or "",
        )
    console.print(table)


# ─── verify-all ────────────────────────────────────────────────────────
@cli.command("verify-all")
@click.argument("queue")
def verify_all(queue: str) -> None:
    """Re-executa todos os (verify=...) declarados na fila."""
    queue_path = tasks_dir() / f"{queue}.md"
    if not queue_path.exists():
        console.print(f"[red]fila {queue!r} não existe[/]")
        sys.exit(1)
    blocks = parse_queue(queue_path)
    work_dir = Path.cwd()
    failures = 0
    n = 0
    for b in blocks:
        for t in b.tasks:
            if not t.verify:
                continue
            n += 1
            res = run_verify(t.verify, work_dir)
            mark = "[green]✓[/]" if res.passed else "[red]✗[/]"
            console.print(f"{mark} L{t.line_num}: {t.verify}")
            if not res.passed:
                console.print(f"  [red]{res.output[:300]}[/]")
                failures += 1
    if n == 0:
        console.print("[yellow]nenhuma tarefa tem (verify=...)[/]")
    elif failures:
        console.print(f"\n[red]{failures}/{n} verifies falharam[/]")
        sys.exit(2)
    else:
        console.print(f"\n[green]{n}/{n} verifies passaram[/]")


# ─── schedule ──────────────────────────────────────────────────────────
@cli.group()
def schedule() -> None:
    """Tarefas recorrentes (cron) via Task Scheduler."""


@schedule.command("register")
@click.argument("queue")
def schedule_register(queue: str) -> None:
    """Registra todas as tarefas com (cron=...) da fila no Task Scheduler."""
    work_dir = Path.cwd()
    results = scheduler.register_queue(queue, work_dir)
    for ok, msg in results:
        mark = "[green]✓[/]" if ok else "[red]✗[/]"
        console.print(f"{mark} {msg}")
    failed = sum(1 for ok, _ in results if not ok)
    if failed and not any(ok for ok, _ in results):
        sys.exit(2)


@schedule.command("list")
def schedule_list() -> None:
    """Lista tarefas cron registradas."""
    rows = scheduler.list_registered()
    if not rows:
        console.print("[yellow]nenhuma entry cron registrada[/]")
        return
    table = Table(title="cron entries no Task Scheduler")
    table.add_column("nome", style="cyan")
    table.add_column("próximo run")
    table.add_column("status")
    for r in rows:
        table.add_row(r["task_name"], r["next_run"], r["status"])
    console.print(table)


@schedule.command("unregister")
@click.argument("queue")
def schedule_unregister(queue: str) -> None:
    """Remove todas as entries cron de uma fila."""
    results = scheduler.unregister_queue(queue)
    for ok, msg in results:
        mark = "[green]✓[/]" if ok else "[red]✗[/]"
        console.print(f"{mark} {msg}")


# ─── resume ────────────────────────────────────────────────────────────
@cli.group()
def resume() -> None:
    """Auto-resume após rate-limit (entries one-shot do Task Scheduler)."""


@resume.command("list")
def resume_list() -> None:
    """Lista resumes pendentes."""
    rows = list_pending_resumes()
    if not rows:
        console.print("[yellow]nenhuma retomada pendente[/]")
        return
    table = Table(title="resumes pendentes")
    table.add_column("nome", style="cyan")
    table.add_column("próximo run")
    table.add_column("status")
    for r in rows:
        table.add_row(r["task_name"], r["next_run"], r["status"])
    console.print(table)


@resume.command("delete")
@click.argument("task_name")
def resume_delete(task_name: str) -> None:
    """Remove uma entry de resume específica."""
    ok = delete_resume_task(task_name)
    if ok:
        console.print(f"[green]removida: {task_name}[/]")
    else:
        console.print(f"[red]falhou ao remover {task_name}[/]")
        sys.exit(1)


# ─── paths ─────────────────────────────────────────────────────────────
@cli.command("paths")
def paths_cmd() -> None:
    """Mostra os diretórios usados pelo win-runner."""
    console.print(f"tasks:    [cyan]{tasks_dir()}[/]")
    console.print(f"state:    [cyan]{state_dir()}[/]")


# ─── serve ─────────────────────────────────────────────────────────────
@cli.command()
@click.option("--port", default=9090, help="Porta (default 9090).")
@click.option("--host", default="127.0.0.1", help="Bind host (default 127.0.0.1).")
def serve(port: int, host: str) -> None:
    """Inicia o status server local em 127.0.0.1:9090."""
    status_server.serve(host=host, port=port)


# ─── tui ───────────────────────────────────────────────────────────────
@cli.command()
def tui() -> None:
    """Abre a TUI Textual (filas, log, comandos /run, /stop)."""
    from . import tui as tui_mod
    tui_mod.main()


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
