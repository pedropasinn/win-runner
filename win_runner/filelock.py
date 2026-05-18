"""File locking cross-platform.

Windows: `msvcrt.locking` (bloqueante via `LK_LOCK`, ou não-bloqueante
via `LK_NBLCK`). Trava 1 byte no offset 0 — suficiente como mutex, já
que o lockfile é vazio.

POSIX (fallback dev no WSL): `fcntl.flock` com `LOCK_EX`/`LOCK_UN`.

Não usamos biblioteca externa (`portalocker`, `filelock`) para evitar
dependência adicional num projeto que deve rodar com `pip install` user
sem complicação em rede corporativa.
"""

from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    import msvcrt  # type: ignore[import-not-found]
else:
    import fcntl


def _win_lock(fd: int, blocking: bool, deadline: float | None = None) -> bool:
    """Tentativa de lock em Windows. Retorna True se travou."""
    try:
        os.lseek(fd, 0, 0)
    except OSError:
        pass
    if blocking:
        # LK_LOCK do CRT já faz 10×1s; estendemos com retry para contenção pesada.
        end = deadline if deadline is not None else (time.monotonic() + 30.0)
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                return True
            except OSError:
                if time.monotonic() >= end:
                    return False
                time.sleep(0.1)
    try:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return True
    except OSError:
        return False


def _win_unlock(fd: int) -> None:
    try:
        os.lseek(fd, 0, 0)
    except OSError:
        pass
    try:
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except OSError:
        pass


@contextmanager
def file_lock(path: Path) -> Iterator[int]:
    """Trava exclusiva sobre `path` enquanto o bloco roda."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        if _IS_WINDOWS:
            if not _win_lock(fd, blocking=True):
                raise OSError(f"timeout adquirindo lock em {path}")
        else:
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield fd
    finally:
        try:
            if _IS_WINDOWS:
                _win_unlock(fd)
            else:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            try:
                os.close(fd)
            except OSError:
                pass


def try_acquire(path: Path) -> int | None:
    """Não-bloqueante. Retorna fd com lock segurado ou None se ocupado.

    Caller é responsável por chamar `release(fd)` depois — usado pelo
    scheduler daemon que mantém lock pela vida toda do processo.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o644)
    if _IS_WINDOWS:
        if _win_lock(fd, blocking=False):
            return fd
    else:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            pass
    os.close(fd)
    return None


def release(fd: int) -> None:
    """Libera lock obtido por `try_acquire`."""
    try:
        if _IS_WINDOWS:
            _win_unlock(fd)
        else:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
