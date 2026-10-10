"""The generic CLI action envelope exposes bounded idempotent candidate claims."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from agentrelay.store import Store


class CliClaimNextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-cli-claim-next-")
        self.root = Path(self.temp.name)
        self.database = self.root / "workspace.sqlite"
        self.store = Store(self.database)
        self.request_number = 0

    def tearDown(self):
        self.temp.cleanup()

    def create(self, title, *, priority="normal", acceptance=None, status="queued",
               profile_id=None):
        data = {"title": title, "priority": priority,
                "acceptance": ["Review result"] if acceptance is None else acceptance}
        if profile_id is not None:
            data["profile_id"] = profile_id
        ticket = self.store.action("create_ticket", data)
        if status != "queued":
            ticket = self.store.action("transition", {
                "id": ticket["id"], "expected_revision": ticket["revision"],
                "status": status, "reason": "Fixture state",
            })
        return ticket

    def action(self, data, actor="agent:cli-candidate", *, name="claim_next_ticket"):
        self.request_number += 1
        request = self.root / f"request-{self.request_number}.json"
        request.write_text(json.dumps({"action": name, "data": data},
                                      ensure_ascii=False), encoding="utf-8")
        return subprocess.run([
            sys.executable, "-m", "agentrelay", "action", "--db", str(self.database),
            "--actor", actor, "--input", str(request),
        ], cwd=Path(__file__).resolve().parents[1], capture_output=True,
            text=True, encoding="utf-8", timeout=20)

    @staticmethod
    def candidate(ticket, revision=None):
        return {"ticket_id": ticket["id"],
                "expected_revision": ticket["revision"] if revision is None else revision}

    def receipt_count(self):
        with closing(sqlite3.connect(self.database)) as database:
            return database.execute("SELECT COUNT(*) FROM claim_requests").fetchone()[0]

    def claim_events(self):
        with closing(sqlite3.connect(self.database)) as database:
            return database.execute(
                "SELECT ticket_id,actor FROM events WHERE action='claim_ticket' ORDER BY id").fetchall()

    def test_priority_skips_explicit_scope_and_exact_retry_claims_only_once(self):
        outside = self.create("Outside scope", priority="urgent")
        stale = self.create("Stale", priority="urgent")
        missing = self.create("Missing acceptance", priority="urgent", acceptance=[])
        not_ready = self.create("Not ready", priority="urgent", status="backlog")
        astra = self.create("Astra locked", priority="urgent", profile_id="astra")
        high = self.create("Eligible high", priority="high")
        normal = self.create("Eligible normal", priority="normal")
        candidates = [self.candidate(stale, stale["revision"] + 1), self.candidate(missing),
                      self.candidate(not_ready), self.candidate(astra), self.candidate(normal),
                      self.candidate(high)]
        data = {"request_id": "cli-claim-á", "candidates": candidates,
                "assignee": "agent:cli-candidate", "actual_model": "unknown",
                "actual_effort": "unknown"}

        first = self.action(data)
        self.assertEqual(first.returncode, 0, first.stderr)
        result = json.loads(first.stdout)
        self.assertEqual(result["request_id"], "cli-claim-á")
        self.assertEqual(result["ticket"]["id"], high["id"])
        self.assertEqual(result["ticket"]["assignee"], "agent:cli-candidate")
        self.assertEqual(result["skipped"], [
            {"ticket_id": stale["id"], "reason": "stale_revision"},
            {"ticket_id": missing["id"], "reason": "missing_acceptance"},
            {"ticket_id": not_ready["id"], "reason": "not_ready"},
            {"ticket_id": astra["id"], "reason": "incompatible_profile"},
        ])

        retry = self.action(data)
        self.assertEqual(retry.returncode, 0, retry.stderr)
        self.assertEqual(json.loads(retry.stdout), result)
        self.assertEqual(self.receipt_count(), 1)
        self.assertEqual(self.claim_events(), [(high["id"], "agent:cli-candidate")])
        current = {ticket["id"]: ticket for ticket in self.store.state()["tickets"]}
        self.assertEqual(current[outside["id"]]["status"], "queued")
        self.assertEqual(current[normal["id"]]["status"], "queued")

    def test_unknown_actor_payload_and_invalid_candidates_roll_back(self):
        first = self.create("First", priority="high")
        second = self.create("Second", priority="normal")
        baseline = self.store.state()
        unknown = {"request_id": "unknown-scope", "candidates": [
            self.candidate(first), {"ticket_id": "AR-9999", "expected_revision": 1}],
            "assignee": "agent:cli-candidate", "actual_model": "unknown",
            "actual_effort": "unknown"}
        rejected = self.action(unknown)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertNotIn("Traceback", rejected.stderr)
        self.assertEqual(self.store.state(), baseline)
        self.assertEqual(self.receipt_count(), 0)

        data = {"request_id": "stable-request", "candidates": [self.candidate(first)],
                "assignee": "agent:cli-candidate", "actual_model": "unknown",
                "actual_effort": "unknown"}
        accepted = self.action(data)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        claimed = json.loads(accepted.stdout)["ticket"]
        self.assertEqual(claimed["id"], first["id"])

        actor_conflict = self.action({**data, "assignee": "agent:other"}, "agent:other")
        self.assertNotEqual(actor_conflict.returncode, 0)
        payload_conflict = self.action({**data, "candidates": [self.candidate(second)]})
        self.assertNotEqual(payload_conflict.returncode, 0)
        invalid = self.action({**data, "request_id": "new-invalid",
                               "candidates": [{"ticket_id": second["id"],
                                               "expected_revision": True}]})
        self.assertNotEqual(invalid.returncode, 0)
        self.assertEqual(self.receipt_count(), 1)
        self.assertEqual(self.claim_events(), [(first["id"], "agent:cli-candidate")])
        current = {ticket["id"]: ticket for ticket in self.store.state()["tickets"]}
        self.assertEqual(current[second["id"]]["status"], "queued")

    def test_request_id_namespace_is_shared_with_create_plan(self):
        first = self.create("Plan then claim")
        planned = self.action({"request_id": "cross-plan-first", "tickets": [
            {"key": "one", "title": "Planned item"},
        ]}, name="create_plan")
        self.assertEqual(planned.returncode, 0, planned.stderr)
        rejected_claim = self.action({
            "request_id": "cross-plan-first", "candidates": [self.candidate(first)],
            "assignee": "agent:cli-candidate", "actual_model": "unknown",
            "actual_effort": "unknown",
        })
        self.assertNotEqual(rejected_claim.returncode, 0)
        self.assertEqual(self.store.context(first["id"])["ticket"]["status"], "queued")

        second = self.create("Claim then plan")
        claimed = self.action({
            "request_id": "cross-claim-first", "candidates": [self.candidate(second)],
            "assignee": "agent:cli-candidate", "actual_model": "unknown",
            "actual_effort": "unknown",
        })
        self.assertEqual(claimed.returncode, 0, claimed.stderr)
        rejected_plan = self.action({"request_id": "cross-claim-first", "tickets": [
            {"key": "two", "title": "Must not be created"},
        ]}, name="create_plan")
        self.assertNotEqual(rejected_plan.returncode, 0)
        self.assertNotIn("Must not be created",
                         {ticket["title"] for ticket in self.store.state()["tickets"]})


if __name__ == "__main__":
    unittest.main()
