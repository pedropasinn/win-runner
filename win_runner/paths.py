"""Diretórios canônicos por SO.

Windows é o alvo principal: `%LOCALAPPDATA%\\win-runner` para state e
logs, `%TEMP%` para arquivos efêmeros. Mantemos fallback Linux/macOS
para desenvolvimento no WSL — não é um SO suportado em produção, só
permite rodar `pytest` localmente sem subir uma VM Windows.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def home() -> Path:
    return Path.home()


def state_dir() -> Path:
    """Onde state.jsonl, scheduler.jsonl, etc. ficam."""
    override = os.environ.get("WIN_RUNNER_STATE")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(home() / "AppData" / "Local")
        return Path(base) / "win-runner"
    return home() / ".local" / "share" / "win-runner"


def logs_dir() -> Path:
    return state_dir() / "logs"


def tmp_dir() -> Path:
    """Para outcome contracts e arquivos efêmeros."""
    if sys.platform == "win32":
        return Path(os.environ.get("TEMP") or str(home() / "AppData" / "Local" / "Temp"))
    return Path("/tmp")


def repo_root() -> Path:
    """Raiz do projeto (resolve relativo a este arquivo)."""
    return Path(__file__).resolve().parent.parent


def tasks_dir() -> Path:
    """Diretório de filas .md. Override via WIN_RUNNER_TASKS."""
    override = os.environ.get("WIN_RUNNER_TASKS")
    if override:
        return Path(override)
    return repo_root() / "tasks"


def ensure_dirs() -> None:
    """Cria os diretórios necessários se ainda não existem."""
    state_dir().mkdir(parents=True, exist_ok=True)
    logs_dir().mkdir(parents=True, exist_ok=True)
    tasks_dir().mkdir(parents=True, exist_ok=True)
