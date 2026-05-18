"""TUI mínima em Textual.

Layout:
  ┌──────────────────────────────────────────────────────────┐
  │ win-runner v0.2 │ filas: 3 / running: 1 / done hoje: 12  │
  ├──────────────┬───────────────────────────────────────────┤
  │ filas        │ log da fila ativa                         │
  │ • hello      │                                           │
  │ • refactor*  │                                           │
  │ • docs       │                                           │
  ├──────────────┴───────────────────────────────────────────┤
  │ comando: /run hello   (Enter pra executar, Ctrl-C sai)   │
  └──────────────────────────────────────────────────────────┘

Comandos:
  /run <fila>     — dispara `win-runner run <fila>` em subprocesso
  /stop           — Ctrl-C no subprocesso atual
  /reload         — re-lista filas e recarrega o log
  /status <fila>  — sumário rápido
  /help           — lista comandos
  /quit           — sai
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import threading
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, ListItem, ListView, Label, RichLog

from . import state
from .parser import count_summary, list_queues, parse_queue
from .paths import tasks_dir


class _RunnerProcess:
    """Encapsula o subprocesso do runner para a TUI consumir."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, queue: str, on_line, on_exit) -> None:
        if self.is_running():
            on_line("[stderr] já existe um runner ativo. /stop primeiro.\n")
            return
        env = os.environ.copy()
        cmd = [sys.executable, "-m", "win_runner", "run", queue]
        self.proc = subprocess.Popen(
            cmd, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            bufsize=1,
        )

        def _pump() -> None:
            assert self.proc and self.proc.stdout
            for line in self.proc.stdout:
                on_line(line.rstrip("\n"))
            rc = self.proc.wait()
            on_exit(rc)

        self._reader = threading.Thread(target=_pump, daemon=True)
        self._reader.start()

    def stop(self) -> None:
        if self.proc and self.is_running():
            self.proc.terminate()


class WinRunnerTUI(App):
    CSS = """
    Screen { background: $background; }
    #sidebar { width: 28; border-right: solid $accent; }
    #main    { padding: 0 1; }
    ListView { height: 1fr; }
    Input    { dock: bottom; }
    RichLog  { height: 1fr; border: solid $accent; }
    Label.title { color: $accent; text-style: bold; padding: 0 1; }
    Label.meta  { color: $text-muted; padding: 0 1; }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Sair"),
        Binding("ctrl+r", "reload", "Refresh"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.runner = _RunnerProcess()
        self.selected: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Label("filas", classes="title")
                yield ListView(id="queues")
                yield Label("", classes="meta", id="sidebar-meta")
            with Vertical(id="main"):
                yield Label("log", classes="title")
                yield RichLog(id="log", highlight=False, markup=False, wrap=False)
        yield Input(placeholder="comando (/help)", id="cmd")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "win-runner"
        self.refresh_queues()
        self.query_one("#cmd", Input).focus()
        self._write_log(f"win-runner TUI · tasks={tasks_dir()}")
        self._write_log("digite /help para ver comandos.")

    # ─── ações ───────────────────────────────────────────────────────
    def action_quit(self) -> None:
        self.runner.stop()
        self.exit()

    def action_reload(self) -> None:
        self.refresh_queues()

    # ─── input ───────────────────────────────────────────────────────
    def on_input_submitted(self, event: Input.Submitted) -> None:
        cmd = event.value.strip()
        event.input.value = ""
        if not cmd:
            return
        if not cmd.startswith("/"):
            self._write_log(f"[sintaxe] comandos começam com /. tente /run {cmd}")
            return
        parts = shlex.split(cmd[1:])
        if not parts:
            return
        op, *rest = parts
        op = op.lower()
        if op in ("quit", "exit", "q"):
            self.action_quit()
        elif op == "help":
            self._write_log(
                "comandos:\n"
                "  /run <fila>     — dispara o runner em subprocesso\n"
                "  /stop           — termina o runner ativo\n"
                "  /reload         — re-lê tasks/ e atualiza sidebar\n"
                "  /status <fila>  — sumário da fila\n"
                "  /quit           — sai (também Ctrl-Q)"
            )
        elif op == "run":
            if not rest:
                self._write_log("uso: /run <fila>")
            else:
                self._run_queue(rest[0])
        elif op == "stop":
            self.runner.stop()
            self._write_log("[stop] sinal enviado.")
        elif op == "reload":
            self.refresh_queues()
        elif op == "status":
            if not rest:
                self._write_log("uso: /status <fila>")
            else:
                self._status(rest[0])
        else:
            self._write_log(f"[?] comando desconhecido: /{op}")

    # ─── helpers ─────────────────────────────────────────────────────
    def _write_log(self, msg: str) -> None:
        self.query_one("#log", RichLog).write(msg)

    def refresh_queues(self) -> None:
        lv = self.query_one("#queues", ListView)
        lv.clear()
        n = 0
        for qpath in list_queues(tasks_dir()):
            n += 1
            lv.append(ListItem(Label(qpath.stem)))
        self.query_one("#sidebar-meta", Label).update(f"{n} fila(s)")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        label = event.item.query_one(Label)
        self.selected = str(label.renderable)
        self._status(self.selected)

    def _status(self, queue: str) -> None:
        path = tasks_dir() / f"{queue}.md"
        if not path.exists():
            self._write_log(f"[erro] {queue!r} não existe em {tasks_dir()}")
            return
        blocks = parse_queue(path)
        done, running, failed, pending = count_summary(blocks)
        last = state.last_run_summary(queue) or {}
        self._write_log(
            f"\n— fila: {queue} —\n"
            f"  blocos: {len(blocks)} · done: {done} pending: {pending} "
            f"running: {running} failed: {failed}\n"
            f"  última run: exit={last.get('exit')} "
            f"dur={last.get('duration_s')}s motivo={last.get('reason') or '-'}"
        )

    def _run_queue(self, queue: str) -> None:
        path = tasks_dir() / f"{queue}.md"
        if not path.exists():
            self._write_log(f"[erro] fila {queue!r} não existe")
            return
        self._write_log(f"\n▶ /run {queue}\n")

        def on_line(line: str) -> None:
            self.call_from_thread(self._write_log, line)

        def on_exit(rc: int) -> None:
            self.call_from_thread(
                self._write_log,
                f"\n=== runner terminou (exit={rc}) ===",
            )
            self.call_from_thread(self.refresh_queues)

        self.runner.start(queue, on_line, on_exit)


def main() -> None:
    WinRunnerTUI().run()


if __name__ == "__main__":
    main()
