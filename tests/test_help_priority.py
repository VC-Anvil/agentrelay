"""Help inherits queue priority at creation without later priority propagation."""

import tempfile
import unittest
from pathlib import Path

from agentrelay.__main__ import ready_work
from agentrelay.store import DomainError, Store


WORKER = {"profile_ids": [], "model": "gpt-6-sol", "effort": "high"}
HELP_CRITERION = "La ayuda solicitada está documentada y revisada."
EVIDENCE = [{"kind": "file", "label": "Help report", "uri": "local://help-report"}]


class HelpPriorityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="agentrelay-help-priority-")
        self.store = Store(Path(self.directory.name) / "tickets.sqlite")

    def tearDown(self):
        self.directory.cleanup()

    def request_help(self, priority):
        parent = self.store.action("create_ticket", {"title": f"Parent {priority}",
            "priority": priority, "acceptance": ["Parent work reviewed"]})
        claimed = self.store.action("claim_ticket", {"id": parent["id"],
            "expected_revision": parent["revision"], "assignee": "agent:owner"}, "agent:owner")
        return self.store.action("request_help", {"id": parent["id"],
            "expected_revision": claimed["revision"], "title": f"Help {priority}",
            "description": "Unblock the parent", "profile_id": "terra"}, "agent:owner")

    def test_help_priority_changes_ready_work_order_without_preemption(self):
        requested = {level: self.request_help(level) for level in ("urgent", "high", "low")}
        competing = self.store.action("create_ticket", {"title": "Other high work",
            "priority": "high", "acceptance": ["Reviewed"]})

        for level, result in requested.items():
            parent, child = result["parent"], result["child"]
            self.assertEqual(parent["status"], "blocked")
            self.assertIn(child["id"], parent["depends_on"])
            self.assertEqual(child["parent_id"], parent["id"])
            self.assertEqual(child["priority"], level)
            self.assertEqual(child["profile_id"], "terra")
            self.assertEqual(child["status"], "queued")

        order = [ticket["id"] for ticket in ready_work(self.store, WORKER)]
        self.assertEqual(order, [requested["urgent"]["child"]["id"],
                                 requested["high"]["child"]["id"],
                                 competing["id"], requested["low"]["child"]["id"]])

    def test_parent_reprioritization_does_not_change_assigned_help_or_review(self):
        result = self.request_help("urgent")
        parent, child = result["parent"], result["child"]
        claimed = self.store.action("claim_ticket", {"id": child["id"],
            "expected_revision": child["revision"], "assignee": "agent:helper"}, "agent:helper")
        self.assertNotIn(child["id"], [item["id"] for item in ready_work(self.store, WORKER)])

        updated_parent = self.store.action("update_ticket", {"id": parent["id"],
            "expected_revision": parent["revision"], "priority": "low"}, "agent:owner")
        unchanged_help = self.store.context(child["id"])["ticket"]
        self.assertEqual(updated_parent["priority"], "low")
        self.assertEqual(unchanged_help["priority"], "urgent")
        self.assertEqual(unchanged_help["revision"], claimed["revision"])
        self.assertEqual(unchanged_help["assignee"], "agent:helper")

        submitted = self.store.action("submit_ticket", {"id": child["id"],
            "expected_revision": claimed["revision"], "summary": "Help delivered",
            "evidence": EVIDENCE}, "agent:helper")
        with self.assertRaises(DomainError) as caught:
            self.store.action("complete_ticket", {"expected_acceptance_context_token": self.store.context(child["id"])["acceptance_context"]["token"], "id": child["id"],
                "expected_revision": submitted["revision"], "verification": "Checked",
                "accepted_criteria": [HELP_CRITERION]}, "agent:helper")
        self.assertEqual(caught.exception.status, 409)
        completed = self.store.action("complete_ticket", {"expected_acceptance_context_token": self.store.context(child["id"])["acceptance_context"]["token"], "id": child["id"],
            "expected_revision": submitted["revision"], "verification": "Help report checked",
            "accepted_criteria": [HELP_CRITERION]}, "agent:reviewer")
        self.assertEqual(completed["status"], "done")
        self.assertEqual(self.store.context(parent["id"])["ticket"]["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
