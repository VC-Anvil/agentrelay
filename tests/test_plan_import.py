"""Atomic, repeatable imports of ticket plans."""

from concurrent.futures import ThreadPoolExecutor
import copy
from pathlib import Path
import tempfile
import unittest

from agentrelay.store import DomainError, Store


class PlanImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-plan-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "tickets.sqlite"
        self.store = Store(self.path)

    def plan(self, request_id="plan-1"):
        return {"request_id": request_id, "tickets": [
            {"key": "child", "title": "Write report", "parent_key": "root",
             "depends_on_keys": ["research"], "status": "queued", "profile_id": "sol",
             "acceptance": ["Report reviewed"]},
            {"key": "root", "title": "Publish report", "type": "objective",
             "acceptance": ["Publication reviewed"]},
            {"key": "research", "title": "Research inputs", "parent_key": "root",
             "acceptance": ["Sources recorded"]},
        ]}

    def test_forward_references_defaults_events_and_existing_relations(self):
        existing = self.store.action("create_ticket", {"title": "Existing dependency"})["id"]
        plan = self.plan()
        plan["tickets"][0]["depends_on"] = [existing]
        plan["tickets"].append({"key": "external-child", "title": "Attach to existing scope",
                                "parent_id": existing})
        result = self.store.action("create_plan", plan, actor="agent:planner")
        ids = result["key_to_id"]
        self.assertEqual(list(ids), ["child", "root", "research", "external-child"])
        child, root, research = (next(t for t in result["tickets"] if t["id"] == ids[key])
                                 for key in ("child", "root", "research"))
        self.assertEqual(child["parent_id"], root["id"])
        self.assertEqual(child["depends_on"], sorted([existing, research["id"]]))
        self.assertEqual(child["status"], "queued")
        self.assertFalse(child["ready"])
        self.assertEqual(root["status"], "backlog")
        self.assertEqual(research["status"], "backlog")
        self.assertEqual(child["profile_id"], "sol")
        self.assertEqual(next(t for t in result["tickets"] if t["id"] == ids["external-child"])["parent_id"],
                         existing)
        events = self.store.export()["events"]
        self.assertEqual(sum(event["action"] == "create_plan_ticket" for event in events), 4)
        self.assertEqual(sum(event["action"] == "create_plan" for event in events), 1)
        self.assertEqual({event["actor"] for event in events if event["action"].startswith("create_plan")},
                         {"agent:planner"})

    def test_late_error_rolls_back_tickets_events_counter_and_request(self):
        before = self.store.export()
        invalid = self.plan()
        invalid["tickets"][-1]["depends_on_keys"] = ["root"]  # root waits for its children.
        with self.assertRaises(DomainError) as caught:
            self.store.action("create_plan", invalid)
        self.assertEqual(caught.exception.status, 409)
        after = self.store.export()
        self.assertEqual(after["tickets"], before["tickets"])
        self.assertEqual(after["events"], before["events"])
        self.assertEqual(self.store.action("create_plan", self.plan())["key_to_id"]["child"], "AR-0001")

    def test_cycles_and_ambiguous_relations_rejected(self):
        for change in (
            lambda p: p["tickets"][1].update(parent_key="child"),
            lambda p: p["tickets"][0].update(parent_id="AR-0001"),
            lambda p: p["tickets"][0].update(depends_on_keys=["research", "research"]),
        ):
            candidate = self.plan()
            change(candidate)
            with self.assertRaises(DomainError):
                self.store.action("create_plan", candidate)
            self.assertEqual(self.store.state()["tickets"], [])

    def test_external_ids_are_persisted_normalized_and_empty_parent_is_null(self):
        parent = self.store.action("create_ticket", {"title": "Existing parent"})["id"]
        dependency = self.store.action("create_ticket", {"title": "Existing dependency"})["id"]
        result = self.store.action("create_plan", {"request_id": "normalized", "tickets": [
            {"key": "first", "title": "First", "parent_id": f" {parent} ",
             "depends_on": [f" {dependency} "]},
            {"key": "second", "title": "Second", "parent_id": ""},
        ]})
        first, second = result["tickets"]
        self.assertEqual(first["parent_id"], parent)
        self.assertEqual(first["depends_on"], [dependency])
        self.assertIsNone(second["parent_id"])
        self.assertEqual(self.store.context(first["id"])["parent"]["id"], parent)

    def test_idempotence_reopen_canonical_payload_and_concurrent_callers(self):
        data = self.plan()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: Store(self.path).action("create_plan", data, "agent:planner"),
                                    range(2)))
        self.assertEqual(results[0], results[1])
        reopened = Store(self.path)
        reordered = {"tickets": [{key: entry[key] for key in reversed(list(entry))}
                                 for entry in data["tickets"]], "request_id": "plan-1"}
        self.assertEqual(reopened.action("create_plan", reordered, "agent:planner"), results[0])
        self.assertEqual(len(reopened.state()["tickets"]), 3)
        self.assertEqual(len(reopened.state()["events"]), 4)
        with self.assertRaises(DomainError) as actor_conflict:
            reopened.action("create_plan", data, "human")
        self.assertEqual(actor_conflict.exception.status, 409)
        changed = copy.deepcopy(data)
        changed["tickets"][0]["title"] = "Different scope"
        with self.assertRaises(DomainError) as payload_conflict:
            reopened.action("create_plan", changed, "agent:planner")
        self.assertEqual(payload_conflict.exception.status, 409)

    def test_limits_profiles_and_initial_status(self):
        invalid_cases = [
            {"request_id": "x", "tickets": []},
            {"request_id": "x", "tickets": [{"key": str(i), "title": "Ticket"} for i in range(65)]},
            {"request_id": "x" * 129, "tickets": [{"key": "one", "title": "Ticket"}]},
            {"request_id": "x", "tickets": [{"key": "k" * 65, "title": "Ticket"}]},
            {"request_id": "x", "tickets": [{"key": "one", "title": "Ticket", "status": "done"}]},
            {"request_id": "x", "tickets": [{"key": "one", "title": "Ticket", "profile_id": "missing"}]},
            {"request_id": "x", "tickets": [{"key": "one", "title": "\ud800"}]},
            {"request_id": "x", "tickets": [{"key": "one", "title": "Ticket",
                                                "depends_on_keys": [" one "]}]},
            {"request_id": "x", "tickets": [{"key": "one", "title": "Ticket"},
                                                {"key": "one", "title": "Other"}]},
        ]
        for data in invalid_cases:
            with self.subTest(data=data), self.assertRaises(DomainError):
                self.store.action("create_plan", data)
            self.assertEqual(self.store.state()["tickets"], [])


if __name__ == "__main__":
    unittest.main()
