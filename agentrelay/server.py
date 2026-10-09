"""Loopback web interface. Domain rules are shared with the MCP transport.

Optional execution uses only workers from a trusted startup configuration.
Browser writes require a custom header and a same-origin request. This protects
against drive-by web pages, not other programs running as the local OS user.
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import __version__
from .store import DomainError, Store
from .workspaces import Workspace

STATIC = Path(__file__).with_name("static")
MAX_BODY = 1_048_576


class AppServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], store: Store, demo: bool = False, execution=None,
                 workspaces=None, default_workspace_id=None):
        self.store = store
        self.demo = demo
        self.execution = execution
        self.workspaces = workspaces or {"default": Workspace("default", Path(store.path).resolve().parent.name, store, execution)}
        self.default_workspace_id = default_workspace_id or next(iter(self.workspaces))
        super().__init__(address, Handler)

    def workspace(self, identity=None):
        if identity is None:
            if len(self.workspaces) > 1:
                raise DomainError("Selecciona un espacio con X-AgentRelay-Workspace.")
            identity = self.default_workspace_id
        if identity not in self.workspaces:
            raise DomainError("Espacio de trabajo no registrado.", 404)
        return self.workspaces[identity]

    def snapshot(self, identity=None) -> dict:
        workspace = self.workspace(identity)
        state = workspace.store.state()
        runs = state.pop("runs")
        execution = workspace.execution.snapshot() if workspace.execution else {"enabled": False, "workers": []}
        # Ticket and run statuses come from the same SQLite read transaction.
        execution["runs"] = runs
        return {**state, "demo": self.demo or state["demo"], "version": __version__, "execution": execution,
                "workspace": {"id": workspace.id, "name": workspace.name,
                              "database": str(Path(workspace.store.path).resolve()), "demo": state["demo"]}}

    def server_close(self):
        try:
            for workspace in self.workspaces.values():
                if workspace.execution:
                    workspace.execution.close()
        finally:
            super().server_close()


class Handler(BaseHTTPRequestHandler):
    server: AppServer
    server_version = "AgentRelay/0.4"

    def log_message(self, fmt, *args):
        logging.getLogger("agentrelay.http").info(fmt, *args)

    def _reply(self, status: int, body: bytes, content_type: str, **headers):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for name, value in headers.items():
            self.send_header(name.replace("_", "-"), value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value, **headers):
        self._reply(status, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", **headers)

    def _host_ok(self) -> bool:
        host = self.headers.get("Host", "")
        port = self.server.server_port
        if host not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            self._json(403, {"error": "Host no permitido. Usa la dirección local del servidor."})
            return False
        return True

    def _write_ok(self) -> bool:
        if not self._host_ok():
            return False
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{self.headers.get('Host')}":
            self._json(403, {"error": "Origen no permitido."})
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            self._json(403, {"error": "Petición externa no permitida."})
            return False
        if self.headers.get("X-AgentRelay-Client") != "browser":
            self._json(403, {"error": "Falta la identificación del cliente local."})
            return False
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            self._json(415, {"error": "Se requiere application/json."})
            return False
        return True

    def do_GET(self):
        if not self._host_ok():
            return
        path = unquote(urlsplit(self.path).path)
        try:
            if path == "/api/health":
                self._json(200, {"status": "ok", "version": __version__})
            elif path == "/api/workspaces":
                self._json(200, {"workspaces": [w.public() for w in self.server.workspaces.values()],
                                 "default_workspace_id": self.server.default_workspace_id})
            elif path == "/api/state":
                self._json(200, self.server.snapshot(self.headers.get("X-AgentRelay-Workspace")))
            elif path == "/api/export":
                workspace = self.server.workspace(self.headers.get("X-AgentRelay-Workspace"))
                self._json(200, {**workspace.store.export(), "workspace": workspace.public()},
                           Content_Disposition=f'attachment; filename="agentrelay-{workspace.id}-export.json"')
            elif path.startswith("/api/tickets/") and path.endswith("/context"):
                ticket_id = path[len("/api/tickets/"):-len("/context")]
                workspace = self.server.workspace(self.headers.get("X-AgentRelay-Workspace"))
                self._json(200, {**workspace.store.context(ticket_id), "workspace": workspace.public()})
            else:
                assets = {"/": ("index.html", "text/html"), "/index.html": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css"), "/static/app.js": ("app.js", "text/javascript"), "/static/style.css": ("style.css", "text/css")}
                asset = assets.get(path)
                if asset and (STATIC / asset[0]).is_file():
                    self._reply(200, (STATIC / asset[0]).read_bytes(), asset[1] + "; charset=utf-8")
                else:
                    self._json(404, {"error": "No encontrado."})
        except DomainError as exc:
            self._json(exc.status, {"error": str(exc)})
        except Exception:
            logging.exception("GET failed")
            self._json(500, {"error": "Error interno. Revisa el registro local."})

    def do_POST(self):
        if not self._write_ok():
            return
        if urlsplit(self.path).path != "/api/actions":
            self._json(404, {"error": "No encontrado."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY:
                self._json(413, {"error": "Cuerpo vacío o demasiado grande (máximo 1 MiB)."})
                return
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict) or not isinstance(payload.get("action"), str) or not isinstance(payload.get("data"), dict):
                self._json(400, {"error": "Se requieren action y data."})
                return
            if payload.get("actor", "human") != "human":
                self._json(403, {"error": "La interfaz representa a human. Los agentes deben usar MCP."})
                return
            action, data = payload["action"], payload["data"]
            workspace = self.server.workspace(self.headers.get("X-AgentRelay-Workspace"))
            if action in {"start_run", "cancel_run"}:
                if workspace.execution is None:
                    raise DomainError("Ejecución desactivada. Inicia el servidor con --workers.", 409)
                if action == "start_run":
                    if not isinstance(data.get("ticket_id"), str) or not isinstance(data.get("worker_id"), str) or type(data.get("expected_revision")) is not int:
                        raise DomainError("Se requieren ticket_id, worker_id y expected_revision.")
                    result = workspace.execution.start(data["ticket_id"], data["worker_id"], data["expected_revision"])
                else:
                    if not isinstance(data.get("run_id"), str):
                        raise DomainError("Se requiere run_id.")
                    result = workspace.execution.cancel(data["run_id"])
            else:
                result = workspace.store.action(action, data, actor="human")
            self._json(200, {"result": result, "state": self.server.snapshot(workspace.id)})
        except (ValueError, UnicodeError) as exc:
            self._json(400, {"error": "JSON o longitud de petición inválidos."})
        except DomainError as exc:
            self._json(exc.status, {"error": str(exc)})
        except Exception:
            logging.exception("POST failed")
            self._json(500, {"error": "Error interno. Revisa el registro local."})

    def do_OPTIONS(self):
        self._json(403, {"error": "CORS no habilitado. Usa la interfaz local o MCP."})


def serve(store: Store, port: int = 8787, demo: bool = False, execution=None,
          workspaces=None, default_workspace_id=None):
    with AppServer(("127.0.0.1", port), store, demo, execution, workspaces, default_workspace_id) as server:
        print(f"AgentRelay {__version__} · http://127.0.0.1:{server.server_port}", flush=True)
        print("Datos ficticios de demostración" if demo else "Espacio de trabajo local", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
