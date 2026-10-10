"""A closed parent's reviewed child membership cannot change indirectly."""

import tempfile
import unittest
from pathlib import Path

from agentrelay.store import DomainError, Store


EVIDENCE = [{"kind": "test", "label": "Scope fixture", "uri": "local://scope"}]


class ClosedParentScopeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="agentrelay-closed-scope-")
        self.store = Store(Path(self.directory.name) / "tickets.db")

    def tearDown(self):
        self.directory.cleanup()

    def create(self, title, **fields):
        return self.store.action("create_ticket", {"title": title, **fields})

    def close_parent(self, status):
        parent = self.create("Parent", acceptance=["Scope checked"])
        child = self.create("Cancelled child", parent_id=parent["id"])
        child = self.store.action("transition", {"id": child["id"],
            "expected_revision": child["revision"], "status": "cancelled"})
        if status == "done":
            parent = self.store.action("claim_ticket", {"id": parent["id"],
                "expected_revision": parent["revision"], "assignee": "owner"}, "agent:owner")
            parent = self.store.action("submit_ticket", {"id": parent["id"],
                "expected_revision": parent["revision"], "summary": "Scope delivered",
                "evidence": EVIDENCE}, "agent:owner")
            parent = self.store.action("complete_ticket", {"id": parent["id"],
                "expected_revision": parent["revision"], "verification": "Scope reviewed",
                "accepted_criteria": ["Scope checked"]}, "agent:reviewer")
        else:
            parent = self.store.action("transition", {"id": parent["id"],
                "expected_revision": parent["revision"], "status": "cancelled"})
        self.assertEqual(parent["status"], status)
        return parent, child

    def assert_conflict(self, action, data):
        with self.assertRaises(DomainError) as caught:
            self.store.action(action, data)
        self.assertEqual(caught.exception.status, 409)

    def test_detach_and_move_from_closed_parent_roll_back_all_fields_and_events(self):
        for status in ("done", "cancelled"):
            parent, child = self.close_parent(status)
            target = self.create("Open target")
            dependency = self.create("Independent dependency")
            for destination in (None, target["id"]):
                with self.subTest(status=status, destination=destination):
                    parent_before = self.store.context(parent["id"])
                    child_before = self.store.context(child["id"])
                    target_before = self.store.context(target["id"])
                    self.assert_conflict("update_ticket", {
                        "id": child["id"], "expected_revision": child["revision"],
                        "parent_id": destination, "description": "Should roll back",
                        "depends_on": [dependency["id"]],
                    })
                    self.assertEqual(self.store.context(parent["id"]), parent_before)
                    self.assertEqual(self.store.context(child["id"]), child_before)
                    self.assertEqual(self.store.context(target["id"]), target_before)
                    self.assertEqual([ticket["id"] for ticket in parent_before["children"]],
                                     [child["id"]])

    def test_open_parent_allows_detach_and_move(self):
        original = self.create("Open original")
        target = self.create("Open target")
        child = self.create("Child", parent_id=original["id"])
        child = self.store.action("update_ticket", {"id": child["id"],
            "expected_revision": child["revision"], "parent_id": None})
        self.assertIsNone(child["parent_id"])
        self.assertEqual(self.store.context(original["id"])["children"], [])
        child = self.store.action("update_ticket", {"id": child["id"],
            "expected_revision": child["revision"], "parent_id": target["id"]})
        self.assertEqual(child["parent_id"], target["id"])
        child = self.store.action("update_ticket", {"id": child["id"],
            "expected_revision": child["revision"], "parent_id": original["id"]})
        self.assertEqual(child["parent_id"], original["id"])
        self.assertEqual(self.store.context(target["id"])["children"], [])

    def test_reopening_old_parent_with_reason_allows_detach(self):
        parent, child = self.close_parent("done")
        reopened = self.store.action("transition", {"id": parent["id"],
            "expected_revision": parent["revision"], "status": "queued",
            "reason": "Revise child scope"}, "agent:reviewer")
        self.assertEqual(reopened["status"], "queued")
        updated = self.store.action("update_ticket", {"id": child["id"],
            "expected_revision": child["revision"], "parent_id": None})
        self.assertIsNone(updated["parent_id"])
        self.assertEqual(self.store.context(parent["id"])["children"], [])
        self.assertEqual(self.store.context(parent["id"])["ticket"]["status"], "queued")

    def test_nonrelational_edit_of_cancelled_child_preserves_closed_parent(self):
        parent, child = self.close_parent("done")
        dependency = self.create("External task")
        edited = self.store.action("update_ticket", {"id": child["id"],
            "expected_revision": child["revision"], "description": "Historical note",
            "depends_on": [dependency["id"]]})
        self.assertEqual(edited["description"], "Historical note")
        self.assertEqual(edited["depends_on"], [dependency["id"]])
        self.assertEqual(edited["parent_id"], parent["id"])
        self.assertEqual(self.store.context(parent["id"])["ticket"]["revision"],
                         parent["revision"])
        self.assertEqual([ticket["id"] for ticket in self.store.context(parent["id"])["children"]],
                         [child["id"]])

    def test_reopening_child_keeps_historical_parent_and_cannot_detach(self):
        parent, child = self.close_parent("done")
        reopened_child = self.store.action("transition", {"id": child["id"],
            "expected_revision": child["revision"], "status": "queued",
            "reason": "Continue child work"})
        self.assertEqual(reopened_child["parent_id"], parent["id"])
        parent_before = self.store.context(parent["id"])
        self.assertEqual(parent_before["ticket"]["status"], "done")
        self.assertEqual(parent_before["ticket"]["revision"], parent["revision"])
        self.assert_conflict("update_ticket", {"id": child["id"],
            "expected_revision": reopened_child["revision"], "parent_id": None})
        self.assertEqual(self.store.context(parent["id"]), parent_before)
        self.assertEqual(self.store.context(child["id"])["ticket"]["parent_id"], parent["id"])

    def test_closed_destination_guard_and_explicit_noop_remain(self):
        for status in ("done", "cancelled"):
            parent, child = self.close_parent(status)
            unrelated = self.create("Unrelated")
            self.assert_conflict("create_ticket", {"title": "New child", "parent_id": parent["id"]})
            self.assert_conflict("update_ticket", {"id": unrelated["id"],
                "expected_revision": unrelated["revision"], "parent_id": parent["id"]})
            self.assert_conflict("update_ticket", {"id": child["id"],
                "expected_revision": child["revision"], "parent_id": parent["id"]})
            self.assertEqual(self.store.context(parent["id"])["ticket"]["revision"],
                             parent["revision"])

    def test_stale_child_revision_still_rejected_without_mutation(self):
        parent = self.create("Open parent")
        child = self.create("Child", parent_id=parent["id"])
        updated = self.store.action("update_ticket", {"id": child["id"],
            "expected_revision": child["revision"], "title": "Revised child"})
        before = self.store.context(child["id"])
        self.assert_conflict("update_ticket", {"id": child["id"],
            "expected_revision": child["revision"], "parent_id": None})
        self.assertEqual(self.store.context(child["id"]), before)
        self.assertEqual(updated["parent_id"], parent["id"])


if __name__ == "__main__":
    unittest.main()
