"""Domain tests use a fresh SQLite file for each case."""

import tempfile
import unittest
from pathlib import Path

from agentrelay.store import DomainError, Store


EVIDENCE = [{"kind": "file", "label": "Review sample", "uri": "local://sample"}]


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="agentrelay-store-")
        self.path = Path(self.directory.name) / "tickets.db"
        self.store = Store(self.path)

    def tearDown(self):
        self.directory.cleanup()

    def create(self, title="Task", **extra):
        return self.store.action("create_ticket", {"title": title, **extra})

    def assert_error(self, status, action, data, actor="human"):
        with self.assertRaises(DomainError) as caught:
            self.store.action(action, data, actor)
        self.assertEqual(caught.exception.status, status)

    def test_schema_profiles_persistence_and_export(self):
        self.assertEqual(self.store.state()["tickets"], [])
        profiles = {p["id"]: p for p in self.store.state()["profiles"]}
        self.assertEqual(profiles["astra"]["model"], "gpt-6-astra")
        self.assertEqual(profiles["astra"]["effort"], "high")
        ticket = self.create("Persist me", acceptance=["Observed behavior passes"])
        reopened = Store(self.path)
        self.assertEqual(reopened.context(ticket["id"])["ticket"]["title"], "Persist me")
        exported = reopened.export()
        from agentrelay import __version__
        self.assertEqual(exported["version"], __version__)
        self.assertEqual(len(exported["tickets"]), 1)
        self.assertEqual(exported["events"][0]["action"], "create_ticket")

    def test_optimistic_conflict_preserves_first_writer(self):
        ticket = self.create()
        independent = Store(self.path)
        updated = self.store.action("update_ticket", {"id": ticket["id"], "expected_revision": 1,
                                                       "title": "First writer"})
        self.assertEqual(updated["revision"], 2)
        self.assert_error(409, "update_ticket", {"id": ticket["id"], "expected_revision": 1,
                                                 "title": "Second writer"})
        self.assertEqual(independent.context(ticket["id"])["ticket"]["title"], "First writer")

    def test_context_includes_recommendation_and_help_profile_catalog(self):
        custom = self.store.action("create_profile", {"name": "Audio QA", "role": "reviewer",
                                  "model": "configured-model", "effort": "high"})
        ticket = self.create("Audio evidence", profile_id=custom["id"])
        context = self.store.context(ticket["id"])
        self.assertEqual(context["profile"], custom)
        self.assertIn(custom, context["profiles"])
        self.assertIsNone(context["ticket"]["actual_model"])
        unassigned = self.create("Unassigned")
        self.assertIsNone(self.store.context(unassigned["id"])["profile"])

    def test_active_ticket_rejects_other_agent_edits(self):
        ticket = self.create("Owned", acceptance=["Outcome checked"])
        ticket = self.store.action("claim_ticket", {"id": ticket["id"], "expected_revision": 1,
                                                     "assignee": "worker"}, "agent:worker")
        self.assert_error(409, "update_ticket", {"id": ticket["id"], "expected_revision": 2,
                                                 "description": "unauthorized"}, "agent:other")
        self.assert_error(409, "checkpoint", {"id": ticket["id"], "expected_revision": 2,
                                              "checkpoint": "unauthorized"}, "agent:other")
        self.assert_error(409, "transition", {"id": ticket["id"], "expected_revision": 2,
                                              "status": "blocked", "reason": "unavailable"}, "agent:other")
        self.assert_error(409, "request_help", {"id": ticket["id"], "expected_revision": 2,
                                                "title": "Help", "description": "Details"}, "agent:other")
        self.assertEqual(self.store.context(ticket["id"])["ticket"]["revision"], 2)
        paused = self.store.action("request_help", {"id": ticket["id"], "expected_revision": 2,
                                                    "title": "Help", "description": "Details"}, "worker")["parent"]
        self.assert_error(409, "update_ticket", {"id": ticket["id"], "expected_revision": paused["revision"],
                                                 "title": "Hijacked"}, "agent:other")
        self.assert_error(409, "transition", {"id": ticket["id"], "expected_revision": paused["revision"],
                                              "status": "cancelled"}, "agent:other")
        self.assert_error(409, "split_ticket", {"id": ticket["id"], "expected_revision": paused["revision"],
                                                "children": [{"title": "Part"}]}, "agent:other")
        self.assert_error(409, "request_help", {"id": ticket["id"], "expected_revision": paused["revision"],
                                                "title": "Another", "description": "Details"}, "agent:other")

    def test_astra_claim_cannot_record_conflicting_actual_model(self):
        ticket = self.create("Coordinate", profile_id="astra")
        self.assert_error(409, "claim_ticket", {"id": ticket["id"], "expected_revision": 1,
                                                 "assignee": "astra", "actual_model": "gpt-6-sol"})
        self.assert_error(409, "claim_ticket", {"id": ticket["id"], "expected_revision": 1,
                                                 "assignee": "astra", "actual_effort": "low"})
        claimed = self.store.action("claim_ticket", {"id": ticket["id"], "expected_revision": 1,
                                                     "assignee": "astra", "actual_model": "gpt-6-astra",
                                                     "actual_effort": "high"})
        self.assertEqual(claimed["actual_model"], "gpt-6-astra")

    def test_audit_retains_create_and_update_values(self):
        ticket = self.create("Original", acceptance=["Original criterion"])
        self.store.action("update_ticket", {"id": ticket["id"], "expected_revision": 1,
                                            "title": "Revised", "acceptance": ["Revised criterion"]})
        events = self.store.context(ticket["id"])["events"]
        self.assertEqual(events[0]["details"]["before"]["acceptance"], ["Original criterion"])
        self.assertEqual(events[0]["details"]["after"]["acceptance"], ["Revised criterion"])
        self.assertEqual(events[1]["details"]["after"]["title"], "Original")

    def test_dependency_cycle_and_mixed_hierarchy_deadlock(self):
        a = self.create("A")
        b = self.create("B", depends_on=[a["id"]])
        self.assert_error(409, "update_ticket", {"id": a["id"], "expected_revision": a["revision"],
                                                 "depends_on": [b["id"]]})
        self.assertEqual(self.store.context(a["id"])["ticket"]["depends_on"], [])
        parent = self.create("Parent")
        child = self.create("Child", parent_id=parent["id"])
        self.assert_error(409, "update_ticket", {"id": child["id"], "expected_revision": 1,
                                                 "depends_on": [parent["id"]]})
        self.assert_error(409, "update_ticket", {"id": parent["id"], "expected_revision": 1,
                                                 "parent_id": child["id"]})
        self.assertTrue(self.store.context(parent["id"])["ticket"]["blockers"])

    def test_lifecycle_requires_independent_review_and_acceptance(self):
        ticket = self.create("Deliver", acceptance=["Feature works", "Failure path checked"])
        claimed = self.store.action("claim_ticket", {"id": ticket["id"], "expected_revision": 1,
                                                     "assignee": "worker", "actual_model": "local-model"}, "agent:worker")
        self.assertEqual(claimed["status"], "in_progress")
        self.assertEqual(claimed["actual_model"], "local-model")
        self.assert_error(409, "update_ticket", {"id": ticket["id"], "expected_revision": 2,
                                                 "acceptance": ["Feature works"]})
        checkpoint = self.store.action("checkpoint", {"id": ticket["id"], "expected_revision": 2,
                                                      "checkpoint": "Implemented and locally checked"}, "worker")
        submitted = self.store.action("submit_ticket", {"id": ticket["id"], "expected_revision": checkpoint["revision"],
                                                       "summary": "Ready for human review", "evidence": EVIDENCE}, "worker")
        self.assertEqual(submitted["status"], "review")
        self.assert_error(409, "complete_ticket", {"id": ticket["id"], "expected_revision": submitted["revision"],
                                                   "verification": "Checked", "accepted_criteria": ["Feature works", "Failure path checked"]}, "worker")
        self.assert_error(409, "complete_ticket", {"id": ticket["id"], "expected_revision": submitted["revision"],
                                                   "verification": "Checked", "accepted_criteria": ["Feature works"]})
        done = self.store.action("complete_ticket", {"id": ticket["id"], "expected_revision": submitted["revision"],
                                                     "verification": "Both behaviors observed in review",
                                                     "accepted_criteria": ["Feature works", "Failure path checked"]})
        self.assertEqual(done["status"], "done")
        self.assert_error(409, "update_ticket", {"id": ticket["id"], "expected_revision": done["revision"],
                                                 "description": "changed"})
        self.assert_error(400, "transition", {"id": ticket["id"], "expected_revision": done["revision"],
                                               "status": "queued"})
        reopened = self.store.action("transition", {"id": ticket["id"], "expected_revision": done["revision"],
                                                   "status": "queued", "reason": "Additional requirement"})
        self.assertIsNone(reopened["assignee"])

    def test_hierarchy_readiness_and_completion(self):
        parent = self.create("Parent", type="objective", acceptance=["All child work accepted"])
        child = self.create("Child", parent_id=parent["id"], acceptance=["Child accepted"])
        self.assert_error(409, "claim_ticket", {"id": parent["id"], "expected_revision": 1, "assignee": "worker"})
        c = self.store.action("claim_ticket", {"id": child["id"], "expected_revision": 1, "assignee": "worker"})
        c = self.store.action("submit_ticket", {"id": child["id"], "expected_revision": c["revision"],
                                                "summary": "Done", "evidence": EVIDENCE})
        self.store.action("complete_ticket", {"id": child["id"], "expected_revision": c["revision"],
                                             "verification": "Reviewed", "accepted_criteria": ["Child accepted"]})
        self.assertTrue(self.store.context(parent["id"])["ticket"]["ready"])

    def test_help_completion_keeps_parent_explicitly_blocked_until_resume(self):
        parent = self.create("Parent", acceptance=["Result reviewed"])
        parent = self.store.action("claim_ticket", {"id": parent["id"], "expected_revision": 1, "assignee": "worker"})
        result = self.store.action("request_help", {"id": parent["id"], "expected_revision": parent["revision"],
                                                    "title": "Clarify API", "description": "Need input shape"}, "worker")
        child = result["child"]
        self.assertEqual(child["type"], "help")
        self.assertEqual(child["parent_id"], parent["id"])
        self.assertNotIn(parent["id"], child["depends_on"])
        self.assertIn(child["id"], result["parent"]["depends_on"])
        child = self.store.action("claim_ticket", {"id": child["id"], "expected_revision": 1, "assignee": "helper"})
        child = self.store.action("submit_ticket", {"id": child["id"], "expected_revision": child["revision"],
                                                    "summary": "Schema clarified", "evidence": EVIDENCE})
        self.store.action("complete_ticket", {"id": child["id"], "expected_revision": child["revision"],
                                             "verification": "Explanation reviewed",
                                             "accepted_criteria": ["La ayuda solicitada está documentada y revisada."]})
        blocked = self.store.context(parent["id"])["ticket"]
        self.assertEqual(blocked["status"], "blocked")
        self.assertFalse(blocked["ready"])
        resumed = self.store.action("transition", {"id": parent["id"], "expected_revision": blocked["revision"],
                                                 "status": "queued"}, "worker")
        self.assertTrue(resumed["ready"])

    def test_unassigned_blocked_ticket_requires_human_resume(self):
        parent = self.create("Waiting for decision", acceptance=["Reviewed"])
        blocked = self.store.action("request_help", {"id": parent["id"], "expected_revision": 1,
                                                     "title": "Advice", "description": "Clarify scope"})["parent"]
        self.assert_error(409, "transition", {"id": parent["id"], "expected_revision": blocked["revision"],
                                              "status": "queued"}, "agent:worker")

    def test_split_preserves_parent_history_and_blocks_until_children_finish(self):
        parent = self.create("Large task", acceptance=["Integrated result works"],
                             priority="urgent", profile_id="sol")
        result = self.store.action("split_ticket", {"id": parent["id"], "expected_revision": 1,
                                                   "children": [{"title": "Part A", "acceptance": ["A checked"]},
                                                                {"title": "Part B", "acceptance": ["B checked"]}]})
        self.assertEqual(len(result["children"]), 2)
        self.assertTrue(all(child["priority"] == "urgent" and child["profile_id"] == "sol"
                            for child in result["children"]))
        self.assertEqual(result["parent"]["status"], "blocked")
        self.assertEqual(self.store.context(parent["id"])["events"][0]["action"], "split_ticket")
        self.assertFalse(result["parent"]["ready"])
        self.assert_error(400, "split_ticket", {"id": parent["id"], "expected_revision": 2, "children": []})

    def test_profile_validation_and_locked_coordinator(self):
        self.assert_error(409, "update_profile", {"id": "astra", "model": "cheaper-model"})
        profile = self.store.action("create_profile", {"name": "Local", "role": "QA", "model": "offline"})
        self.assertEqual(profile["provider"], "")
        updated = self.store.action("update_profile", {"id": profile["id"], "capabilities": ["qa"]})
        self.assertEqual(updated["capabilities"], ["qa"])

    def test_demo_is_explicit_idempotent_and_does_not_mix_user_tickets(self):
        self.assertEqual(self.store.state()["tickets"], [])
        self.assertTrue(self.store.seed_demo())
        self.assertFalse(self.store.seed_demo())
        tickets = self.store.state()["tickets"]
        self.assertGreaterEqual(len(tickets), 8)
        self.assertTrue(all(t["title"] for t in tickets))
        self.assertTrue(any(t["evidence"] for t in tickets))
        self.assertTrue(any(t["type"] == "help" for t in tickets))
        self.assertTrue(any(t["status"] == "blocked" for t in tickets))
        other = Store(Path(self.directory.name) / "other.db")
        other.action("create_ticket", {"title": "User work"})
        with self.assertRaises(DomainError) as caught:
            other.seed_demo()
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(other.state()["stats"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
