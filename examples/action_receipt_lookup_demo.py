"""Recover a real isolated HTTP write response with GET and no second POST."""

from __future__ import annotations

import argparse
from http.client import HTTPConnection
import json
import logging
from pathlib import Path
import sys
import threading
from urllib.parse import urlencode
import uuid

from agentrelay import __version__
from agentrelay.server import AppServer, Handler
from agentrelay.store import DomainError, Store


class CountingHandler(Handler):
    def do_POST(self):
        self.server.received_posts += 1
        super().do_POST()


class UncertainResponseServer(AppServer):
    """Inject exactly one failure after the normal action path has committed."""

    def __init__(self, store):
        super().__init__(("127.0.0.1", 0), store)
        self.RequestHandlerClass = CountingHandler
        self.received_posts = 0
        self.fail_next_snapshot = True

    def snapshot(self, identity=None):
        if self.fail_next_snapshot:
            self.fail_next_snapshot = False
            raise ValueError("Demonstration: response construction failed after commit")
        return super().snapshot(identity)


def run(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    store = Store(output / "workspace.sqlite")
    server = UncertainResponseServer(store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    log_handler = logging.FileHandler(output / "expected-server-error.log", encoding="utf-8")
    logging.getLogger().addHandler(log_handler)
    thread.start()

    def call(method, path, payload=None):
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        headers = {"X-AgentRelay-Workspace": "default"}
        if payload is not None:
            headers.update({"Content-Type": "application/json", "X-AgentRelay-Client": "browser"})
        try:
            body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    try:
        request_id = "example/á+" + str(uuid.uuid4())
        request = {"action": "apply_ticket_action", "data": {
            "request_id": request_id, "action": "create_ticket", "data": {
                "title": "Fictional HTTP response recovery",
                "acceptance": ["Recover the committed receipt without a second POST"],
            },
        }}
        (output / "original-request.json").write_text(
            json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
        first_status, first_body = call("POST", "/api/actions", request)
        assert first_status == 500, (first_status, first_body)

        lookup_path = "/api/action-receipts?" + urlencode({"request_id": request_id})
        lookup_status, recovered = call("GET", lookup_path)
        assert lookup_status == 200, (lookup_status, recovered)
        receipt = recovered["receipt"]
        ticket = receipt["result"]
        assert "replayed" not in receipt and "current_ticket" not in recovered
        assert server.received_posts == 1
        assert len(store.state()["tickets"]) == 1

        # This explicitly separate fixture edit shows why a receipt is not current
        # context. It is a direct domain call, never a retry of the uncertain POST.
        current = store.action("update_ticket", {
            "id": ticket["id"], "expected_revision": ticket["revision"],
            "title": "Later independent edit",
        })
        later_status, later_receipt = call("GET", lookup_path)
        context_status, context = call("GET", f"/api/tickets/{ticket['id']}/context")
        assert later_status == context_status == 200
        assert later_receipt["receipt"] == receipt
        assert context["ticket"]["revision"] == current["revision"] > ticket["revision"]

        try:
            store.get_action_receipt(request_id, actor="agent:another-connection")
        except DomainError as error:
            assert error.status == 404
        else:
            raise AssertionError("Another actor could read this receipt")

        before = store.state()
        store.backup(output / "backup.sqlite")
        backup_receipt = Store(output / "backup.sqlite").get_action_receipt(request_id, actor="human")
        assert backup_receipt["receipt"] == receipt
        assert store.state() == before and server.received_posts == 1
        report = {
            "version": __version__, "fictional": True,
            "fault": "Injected snapshot failure after a real HTTP write committed",
            "first_http_status": first_status, "lookup_http_status": lookup_status,
            "received_posts": server.received_posts,
            "tickets": len(before["tickets"]), "receipt": receipt,
            "current_ticket": context["ticket"], "other_actor_status": 404,
            "backup_preserved_receipt": True,
            "limits": "A lookup is historical; 404 cannot rule out a writer still in flight. No automatic retry, model or worker.",
        }
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        logging.getLogger().removeHandler(log_handler)
        log_handler.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New isolated output directory")
    args = parser.parse_args()
    try:
        report = run(args.output.resolve())
    except (OSError, DomainError) as error:
        print(f"Receipt lookup example failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
