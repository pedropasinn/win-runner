"""Status server local (HTTP em 127.0.0.1:9090).

Stdlib http.server — sem FastAPI/uvicorn pra evitar dependências
pesadas em rede corporativa.

Endpoints:
  GET /             → HTML dashboard simples
  GET /api/state    → JSON com filas e últimas runs
  GET /api/health   → {runner: up, version, time}

Bind 127.0.0.1 sempre — nunca expõe na rede. Sem auth (é localhost only).

Para rodar persistente em Windows: registrar via schtasks /sc onlogon
(install_scheduler_tasks.ps1 cuida disso) ou simplesmente abrir uma
janela PowerShell e deixar rodando.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__, state
from .parser import count_summary, list_queues, parse_queue
from .paths import state_dir, tasks_dir


PORT_DEFAULT = 9090


_INDEX_HTML = """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <title>win-runner status</title>
  <style>
    body { font-family: -apple-system, "Segoe UI", Tahoma, sans-serif;
           background: #1e1e1e; color: #d4d4d4; max-width: 1000px; margin: 2em auto;
           padding: 0 1em; }
    h1 { color: #4ec9b0; margin-bottom: 0.2em; }
    .meta { color: #808080; font-size: 0.85em; margin-bottom: 1.5em; }
    table { border-collapse: collapse; width: 100%; margin-top: 1em; }
    th, td { padding: 0.4em 0.6em; text-align: left;
             border-bottom: 1px solid #333; }
    th { color: #569cd6; font-weight: 600; }
    .pending { color: #dcdcaa; }
    .running { color: #569cd6; font-weight: 600; }
    .done    { color: #6a9955; }
    .failed  { color: #f48771; }
    .stale   { color: #808080; }
    .toolbar { margin-bottom: 1em; }
    button { background: #0e639c; color: white; border: none;
             padding: 0.4em 1em; cursor: pointer; border-radius: 3px; }
    button:hover { background: #1177bb; }
    code { background: #2d2d2d; padding: 0.1em 0.3em; border-radius: 3px; }
  </style>
</head>
<body>
  <h1>win-runner</h1>
  <div class="meta" id="meta">carregando…</div>
  <div class="toolbar">
    <button onclick="load()">refresh</button>
    <label><input type="checkbox" id="auto" checked> auto (10s)</label>
  </div>
  <table id="tbl">
    <thead>
      <tr>
        <th>fila</th>
        <th>blocos</th>
        <th>pendente</th>
        <th>done</th>
        <th>running</th>
        <th>failed</th>
        <th>última run</th>
        <th>exit</th>
        <th>dur</th>
      </tr>
    </thead>
    <tbody></tbody>
  </table>

<script>
async function load() {
  try {
    const r = await fetch('/api/state');
    const j = await r.json();
    document.getElementById('meta').textContent =
      `versão ${j.version} · ${j.queues.length} fila(s) · atualizado ${new Date().toLocaleTimeString()}`;
    const tbody = document.querySelector('#tbl tbody');
    tbody.innerHTML = '';
    for (const q of j.queues) {
      const tr = document.createElement('tr');
      const last = q.last_run || {};
      tr.innerHTML = `
        <td><code>${q.name}</code></td>
        <td>${q.blocks}</td>
        <td class="pending">${q.pending}</td>
        <td class="done">${q.done}</td>
        <td class="running">${q.running}</td>
        <td class="failed">${q.failed}</td>
        <td class="stale">${last.started_at || '—'}</td>
        <td>${last.exit ?? '—'}</td>
        <td>${last.duration_s ? last.duration_s + 's' : '—'}</td>`;
      tbody.appendChild(tr);
    }
  } catch (e) {
    document.getElementById('meta').textContent = 'erro: ' + e;
  }
}
load();
setInterval(() => { if (document.getElementById('auto').checked) load(); }, 10000);
</script>
</body>
</html>
"""


def _state_snapshot() -> dict:
    queues_out = []
    for qpath in list_queues(tasks_dir()):
        blocks = parse_queue(qpath)
        done, running, failed, pending = count_summary(blocks)
        last = state.last_run_summary(qpath.stem)
        queues_out.append({
            "name": qpath.stem,
            "blocks": len(blocks),
            "done": done,
            "running": running,
            "failed": failed,
            "pending": pending,
            "last_run": last,
        })
    return {
        "version": __version__,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "queues": queues_out,
    }


class _Handler(BaseHTTPRequestHandler):
    server_version = f"win-runner/{__version__}"

    def log_message(self, format: str, *args) -> None:  # silenciar
        return

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, code: int, body: str, content_type: str) -> None:
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/" or self.path == "/index.html":
            self._send_text(200, _INDEX_HTML, "text/html; charset=utf-8")
            return
        if self.path == "/api/health":
            self._send_json(200, {
                "runner": "up",
                "version": __version__,
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            return
        if self.path == "/api/state":
            try:
                self._send_json(200, _state_snapshot())
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return
        self._send_text(404, "not found", "text/plain")


def serve(host: str = "127.0.0.1", port: int = PORT_DEFAULT) -> None:
    httpd = ThreadingHTTPServer((host, port), _Handler)
    print(f"win-runner status: http://{host}:{port}")
    print(f"  state dir: {state_dir()}")
    print(f"  tasks dir: {tasks_dir()}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nencerrando status server.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=PORT_DEFAULT)
    p.add_argument("--host", default="127.0.0.1")
    a = p.parse_args()
    serve(host=a.host, port=a.port)
