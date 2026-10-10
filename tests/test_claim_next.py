"""Caller-scoped atomic claims across independent SQLite connections."""

from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest

from agentrelay.store import DomainError, Store


class ClaimNextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-claim-next-")
        self.path = Path(self.temp.name) / "tickets.sqlite"
        self.store = Store(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def ticket(self, title, **fields):
        return self.store.action("create_ticket", {"title": title,
            "acceptance": ["Independent review"], **fields})

    @staticmethod
    def candidate(ticket):
        return {"ticket_id": ticket["id"], "expected_revision": ticket["revision"]}

    def data(self, request_id, candidates, **changes):
        return {"request_id": request_id, "candidates": candidates,
                "assignee": "agent:worker", "actual_model": "unknown",
                "actual_effort": "unknown", **changes}

    def action(self, data, *, store=None, actor="agent:worker"):
        return (store or self.store).action("claim_next_ticket", data, actor)

    def events(self, action=None):
        with self.store._connection() as db:
            if action is None:
                return db.execute("SELECT id,action,details FROM events ORDER BY id").fetchall()
            return db.execute("SELECT id,action,details FROM events WHERE action=? ORDER BY id",
                              (action,)).fetchall()

    def test_priority_scope_and_audit_claim_only_one(self):
        outside = self.ticket("Outside urgent", priority="urgent")
        low = self.ticket("Low", priority="low")
        normal = self.ticket("Normal", priority="normal")
        high = self.ticket("High", priority="high")
        result = self.action(self.data("scope-1", [self.candidate(low), self.candidate(normal),
                                                   self.candidate(high)]))
        self.assertEqual(result["ticket"]["id"], high["id"])
        self.assertEqual(result["ticket"]["status"], "in_progress")
        self.assertEqual(result["ticket"]["assignee"], "agent:worker")
        self.assertEqual(result["skipped"], [])
        self.assertEqual(self.store.context(outside["id"])["ticket"]["status"], "queued")
        self.assertEqual(self.store.context(normal["id"])["ticket"]["status"], "queued")
        self.assertEqual(self.store.context(low["id"])["ticket"]["status"], "queued")
        self.assertEqual(len(self.events("claim_ticket")), 1)
        audit = json.loads(self.events("claim_next_ticket")[0]["details"])
        self.assertEqual(audit, {"request_id": "scope-1", "selected_ticket_id": high["id"],
                                 "skipped": []})

        urgent = self.ticket("Scoped urgent", priority="urgent")
        result = self.action(self.data("scope-2", [self.candidate(low), self.candidate(urgent)]))
        self.assertEqual(result["ticket"]["id"], urgent["id"])

    def test_same_priority_uses_creation_time_then_ticket_id(self):
        late = self.ticket("Late")
        early = self.ticket("Early")
        tie = self.ticket("Tie")
        with self.store._write() as db:
            db.execute("UPDATE tickets SET created_at=? WHERE id=?",
                       ("2026-01-02T00:00:00Z", late["id"]))
            for ticket in (early, tie):
                db.execute("UPDATE tickets SET created_at=? WHERE id=?",
                           ("2026-01-01T00:00:00Z", ticket["id"]))
        result = self.action(self.data("tie-break", [self.candidate(tie),
                                                     self.candidate(late), self.candidate(early)]))
        self.assertEqual(result["ticket"]["id"], early["id"])
        self.assertEqual(self.store.context(tie["id"])["ticket"]["status"], "queued")

    def test_identifiers_allow_internal_spaces_like_create_plan(self):
        ticket = self.ticket("Internal spaces")
        payload = self.data("request with spaces", [self.candidate(ticket)],
                            assignee="agent:worker team", actual_model="declared model",
                            actual_effort="declared effort")
        result = self.action(payload, actor="agent:worker team")
        self.assertEqual(result["ticket"]["id"], ticket["id"])
        self.assertEqual(result["ticket"]["actual_model"], "declared model")

    def test_skips_use_candidate_order_and_respect_graph_lifecycle_acceptance_profile(self):
        dependency = self.ticket("Dependency")
        waiting = self.ticket("Waiting", depends_on=[dependency["id"]])
        parent = self.ticket("Parent", type="objective")
        self.ticket("Child", parent_id=parent["id"])
        backlog = self.ticket("Backlog")
        backlog = self.store.action("transition", {"id": backlog["id"],
            "expected_revision": 1, "status": "backlog"})
        closed = self.ticket("Cancelled")
        closed = self.store.action("transition", {"id": closed["id"],
            "expected_revision": 1, "status": "cancelled"})
        no_acceptance = self.store.action("create_ticket", {"title": "No criteria"})
        astra = self.ticket("Locked coordinator", profile_id="astra")
        stale = self.ticket("Changed since review")
        self.store.action("update_ticket", {"id": stale["id"], "expected_revision": 1,
                                            "description": "Fresh revision"})
        eligible = self.ticket("Eligible", priority="low")
        candidates = [self.candidate(ticket) for ticket in
                      (stale, astra, waiting, parent, backlog, closed, no_acceptance, eligible)]
        result = self.action(self.data("skips-1", candidates))
        self.assertEqual(result["ticket"]["id"], eligible["id"])
        self.assertEqual(result["skipped"], [
            {"ticket_id": stale["id"], "reason": "stale_revision"},
            {"ticket_id": astra["id"], "reason": "incompatible_profile"},
            {"ticket_id": waiting["id"], "reason": "not_ready"},
            {"ticket_id": parent["id"], "reason": "not_ready"},
            {"ticket_id": backlog["id"], "reason": "not_ready"},
            {"ticket_id": closed["id"], "reason": "not_ready"},
            {"ticket_id": no_acceptance["id"], "reason": "missing_acceptance"},
        ])
        self.assertEqual(self.store.context(astra["id"])["ticket"]["status"], "queued")
        self.assertEqual(self.store.context(dependency["id"])["ticket"]["status"], "queued")

        exact = self.data("astra-exact", [self.candidate(astra)],
                          actual_model="gpt-6-astra", actual_effort="high")
        self.assertEqual(self.action(exact)["ticket"]["id"], astra["id"])

    def test_unknown_candidate_rolls_back_all_claims_events_and_receipt(self):
        available = self.ticket("Available")
        before_events = len(self.events())
        data = self.data("unknown-1", [self.candidate(available),
                                       {"ticket_id": "AR-9999", "expected_revision": 1}])
        with self.assertRaises(DomainError) as caught:
            self.action(data)
        self.assertEqual(caught.exception.status, 404)
        self.assertEqual(self.store.context(available["id"])["ticket"]["status"], "queued")
        self.assertEqual(len(self.events()), before_events)
        with self.store._connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM claim_requests").fetchone()[0], 0)

    def test_idle_receipt_is_historical_and_backup_preserves_replay(self):
        candidate = self.store.action("create_ticket", {"title": "Needs criteria"})
        payload = self.data("idle-1", [self.candidate(candidate)])
        idle = self.action(payload)
        self.assertEqual(idle, {"request_id": "idle-1", "ticket": None,
                                "skipped": [{"ticket_id": candidate["id"],
                                             "reason": "missing_acceptance"}]})
        self.store.action("update_ticket", {"id": candidate["id"], "expected_revision": 1,
                                            "acceptance": ["Review criteria"]})
        events_before = len(self.events())
        self.assertEqual(self.action(payload), idle)
        self.assertEqual(len(self.events()), events_before)
        fresh = self.action(self.data("idle-2", [{"ticket_id": candidate["id"],
                                                   "expected_revision": 2}]))
        self.assertEqual(fresh["ticket"]["id"], candidate["id"])
        backup = Path(self.temp.name) / "backup.sqlite"
        self.store.backup(backup)
        restored = Store(backup)
        self.assertEqual(self.action(payload, store=restored), idle)
        self.assertEqual(self.action(self.data("idle-2", [{"ticket_id": candidate["id"],
                                                            "expected_revision": 2}]),
                                     store=restored), fresh)

    def test_claim_replay_after_ticket_changes_and_payload_actor_conflicts(self):
        ticket = self.ticket("Reviewed candidate")
        payload = self.data("claim-once", [self.candidate(ticket)])
        first = self.action(payload)
        self.store.action("checkpoint", {"id": ticket["id"], "expected_revision": 2,
                                         "checkpoint": "Work advanced"}, actor="agent:worker")
        events_before = len(self.events())
        self.assertEqual(self.action(payload), first)
        reordered = {key: payload[key] for key in reversed(tuple(payload))}
        reordered["candidates"] = [{"expected_revision": 1, "ticket_id": ticket["id"]}]
        self.assertEqual(self.action(reordered), first)
        self.assertEqual(len(self.events()), events_before)
        for changed, actor in ((self.data("claim-once", [self.candidate(ticket)],
                                         actual_effort="high"), "agent:worker"),
                               (payload, "human")):
            with self.subTest(actor=actor), self.assertRaises(DomainError) as caught:
                self.action(changed, actor=actor)
            self.assertEqual(caught.exception.status, 409)
        self.assertEqual(len(self.events()), events_before)

    def test_plan_request_id_cannot_be_reused_for_claim(self):
        plan = {"request_id": "shared-plan-first", "tickets": [
            {"key": "planned", "title": "Planned candidate", "status": "queued",
             "acceptance": ["Review result"]}]}
        created = self.store.action("create_plan", plan, actor="agent:worker")
        ticket = created["tickets"][0]
        before = self.store.state()
        with self.assertRaises(DomainError) as caught:
            self.action(self.data(plan["request_id"], [self.candidate(ticket)]))
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.store.state(), before)
        self.assertEqual(self.store.action("create_plan", plan, actor="agent:worker"), created)
        with self.store._connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM plan_requests").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM claim_requests").fetchone()[0], 0)

    def test_claim_request_id_cannot_be_reused_for_plan(self):
        ticket = self.ticket("Claimed candidate")
        payload = self.data("shared-claim-first", [self.candidate(ticket)])
        claimed = self.action(payload)
        before = self.store.state()
        plan = {"request_id": payload["request_id"], "tickets": [
            {"key": "new", "title": "Should not be created"}]}
        with self.assertRaises(DomainError) as caught:
            self.store.action("create_plan", plan, actor="agent:worker")
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.store.state(), before)
        self.assertEqual(self.action(payload), claimed)
        with self.store._connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM plan_requests").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM claim_requests").fetchone()[0], 1)

    def test_two_distinct_requests_claim_two_reviewed_tickets(self):
        first = self.ticket("First")
        second = self.ticket("Second")
        candidates = [self.candidate(first), self.candidate(second)]
        barrier = threading.Barrier(2)
        stores = [Store(self.path), Store(self.path)]

        def claim(request_id, independent):
            barrier.wait(timeout=5)
            return self.action(self.data(request_id, candidates), store=independent)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(claim, request_id, independent)
                       for request_id, independent in zip(("parallel-1", "parallel-2"), stores)]
            results = [future.result(timeout=10) for future in futures]
        self.assertEqual({result["ticket"]["id"] for result in results}, {first["id"], second["id"]})
        self.assertEqual(sorted(len(result["skipped"]) for result in results), [0, 1])
        self.assertEqual(len(self.events("claim_ticket")), 2)
        self.assertEqual(len(self.events("claim_next_ticket")), 2)

    def test_same_request_concurrent_replays_one_historical_claim(self):
        ticket = self.ticket("Only one")
        payload = self.data("parallel-same", [self.candidate(ticket)])
        barrier = threading.Barrier(2)
        stores = [Store(self.path), Store(self.path)]

        def claim(independent):
            barrier.wait(timeout=5)
            return self.action(copy.deepcopy(payload), store=independent)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(claim, independent) for independent in stores]
            results = [future.result(timeout=10) for future in futures]
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0]["ticket"]["id"], ticket["id"])
        self.assertEqual(len(self.events("claim_ticket")), 1)
        self.assertEqual(len(self.events("claim_next_ticket")), 1)
        with self.store._connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM claim_requests").fetchone()[0], 1)

    def test_strict_envelope_identity_boundaries_and_no_events_on_errors(self):
        ticket = self.ticket("Validation target")
        base = self.data("r", [self.candidate(ticket)])
        bad = []
        for key in ("request_id", "assignee", "actual_model", "actual_effort"):
            for value in ("", " edge", "edge ", "x" * 129, None, 42):
                payload = copy.deepcopy(base)
                payload[key] = value
                bad.append(payload)
        for entry in ([], [self.candidate(ticket)] * 65,
                      [self.candidate(ticket), self.candidate(ticket)],
                      [{"ticket_id": "", "expected_revision": 1}],
                      [{"ticket_id": " AR-0001", "expected_revision": 1}],
                      [{"ticket_id": "x" * 129, "expected_revision": 1}],
                      [{"ticket_id": ticket["id"], "expected_revision": True}],
                      [{"ticket_id": ticket["id"], "expected_revision": 1.5}],
                      [{"ticket_id": ticket["id"], "expected_revision": 0}],
                      [{"ticket_id": ticket["id"]}],
                      [{"ticket_id": ticket["id"], "expected_revision": 1, "extra": 1}]):
            payload = copy.deepcopy(base)
            payload["candidates"] = entry
            bad.append(payload)
        bad.extend(({**base, "extra": 1}, {key: value for key, value in base.items()
                                            if key != "actual_model"}))
        events_before = len(self.events())
        for index, payload in enumerate(bad):
            with self.subTest(index=index), self.assertRaises(DomainError) as caught:
                self.action(payload)
            self.assertEqual(caught.exception.status, 400)
        with self.assertRaises(DomainError) as caught:
            self.action(base, actor="agent:other")
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(len(self.events()), events_before)
        self.assertEqual(self.store.context(ticket["id"])["ticket"]["status"], "queued")
        with self.store._connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM claim_requests").fetchone()[0], 0)

        boundary = self.data("r" * 128, [self.candidate(ticket)],
                             assignee="a" * 128, actual_model="m" * 128,
                             actual_effort="e" * 128)
        self.assertEqual(self.action(boundary, actor="agent:" + "a" * 128)["ticket"]["id"],
                         ticket["id"])


if __name__ == "__main__":
    unittest.main()
