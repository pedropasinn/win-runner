"""Hook (verify=<cmd>) — comando shell executado após a tarefa.

Em Windows o `shell=True` invoca `cmd.exe /c <cmd>`. Para tarefas que
declaram bashisms (`&&` é OK em cmd.exe; `[[`, `< <(`, `$(...)` não
são), preferimos invocar `bash -c` se Git Bash estiver no PATH —
documentado no README.

Timeout default 600s; configurável via env WIN_RUNNER_VERIFY_TIMEOUT.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class VerifyResult:
    rc: int
    output: str  # stderr ou stdout, truncado

    @property
    def passed(self) -> bool:
        return self.rc == 0


_BASHISM_RE_TEXT = ("[[", "]]", "< <(", " $(", "<<<", "<(", "process substitution")


def _looks_like_bashism(cmd: str) -> bool:
    return any(token in cmd for token in _BASHISM_RE_TEXT)


def run_verify(
    cmd: str,
    work_dir: Path,
    env: dict | None = None,
    timeout: int | None = None,
) -> VerifyResult:
    timeout = timeout or int(os.environ.get("WIN_RUNNER_VERIFY_TIMEOUT", "600"))
    use_bash = False
    if sys.platform == "win32" and _looks_like_bashism(cmd):
        bash_path = shutil.which("bash")
        if bash_path:
            use_bash = True

    try:
        if use_bash:
            bash_path = shutil.which("bash")
            assert bash_path
            proc = subprocess.run(
                [bash_path, "-c", cmd],
                cwd=str(work_dir),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        else:
            proc = subprocess.run(
                cmd, shell=True, cwd=str(work_dir), env=env,
                capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=timeout,
            )
        out = (proc.stderr or proc.stdout or "").strip()
        return VerifyResult(rc=proc.returncode, output=out[:500])
    except subprocess.TimeoutExpired:
        return VerifyResult(rc=124, output=f"[verify TIMEOUT após {timeout}s]")
    except Exception as e:
        return VerifyResult(rc=1, output=f"[verify error: {e}]")
