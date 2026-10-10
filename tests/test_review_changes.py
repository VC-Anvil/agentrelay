"""Independent review returns: state, audit and bounded context."""

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from agentrelay.store import DomainError, Store


EVIDENCE = [{"kind": "file", "label": "Local result", "uri": "local://result"}]
ACCEPTANCE = ["Observed behavior", "Failure path"]


class ReviewChangesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-review-changes-")
        self.path = Path(self.temp.name) / "tickets.sqlite"
        self.store = Store(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def create(self, **extra):
        return self.store.action("create_ticket", {
            "title": "Review this", "description": "Preserve this scope",
            "acceptance": ACCEPTANCE, "priority": "high", "profile_id": "sol", **extra,
        })

    def submitted(self, *, actor="agent:author", **extra):
        ticket = self.create(**extra)
        ticket = self.store.action("claim_ticket", {
            "id": ticket["id"], "expected_revision": ticket["revision"],
            "assignee": "human" if actor == "human" else "author",
            "actual_model": "unknown", "actual_effort": "unknown",
        }, actor)
        return self.store.action("submit_ticket", {
            "id": ticket["id"], "expected_revision": ticket["revision"],
            "summary": "Delivered draft", "evidence": EVIDENCE,
        }, actor)

    def return_changes(self, ticket, reason="Correct two claims", actor="agent:reviewer"):
        return self.store.action("request_changes", {
            "id": ticket["id"], "expected_revision": ticket["revision"], "reason": reason,
        }, actor)

    def assert_error(self, status, data, actor="agent:reviewer"):
        with self.assertRaises(DomainError) as caught:
            self.store.action("request_changes", data, actor)
        self.assertEqual(caught.exception.status, status)

    def test_independent_return_preserves_ticket_and_other_work(self):
        dependency = self.create(title="Dependency")
        dependency = self.store.action("claim_ticket", {
            "id": dependency["id"], "expected_revision": 1, "assignee": "dep"}, "agent:dep")
        dependency = self.store.action("submit_ticket", {
            "id": dependency["id"], "expected_revision": 2,
            "summary": "Dep delivered", "evidence": EVIDENCE}, "agent:dep")
        dependency = self.store.action("complete_ticket", {"expected_acceptance_context_token": self.store.context(dependency["id"])["acceptance_context"]["token"],
            "id": dependency["id"], "expected_revision": 3,
            "verification": "Checked", "accepted_criteria": ACCEPTANCE}, "agent:reviewer")
        delivered = self.submitted(depends_on=[dependency["id"]])
        dependency = self.store.action("transition", {
            "id": dependency["id"], "expected_revision": dependency["revision"],
            "status": "queued", "reason": "New requirement"})
        before = self.store.context(delivered["id"])["ticket"]
        other_before = self.store.context(dependency["id"])["ticket"]
        returned = self.return_changes(delivered, "  Correct two claims  ")
        self.assertEqual((returned["status"], returned["assignee"], returned["blocked_reason"]),
                         ("queued", None, ""))
        self.assertEqual(returned["revision"], before["revision"] + 1)
        for key in ("title", "description", "type", "priority", "parent_id", "profile_id",
                    "acceptance", "checkpoint", "evidence", "depends_on", "actual_model", "actual_effort"):
            self.assertEqual(returned[key], before[key], key)
        self.assertFalse(returned["ready"])
        self.assertEqual(returned["blockers"], [f"Dependency {dependency['id']} is queued"])
        self.assertEqual(self.store.context(dependency["id"])["ticket"], other_before)
        events = self.store.context(delivered["id"])["events"]
        self.assertEqual(events[0]["action"], "request_changes")
        self.assertEqual(events[0]["details"], {
            "reason": "Correct two claims", "previous_assignee": "author",
            "submitted_revision": before["revision"], "returned_revision": returned["revision"],
        })

    def test_self_review_aliases_and_human_identity(self):
        delivered = self.submitted()
        data = {"id": delivered["id"], "expected_revision": delivered["revision"], "reason": "Fix"}
        self.assert_error(409, data, "author")
        self.assert_error(409, data, "agent:author")
        self.assertEqual(self.store.context(delivered["id"])["ticket"]["revision"], delivered["revision"])
        self.assertEqual(self.return_changes(delivered, actor="human")["status"], "queued")
        human = self.submitted(actor="human")
        self.assert_error(409, {"id": human["id"], "expected_revision": human["revision"],
                                "reason": "Fix"}, "human")
        self.assertEqual(self.return_changes(human)["status"], "queued")

    def test_validation_lifecycle_and_stale_retry_are_side_effect_free(self):
        delivered = self.submitted()
        base = {"id": delivered["id"], "expected_revision": delivered["revision"],
                "reason": "Fix"}
        for invalid in ({**base, "extra": 1}, {k: v for k, v in base.items() if k != "reason"},
                        {**base, "reason": " "}, {**base, "reason": 4},
                        {**base, "reason": "x" * 4001},
                        {**base, "expected_revision": True},
                        {**base, "expected_revision": 0},
                        {**base, "id": None}, {**base, "id": []},
                        {**base, "id": ""}, {**base, "id": "  "}):
            with self.subTest(invalid=repr(invalid)[:80]):
                self.assert_error(400, invalid)
        self.assert_error(404, {**base, "id": "AR-9999"})
        self.assert_error(400, base, "x" * 129)
        self.assert_error(400, base, " ")
        self.assertEqual(self.store.context(delivered["id"])["ticket"]["revision"], delivered["revision"])
        before_events = self.store.ticket_events(delivered["id"])["total"]
        self.return_changes(delivered)
        self.assert_error(409, base)
        self.assertEqual(self.store.ticket_events(delivered["id"])["total"], before_events + 1)
        for status in ("backlog", "queued", "in_progress", "blocked", "done", "cancelled"):
            with self.subTest(status=status):
                ticket = self.create()
                if status in ("backlog", "blocked", "cancelled"):
                    ticket = self.store.action("transition", {"id": ticket["id"],
                        "expected_revision": ticket["revision"], "status": status,
                        "reason": "Blocked" if status == "blocked" else ""})
                elif status in ("in_progress", "done"):
                    ticket = self.store.action("claim_ticket", {
                        "id": ticket["id"], "expected_revision": ticket["revision"],
                        "assignee": "author"}, "agent:author")
                    if status == "done":
                        ticket = self.store.action("submit_ticket", {
                            "id": ticket["id"], "expected_revision": ticket["revision"],
                            "summary": "Delivered", "evidence": EVIDENCE}, "agent:author")
                        ticket = self.store.action("complete_ticket", {"expected_acceptance_context_token": self.store.context(ticket["id"])["acceptance_context"]["token"],
                            "id": ticket["id"], "expected_revision": ticket["revision"],
                            "verification": "Checked", "accepted_criteria": ACCEPTANCE}, "agent:reviewer")
                self.assert_error(409, {"id": ticket["id"], "expected_revision": ticket["revision"],
                                        "reason": "Fix"})
                self.assertEqual(self.store.context(ticket["id"])["ticket"]["revision"], ticket["revision"])

    def test_competing_reviewers_one_wins(self):
        delivered = self.submitted()
        barrier = Barrier(2)

        def review(actor):
            independent = Store(self.path)
            barrier.wait(timeout=5)
            try:
                result = independent.action("request_changes", {
                    "id": delivered["id"], "expected_revision": delivered["revision"],
                    "reason": actor}, actor)
                return result["revision"]
            except DomainError as exc:
                return exc.status

        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(review, ("agent:one", "agent:two")))
        self.assertCountEqual(values, [delivered["revision"] + 1, 409])
        self.assertEqual(sum(e["action"] == "request_changes" for e in
                             self.store.context(delivered["id"])["events"]), 1)

    def test_feedback_survives_bounded_events_and_tracks_only_later_events(self):
        self.assertIsNone(self.store.context(self.create()["id"], event_limit=1)["review_feedback"])
        delivered = self.submitted()
        returned = self.return_changes(delivered, "First correction")
        for n in range(25):
            self.store.action("add_comment", {"id": returned["id"], "body": f"Note {n}"})
        context = self.store.context(returned["id"], event_limit=1)
        feedback = context["review_feedback"]
        self.assertEqual(len(context["events"]), 1)
        self.assertEqual(feedback["reason"], "First correction")
        self.assertEqual(feedback["reviewer"], "agent:reviewer")
        self.assertEqual(feedback["previous_assignee"], "author")
        self.assertEqual((feedback["submitted_revision"], feedback["returned_revision"]),
                         (delivered["revision"], returned["revision"]))
        self.assertFalse(feedback["submission_after_request"])
        self.assertFalse(feedback["completion_after_request"])
        self.assertEqual(feedback["event_id"], next(
            e["id"] for e in self.store.context(returned["id"])["events"]
            if e["action"] == "request_changes"))
        self.assertIn("later submission is not acceptance", context["instructions"])
        claimed = self.store.action("claim_ticket", {
            "id": returned["id"], "expected_revision": returned["revision"],
            "assignee": "author"}, "agent:author")
        self.assertFalse(self.store.context(claimed["id"], event_limit=1)["review_feedback"]["submission_after_request"])
        resubmitted = self.store.action("submit_ticket", {
            "id": claimed["id"], "expected_revision": claimed["revision"],
            "summary": "Revised", "evidence": EVIDENCE}, "agent:author")
        self.assertTrue(self.store.context(resubmitted["id"], event_limit=1)["review_feedback"]["submission_after_request"])
        second = self.return_changes(resubmitted, "Second correction")
        new_feedback = self.store.context(second["id"], event_limit=1)["review_feedback"]
        self.assertEqual(new_feedback["reason"], "Second correction")
        self.assertFalse(new_feedback["submission_after_request"])
        self.assertFalse(new_feedback["completion_after_request"])
        claimed = self.store.action("claim_ticket", {
            "id": second["id"], "expected_revision": second["revision"],
            "assignee": "author"}, "agent:author")
        resubmitted = self.store.action("submit_ticket", {
            "id": claimed["id"], "expected_revision": claimed["revision"],
            "summary": "Revised again", "evidence": EVIDENCE}, "agent:author")
        completed = self.store.action("complete_ticket", {"expected_acceptance_context_token": self.store.context(resubmitted["id"])["acceptance_context"]["token"],
            "id": resubmitted["id"], "expected_revision": resubmitted["revision"],
            "verification": "Verified independently", "accepted_criteria": ACCEPTANCE}, "agent:reviewer")
        final_feedback = self.store.context(completed["id"], event_limit=1)["review_feedback"]
        self.assertTrue(final_feedback["submission_after_request"])
        self.assertTrue(final_feedback["completion_after_request"])
        self.assertEqual(self.store.context(completed["id"], event_limit=1)["events"][0]["action"],
                         "complete_ticket")

    def test_backup_preserves_feedback_and_no_implicit_reopen(self):
        delivered = self.submitted()
        returned = self.return_changes(delivered)
        backup_path = Path(self.temp.name) / "backup.sqlite"
        self.store.backup(backup_path)
        copied = Store(backup_path)
        self.assertEqual(copied.context(returned["id"], event_limit=1)["review_feedback"],
                         self.store.context(returned["id"], event_limit=1)["review_feedback"])
        self.assertEqual(copied.context(returned["id"])["ticket"]["status"], "queued")
        self.assertEqual(self.store.context(returned["id"])["ticket"]["status"], "queued")


if __name__ == "__main__":
    unittest.main()
