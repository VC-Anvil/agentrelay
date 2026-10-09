"""Active acceptance can grow while retaining audit and ownership rules."""

import tempfile
import unittest
from pathlib import Path

from agentrelay.store import DomainError, Store


EVIDENCE = [{"kind": "file", "label": "Review sample", "uri": "local://sample"}]


class AcceptanceUpdateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="agentrelay-acceptance-")
        self.store = Store(Path(self.directory.name) / "tickets.sqlite")

    def tearDown(self):
        self.directory.cleanup()

    def active_ticket(self, status):
        ticket = self.store.action("create_ticket", {"title": f"Scope in {status}",
            "acceptance": ["Original criterion"]})
        ticket = self.store.action("claim_ticket", {"id": ticket["id"],
            "expected_revision": ticket["revision"], "assignee": "agent:owner"}, "agent:owner")
        if status == "review":
            ticket = self.store.action("submit_ticket", {"id": ticket["id"],
                "expected_revision": ticket["revision"], "summary": "Ready for review",
                "evidence": EVIDENCE}, "agent:owner")
        return ticket

    def assert_rejected_without_changes(self, ticket, data, actor):
        before = self.store.context(ticket["id"])
        with self.assertRaises(DomainError) as caught:
            self.store.action("update_ticket", {"id": ticket["id"], **data}, actor)
        self.assertEqual(caught.exception.status, 409)
        after = self.store.context(ticket["id"])
        self.assertEqual(after["ticket"], before["ticket"])
        self.assertEqual(after["events"], before["events"])

    def test_expansion_audits_before_after_in_progress_and_review(self):
        for status in ("in_progress", "review"):
            with self.subTest(status=status):
                ticket = self.active_ticket(status)
                self.assert_rejected_without_changes(ticket, {"expected_revision": ticket["revision"],
                    "acceptance": ["Original criterion", "New criterion"]}, "agent:other")
                self.assert_rejected_without_changes(ticket, {"expected_revision": ticket["revision"] - 1,
                    "acceptance": ["Original criterion", "New criterion"]}, "agent:owner")
                self.assert_rejected_without_changes(ticket, {"expected_revision": ticket["revision"],
                    "acceptance": ["Replacement criterion"]}, "agent:owner")

                expanded = self.store.action("update_ticket", {"id": ticket["id"],
                    "expected_revision": ticket["revision"], "title": f"Expanded {status}",
                    "acceptance": ["Original criterion", "New criterion"]}, "agent:owner")
                self.assertEqual(expanded["status"], status)
                self.assertEqual(expanded["revision"], ticket["revision"] + 1)
                self.assertEqual(expanded["acceptance"], ["Original criterion", "New criterion"])
                event = self.store.context(ticket["id"])["events"][0]
                self.assertEqual(event["action"], "update_ticket")
                self.assertEqual(event["actor"], "agent:owner")
                self.assertEqual(event["details"]["before"], {
                    "acceptance": ["Original criterion"], "title": ticket["title"]})
                self.assertEqual(event["details"]["after"], {
                    "acceptance": ["Original criterion", "New criterion"],
                    "title": f"Expanded {status}"})

                if status == "review":
                    self.assert_rejected_without_changes(expanded, {
                        "expected_revision": expanded["revision"],
                        "acceptance": ["Original criterion"]}, "agent:owner")
                    completed = self.store.action("complete_ticket", {"id": ticket["id"],
                        "expected_revision": expanded["revision"], "verification": "Both criteria checked",
                        "accepted_criteria": ["Original criterion", "New criterion"]}, "agent:reviewer")
                    self.assertEqual(completed["status"], "done")

    def test_owned_blocked_ticket_keeps_criteria_but_allows_expansion(self):
        parent = self.active_ticket("in_progress")
        blocked = self.store.action("request_help", {"id": parent["id"],
            "expected_revision": parent["revision"], "title": "Resolve question",
            "description": "A dependency needs clarification"}, "agent:owner")["parent"]
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["assignee"], "agent:owner")
        self.assert_rejected_without_changes(blocked, {"expected_revision": blocked["revision"],
            "acceptance": ["Replacement criterion"]}, "agent:owner")
        self.assert_rejected_without_changes(blocked, {"expected_revision": blocked["revision"],
            "acceptance": ["Original criterion", "New criterion"]}, "agent:other")
        expanded = self.store.action("update_ticket", {"id": blocked["id"],
            "expected_revision": blocked["revision"],
            "acceptance": ["Original criterion", "New criterion"]}, "agent:owner")
        self.assertEqual(expanded["status"], "blocked")
        self.assertEqual(expanded["revision"], blocked["revision"] + 1)
        details = self.store.context(parent["id"])["events"][0]["details"]
        self.assertEqual(details["before"]["acceptance"], ["Original criterion"])
        self.assertEqual(details["after"]["acceptance"], ["Original criterion", "New criterion"])

    def test_planning_and_unassigned_blocked_can_change_criteria(self):
        queued = self.store.action("create_ticket", {"title": "Queued planning",
            "acceptance": ["Old", "Obsolete"]})
        queued = self.store.action("update_ticket", {"id": queued["id"],
            "expected_revision": queued["revision"], "acceptance": ["Revised"]})
        self.assertEqual(queued["acceptance"], ["Revised"])
        backlog = self.store.action("transition", {"id": queued["id"],
            "expected_revision": queued["revision"], "status": "backlog"})
        backlog = self.store.action("update_ticket", {"id": backlog["id"],
            "expected_revision": backlog["revision"], "acceptance": ["Backlog revised"]})
        self.assertEqual(backlog["acceptance"], ["Backlog revised"])

        unassigned = self.store.action("create_ticket", {"title": "Unassigned planning",
            "acceptance": ["Original", "Obsolete"]})
        blocked = self.store.action("request_help", {"id": unassigned["id"],
            "expected_revision": unassigned["revision"], "title": "Ask for planning help",
            "description": "Scope clarification"})["parent"]
        self.assertIsNone(blocked["assignee"])
        changed = self.store.action("update_ticket", {"id": blocked["id"],
            "expected_revision": blocked["revision"], "acceptance": ["Revised"]})
        self.assertEqual(changed["acceptance"], ["Revised"])


if __name__ == "__main__":
    unittest.main()
