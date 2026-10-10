"""Acceptance uses the exact immediate context reviewed, without graph-wide CAS."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest

from agentrelay.snapshots import create_snapshot
from agentrelay.source_checks import check_sources
from agentrelay.store import DomainError, Store


CRITERION = ["Reviewed deliverable"]
EVIDENCE = [{"kind": "test", "label": "Fixture", "uri": "fixture://acceptance"}]


class AcceptanceContextTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="agentrelay-acceptance-context-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.path = self.directory / "tickets.sqlite"
        self.store = Store(self.path)

    def create(self, title, **fields):
        return self.store.action("create_ticket", {"title": title,
            "acceptance": CRITERION, **fields})

    def review(self, ticket):
        claimed = self.store.action("claim_ticket", {"id": ticket["id"],
            "expected_revision": ticket["revision"], "assignee": "owner"}, "agent:owner")
        return self.store.action("submit_ticket", {"id": ticket["id"],
            "expected_revision": claimed["revision"], "summary": "Ready for review",
            "evidence": EVIDENCE}, "agent:owner")

    def complete(self, ticket, token=None, *, store=None):
        store = store or self.store
        if token is None:
            token = store.context(ticket["id"])["acceptance_context"]["token"]
        return store.action("complete_ticket", {"id": ticket["id"],
            "expected_revision": ticket["revision"],
            "expected_acceptance_context_token": token,
            "verification": "Reviewed current context", "accepted_criteria": CRITERION},
            "agent:reviewer")

    def conflict(self, ticket, token, *, status=409):
        before = self.store.context(ticket["id"])
        with self.assertRaises(DomainError) as caught:
            self.complete(ticket, token)
        self.assertEqual(caught.exception.status, status)
        self.assertEqual(self.store.context(ticket["id"]), before)

    def test_context_shape_success_audit_and_no_automatic_acceptance(self):
        ticket = self.create("Parent")
        self.assertIsNone(self.store.context(ticket["id"])["acceptance_context"])
        ticket = self.review(ticket)
        info = self.store.context(ticket["id"])["acceptance_context"]
        self.assertEqual(info["schema_version"], 1)
        self.assertEqual(set(info), {"schema_version", "token", "children_count",
                                      "dependencies_count", "source_checks_count"})
        self.assertEqual(len(info["token"]), 71)
        self.assertEqual((info["children_count"], info["dependencies_count"],
                          info["source_checks_count"]), (0, 0, 0))
        self.assertEqual(self.store.context(ticket["id"])["ticket"]["status"], "review")
        done = self.complete(ticket, info["token"])
        self.assertEqual(done["status"], "done")
        self.assertIsNone(self.store.context(ticket["id"])["acceptance_context"])
        event = self.store.ticket_events(ticket["id"])["events"][0]
        self.assertEqual(event["details"]["acceptance_context_schema_version"], 1)
        self.assertEqual(event["details"]["expected_acceptance_context_token"], info["token"])
        self.conflict(ticket, info["token"])

    def test_added_and_completed_child_invalidates_old_review(self):
        parent = self.review(self.create("Parent"))
        old = self.store.context(parent["id"])["acceptance_context"]
        child = self.create("New child", parent_id=parent["id"])
        child = self.review(child)
        self.complete(child)
        current = self.store.context(parent["id"])
        self.assertEqual(current["ticket"]["revision"], parent["revision"])
        self.assertEqual(current["ticket"]["blockers"], [])
        self.assertEqual(current["acceptance_context"]["children_count"], 1)
        self.assertNotEqual(current["acceptance_context"]["token"], old["token"])
        self.conflict(parent, old["token"])
        self.complete(parent, current["acceptance_context"]["token"])

    def test_transient_child_then_detach_restores_same_immediate_context(self):
        parent = self.review(self.create("Parent"))
        original = self.store.context(parent["id"])["acceptance_context"]
        child = self.create("Transient child", parent_id=parent["id"])
        child = self.store.action("transition", {"id": child["id"],
            "expected_revision": child["revision"], "status": "cancelled"})
        while_attached = self.store.context(parent["id"])["acceptance_context"]
        self.assertNotEqual(while_attached["token"], original["token"])
        self.store.action("update_ticket", {"id": child["id"],
            "expected_revision": child["revision"], "parent_id": None})
        restored = self.store.context(parent["id"])
        self.assertEqual(restored["ticket"]["revision"], parent["revision"])
        self.assertEqual(restored["children"], [])
        self.assertEqual(restored["acceptance_context"], original)
        self.assertEqual(self.complete(parent, original["token"])["status"], "done")

    def test_detach_and_move_child_change_token_even_if_cancelled(self):
        parent = self.create("Parent")
        child = self.create("Child", parent_id=parent["id"])
        child = self.store.action("transition", {"id": child["id"],
            "expected_revision": child["revision"], "status": "cancelled"})
        parent = self.review(parent)
        old = self.store.context(parent["id"])["acceptance_context"]["token"]
        child = self.store.action("update_ticket", {"id": child["id"],
            "expected_revision": child["revision"], "parent_id": None})
        detached = self.store.context(parent["id"])["acceptance_context"]["token"]
        self.assertNotEqual(detached, old)
        self.conflict(parent, old)
        other = self.create("Other parent")
        child = self.store.action("update_ticket", {"id": child["id"],
            "expected_revision": child["revision"], "parent_id": parent["id"]})
        restored = self.store.context(parent["id"])["acceptance_context"]["token"]
        self.assertNotEqual(restored, detached)
        child = self.store.action("update_ticket", {"id": child["id"],
            "expected_revision": child["revision"], "parent_id": other["id"]})
        self.assertNotEqual(self.store.context(parent["id"])["acceptance_context"]["token"], restored)
        self.conflict(parent, restored)

    def test_child_reopened_and_reaccepted_changes_revision_in_token(self):
        parent = self.create("Parent")
        child = self.create("Child", parent_id=parent["id"])
        child = self.review(child)
        child = self.complete(child)
        parent = self.review(parent)
        old = self.store.context(parent["id"])["acceptance_context"]["token"]
        child = self.store.action("transition", {"id": child["id"],
            "expected_revision": child["revision"], "status": "queued",
            "reason": "Revise child evidence"})
        child = self.review(child)
        child = self.complete(child)
        self.assertEqual(child["status"], "done")
        self.assertEqual(self.store.context(parent["id"])["ticket"]["blockers"], [])
        self.conflict(parent, old)

    def test_dependency_reopened_and_reaccepted_changes_token(self):
        dependency = self.create("Dependency")
        dependency = self.review(dependency)
        dependency = self.complete(dependency)
        parent = self.review(self.create("Parent", depends_on=[dependency["id"]]))
        context = self.store.context(parent["id"])
        self.assertEqual(context["acceptance_context"]["dependencies_count"], 1)
        old = context["acceptance_context"]["token"]
        dependency = self.store.action("transition", {"id": dependency["id"],
            "expected_revision": dependency["revision"], "status": "queued",
            "reason": "Recheck dependency"})
        dependency = self.review(dependency)
        self.complete(dependency)
        self.conflict(parent, old)

    def test_comments_and_event_pagination_do_not_change_token(self):
        parent = self.review(self.create("Parent"))
        old = self.store.context(parent["id"])["acceptance_context"]["token"]
        self.store.action("add_comment", {"id": parent["id"], "body": "Historical note"})
        self.store.ticket_events(parent["id"], limit=1)
        self.assertEqual(self.store.context(parent["id"], event_limit=1)
                         ["acceptance_context"]["token"], old)
        self.complete(parent, old)

    def test_direct_ticket_change_still_uses_revision_cas(self):
        parent = self.review(self.create("Parent"))
        old = self.store.context(parent["id"])["acceptance_context"]["token"]
        updated = self.store.action("update_ticket", {"id": parent["id"],
            "expected_revision": parent["revision"], "checkpoint": "New review note"},
            "agent:owner")
        self.assertNotEqual(self.store.context(parent["id"])["acceptance_context"]["token"], old)
        self.conflict(parent, old)
        self.complete(updated)

    def test_source_check_insert_replay_and_fourth_receipt(self):
        root = self.directory / "inputs"
        root.mkdir()
        (root / "file.txt").write_text("Entrada ñ\n", encoding="utf-8")
        snapshot = self.directory / "snapshot"
        manifest = create_snapshot(root, ["file.txt"], snapshot)
        parent = self.review(self.create("Parent"))
        prior = self.store.context(parent["id"])["acceptance_context"]["token"]
        args = {"ticket_id": parent["id"], "expected_revision": parent["revision"],
                "snapshot": snapshot, "expected_snapshot_id": manifest["snapshot_id"],
                "root": root, "actor": "agent:checker"}
        previous = prior
        for index in range(1, 5):
            receipt = check_sources(self.store, request_id=f"check-{index}", **args)
            context = self.store.context(parent["id"])
            current = context["acceptance_context"]
            self.assertEqual(current["source_checks_count"], index)
            self.assertEqual(context["source_checks_page"]["count"], min(index, 3))
            self.assertNotEqual(current["token"], previous)
            self.assertEqual(check_sources(self.store, request_id=f"check-{index}", **args), receipt)
            self.assertEqual(self.store.context(parent["id"])["acceptance_context"]["token"],
                             current["token"])
            previous = current["token"]
        self.conflict(parent, prior)

    def test_grandchild_state_is_outside_immediate_token(self):
        parent = self.create("Parent")
        child = self.create("Child", parent_id=parent["id"])
        grandchild = self.create("Grandchild", parent_id=child["id"])
        grandchild = self.review(grandchild)
        grandchild = self.complete(grandchild)
        child = self.review(child)
        self.complete(child)
        parent = self.review(parent)
        old = self.store.context(parent["id"])["acceptance_context"]["token"]
        self.store.action("transition", {"id": grandchild["id"],
            "expected_revision": grandchild["revision"], "status": "queued",
            "reason": "New grandchild work"})
        self.assertEqual(self.store.context(parent["id"])["acceptance_context"]["token"], old)

    def test_invalid_and_stale_tokens_leave_no_event(self):
        parent = self.review(self.create("Parent"))
        token = self.store.context(parent["id"])["acceptance_context"]["token"]
        base = {"id": parent["id"], "expected_revision": parent["revision"],
                "verification": "Reviewed", "accepted_criteria": CRITERION}
        before = self.store.context(parent["id"])
        for invalid in (None, "", "sha256:" + "A" * 64, "sha256:" + "g" * 64,
                        "sha256:" + "0" * 63, 42, True):
            with self.subTest(token=invalid):
                data = dict(base)
                if invalid is not None:
                    data["expected_acceptance_context_token"] = invalid
                with self.assertRaises(DomainError) as caught:
                    self.store.action("complete_ticket", data, "agent:reviewer")
                self.assertEqual(caught.exception.status, 400)
                self.assertEqual(self.store.context(parent["id"]), before)
        self.conflict(parent, "sha256:" + "0" * 64)
        self.assertEqual(self.store.context(parent["id"])["acceptance_context"]["token"], token)

    def test_backup_preserves_token_and_completion_event(self):
        parent = self.review(self.create("Parent"))
        token = self.store.context(parent["id"])["acceptance_context"]["token"]
        copy_path = self.directory / "backup.sqlite"
        self.store.backup(copy_path)
        copy = Store(copy_path)
        self.assertEqual(copy.context(parent["id"])["acceptance_context"]["token"], token)
        self.complete(parent, token, store=copy)
        event = Store(copy_path).ticket_events(parent["id"])["events"][0]
        self.assertEqual(event["details"]["expected_acceptance_context_token"], token)

    def test_competing_completions_yield_one_acceptance(self):
        parent = self.review(self.create("Parent"))
        token = self.store.context(parent["id"])["acceptance_context"]["token"]
        independent_stores = [Store(self.path), Store(self.path)]

        def attempt(store):
            try:
                return self.complete(parent, token, store=store)["status"]
            except DomainError as exc:
                return exc.status

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(attempt, independent_stores))
        self.assertCountEqual(outcomes, ["done", 409])
        events = self.store.ticket_events(parent["id"])["events"]
        self.assertEqual(sum(event["action"] == "complete_ticket" for event in events), 1)

    def test_many_immediate_relations_have_fixed_size_deterministic_token(self):
        parent = self.review(self.create("Parent"))
        for index in range(120):
            self.create(f"Child {index:03d}", parent_id=parent["id"])
        first = self.store.context(parent["id"])["acceptance_context"]
        second = Store(self.path).context(parent["id"])["acceptance_context"]
        self.assertEqual(first, second)
        self.assertEqual(first["children_count"], 120)
        self.assertEqual(len(first["token"]), 71)


if __name__ == "__main__":
    unittest.main()
