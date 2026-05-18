"""Loop principal — port enxuto de monorepo/scripts/runner/__main__.py.

Responsabilidades:
- parse_queue → list[Block]
- para cada bloco, claim_next_pending_in_block (atômico)
- dispara Claude via wrapper, marca [x] / escala / [!] conforme retorno
- emite eventos no JSONL
- pausa via schtasks em rate-limit
- respeita depends entre tarefas (DAG)

Não inclui: shared sessions complexas, memory=queue, ask interativo,
auto-router, outcome contract elaborado, signals POSIX. V0.1 enxuto.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

from . import memory as memory_mod
from . import router as router_mod
from . import state
from .parser import (
    Block,
    Task,
    completed_lines,
    expected_workspace,
    parse_queue,
    resolve_depends,
)
from .paths import logs_dir, tasks_dir
from .provider import parse_spec, run as provider_run
from .queue import claim_next_pending_in_block, mark_line, reclaim_zombies
from .resume import schedule_resume
from .verify import run_verify


def _chain_for(task: Task) -> list[str | None]:
    """Constrói cadeia de modelos: model + escalate. None significa 'default'."""
    chain: list[str | None] = []
    chain.append(task.model or None)
    for tier in task.escalate:
        chain.append(tier)
    return chain


def _replace_model(task: Task, new_model: str | None) -> Task:
    """Cópia rasa do Task com `model` substituído (para auto-routing)."""
    from dataclasses import replace
    return replace(task, model=new_model)


def _resolve_work_dir(queue_path: Path) -> tuple[Path, str]:
    """Workspace por fila: <!-- workspace --> > WIN_RUNNER_WORKDIR > cwd."""
    declared = expected_workspace(queue_path)
    if declared:
        p = Path(os.path.expandvars(declared)).expanduser().resolve()
        return p, "queue"
    if env := os.environ.get("WIN_RUNNER_WORKDIR"):
        p = Path(env).resolve()
        if p.is_dir():
            return p, "env"
    return Path.cwd(), "cwd"


def _check_depends_ready(
    task: Task,
    deps: list[int],
    completed: set[int],
) -> tuple[bool, list[int]]:
    pending = [d for d in deps if d not in completed]
    return (len(pending) == 0, pending)


def run_queue(queue_name: str) -> int:
    """Executa uma fila inteira. Retorna exit code."""
    queue_path = tasks_dir() / f"{queue_name}.md"
    if not queue_path.exists():
        print(f"[erro] fila {queue_path} não existe")
        return 1

    logs_dir().mkdir(parents=True, exist_ok=True)
    log_path = logs_dir() / f"{queue_name}-{datetime.now():%Y%m%d}.log"
    log = log_path.open("a", encoding="utf-8")

    work_dir, origin = _resolve_work_dir(queue_path)
    if not work_dir.is_dir():
        print(f"[erro] workspace {work_dir} (origem={origin}) não existe")
        log.write(f"workspace inválido: {work_dir}\n")
        log.close()
        return 1

    print(f"win-runner: fila '{queue_name}' em {work_dir} ({origin})")
    log.write(
        f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} | fila={queue_name} | "
        f"workspace={work_dir} ===\n"
    )

    state.append_event(
        queue_name, "run_start",
        queue=queue_name,
        work_dir=str(work_dir),
        workspace_origin=origin,
        pid=os.getpid(),
    )

    n_zombies = reclaim_zombies(queue_path)
    if n_zombies:
        print(f"  ↻ {n_zombies} tarefa(s) [~] revertida(s) para [ ]")

    t_run = time.time()
    overall_rc = 0
    paused_for_rate = False

    blocks = parse_queue(queue_path)
    if not blocks:
        print(f"[erro] nenhum bloco encontrado em {queue_path}")
        state.append_event(
            queue_name, "run_end", exit=1, duration_s=0, reason="no_blocks",
        )
        log.close()
        return 1

    for block in blocks:
        rc = _process_block(
            queue_name, queue_path, block, work_dir, log,
        )
        if rc == "rate_limit":
            paused_for_rate = True
            break
        if rc != 0:
            overall_rc = max(overall_rc, rc)

    duration_s = int(time.time() - t_run)
    reason = "rate_limit_paused" if paused_for_rate else None
    state.append_event(
        queue_name, "run_end",
        exit=0 if paused_for_rate else overall_rc,
        duration_s=duration_s,
        reason=reason,
    )

    if paused_for_rate:
        print(f"⏸ fila '{queue_name}' pausada por rate-limit. Retomada agendada.")
    else:
        status = "✅" if overall_rc == 0 else "⚠"
        print(f"{status} fila '{queue_name}' concluída ({duration_s}s, exit={overall_rc})")

    log.close()
    return 0 if paused_for_rate else overall_rc


def _process_block(
    queue_name: str,
    queue_path: Path,
    block: Block,
    work_dir: Path,
    log,
) -> int | str:
    print(f"\n━━━ bloco: {block.name} ━━━")
    state.append_event(queue_name, "block_start", name=block.name, start=block.line_num)
    t_block = time.time()
    done = failed = 0

    max_iter = max(50, len(block.tasks) * 4)
    for _ in range(max_iter):
        # Re-parse para verificar depends contra estado atualizado da fila.
        full = parse_queue(queue_path)
        completed = completed_lines(full)
        deps_map = resolve_depends(full)

        skip: set[int] = set()
        for t in block.tasks:
            if t.status != "pending":
                continue
            deps = deps_map.get(t.line_num, [])
            ready, pending = _check_depends_ready(t, deps, completed)
            if not ready:
                skip.add(t.line_num)

        claimed = claim_next_pending_in_block(
            queue_path, block.name, skip_lines=skip,
        )
        if claimed is None:
            break

        # Re-lê o bloco atualizado para pegar metadata da task claimed
        block_now = next(
            (b for b in parse_queue(queue_path) if b.name == block.name), None,
        )
        if block_now is None:
            mark_line(queue_path, claimed, " ")
            break
        task = next((t for t in block_now.tasks if t.line_num == claimed), None)
        if task is None:
            mark_line(queue_path, claimed, " ")
            break

        rc = _process_task(
            queue_name, queue_path, task, work_dir, log,
            block_name=block.name,
        )
        if rc == "rate_limit":
            return "rate_limit"
        if rc == "ok":
            done += 1
        elif rc == "fail":
            failed += 1

    print(f"  {done} ok / {failed} falha(s)")
    state.append_event(
        queue_name, "block_done",
        name=block.name, done=done, failed=failed,
        duration_s=int(time.time() - t_block),
    )
    return 0 if failed == 0 else 2


def _process_task(
    queue_name: str,
    queue_path: Path,
    task: Task,
    work_dir: Path,
    log,
    *,
    block_name: str = "",
) -> str:
    # B5: (model=auto) → resolve via router antes de montar a chain.
    resolved_model = task.model
    if task.model == "auto":
        decision = router_mod.explain(task.description, category=task.category)
        resolved_model = decision.spec
        print(f"  ↳ router auto → {resolved_model} [{decision.rule}] {decision.reason}")
        state.append_event(
            queue_name, "auto_route",
            line=task.line_num, spec=resolved_model,
            rule=decision.rule, reason=decision.reason, score=decision.score,
        )

    chain = _chain_for(_replace_model(task, resolved_model))
    print(f"\n▶ [{task.line_num}] {task.description[:120]}")
    for w in task.warnings:
        print(f"  ⚠ {w}")

    state.append_event(
        queue_name, "task_start",
        line=task.line_num,
        desc=task.description[:200],
        model=resolved_model,
        chain=[c or "default" for c in chain],
        category=task.category,
        task_id=task.task_id,
        memory=task.memory,
        has_verify=bool(task.verify),
    )

    t_task = time.time()

    for tier_idx, model in enumerate(chain):
        label = model or "default"
        provider, alias = parse_spec(model)
        print(f"  modelo: {label} (provider={provider})   {datetime.now():%H:%M:%S}")

        # Injeção de memória entre tarefas da mesma fila/bloco/modelo.
        prompt = task.description
        if task.memory == "queue":
            entries = memory_mod.latest_for(
                queue_name, block=block_name, model=label,
            )
            ctx = memory_mod.build_context(entries)
            if ctx:
                prompt = memory_mod.inject_into_prompt(prompt, ctx)
                state.append_event(
                    queue_name, "context_injection",
                    line=task.line_num, model=label,
                    n_entries=len(entries),
                    bytes=len(ctx.encode("utf-8")),
                )

        res = provider_run(model, prompt, work_dir, use_continue=False)

        # Loga o output cru (já parseado pelo wrapper)
        log.write(f"\n--- [{task.line_num}] tier={label} rc={res.rc} ---\n")
        log.write((res.stdout or "")[:8000])
        if res.stderr:
            log.write("\n[stderr]\n")
            log.write(res.stderr[:4000])
        log.flush()
        if res.stdout:
            print(res.stdout[:2000])

        if res.rate_limited:
            print(f"⏸ rate-limit detectado. Revertendo [~] → [ ] e agendando retomada.")
            mark_line(queue_path, task.line_num, " ")
            ok, msg, task_name = schedule_resume(
                res.rate_limit_text, queue_name, work_dir,
            )
            state.append_event(
                queue_name, "rate_limit",
                line=task.line_num,
                ok=ok, msg=msg, scheduled_task=task_name,
            )
            print(f"  {'✓' if ok else '✗'} {msg}")
            return "rate_limit"

        verify_passed: bool | None = None
        if res.rc == 0 and task.verify:
            v = run_verify(task.verify, work_dir, env=os.environ.copy())
            if v.passed:
                state.append_event(queue_name, "verify_pass", line=task.line_num)
                verify_passed = True
            else:
                state.append_event(
                    queue_name, "verify_fail",
                    line=task.line_num, exit=v.rc,
                    stderr_excerpt=v.output[:300],
                )
                print(f"  ✗ verify falhou (exit {v.rc}): {v.output[:200]}")
                verify_passed = False

        if res.rc == 0 and verify_passed is not False:
            mark_line(queue_path, task.line_num, "x")
            done_fields = {
                "line": task.line_num,
                "duration_s": int(time.time() - t_task),
                "model": model,
            }
            if res.tokens_in is not None:
                done_fields["tokens_in"] = res.tokens_in
            if res.tokens_out is not None:
                done_fields["tokens_out"] = res.tokens_out
            if res.cache_read_tokens is not None:
                done_fields["cache_read_tokens"] = res.cache_read_tokens
            if res.cache_creation_tokens is not None:
                done_fields["cache_creation_tokens"] = res.cache_creation_tokens
            if res.cost_usd is not None:
                done_fields["cost_usd"] = res.cost_usd
            if task.category:
                done_fields["category"] = task.category
            state.append_event(queue_name, "task_done", **done_fields)

            # Grava memória pra próxima task do mesmo (queue, block, model).
            if task.memory == "queue":
                memory_mod.record_completion(
                    queue_name,
                    line=task.line_num,
                    block=block_name,
                    model=label,
                    desc=task.description,
                    summary=(res.stdout or "")[:2000],
                )

            print(f"  ✅ concluída")
            return "ok"

        # Falhou — escala para o próximo tier se houver.
        if tier_idx + 1 < len(chain):
            nxt = chain[tier_idx + 1] or "default"
            print(f"  ↑ falha com {label}; escalando para {nxt}")
            state.append_event(
                queue_name, "escalation",
                line=task.line_num, **{"from": label, "to": nxt},
            )
            continue
        break

    mark_line(queue_path, task.line_num, "!")
    state.append_event(
        queue_name, "task_failed",
        line=task.line_num, reason="all_tiers_failed",
        chain=[c or "default" for c in chain],
        duration_s=int(time.time() - t_task),
    )
    print(f"  ❌ falhou em todos os tiers")
    return "fail"


def run_queues(queue_names: list[str]) -> int:
    """Encadeia múltiplas filas. Para se uma pausar por rate-limit."""
    overall = 0
    for i, q in enumerate(queue_names):
        if len(queue_names) > 1:
            print(f"\n━━━ fila {i+1}/{len(queue_names)}: {q} ━━━")
        rc = run_queue(q)
        if rc != 0:
            overall = rc
        # Se pausou por rate-limit, abre brecha mas o retorno é 0:
        # detectamos via último run_end.
        last = state.last_run_summary(q)
        if last and last.get("reason") == "rate_limit_paused":
            print(f"\n⏸ encadeamento interrompido — {len(queue_names) - i - 1} fila(s) restantes não foram disparadas")
            return 0
    return overall
