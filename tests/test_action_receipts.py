"""Keyed ticket actions use one durable receipt in the same SQLite transaction."""

from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from agentrelay.snapshots import create_snapshot
from agentrelay.source_checks import check_sources
from agentrelay.store import (DomainError, MAX_ACTION_INTENT_BYTES,
                              MAX_ACTION_RESULT_BYTES, Store,
                              validate_ticket_action_request)


class ActionReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-action-receipts-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.path = self.directory / "tickets.sqlite"
        self.store = Store(self.path)

    def keyed(self, key, action, data, *, actor="agent:writer", store=None):
        return (store or self.store).action("apply_ticket_action",
            {"request_id": key, "action": action, "data": data}, actor)

    def ticket(self, title="Parent", **extra):
        return self.store.action("create_ticket", {"title": title,
            "acceptance": ["Reviewed outcome"], **extra})

    def events(self, action=None):
        with self.store._connection() as db:
            where = " WHERE action=?" if action else ""
            return list(db.execute("SELECT id,ticket_id,action FROM events" + where,
                                   (action,) if action else ()))

    def receipts(self):
        with self.store._connection() as db:
            return list(db.execute("SELECT request_id FROM action_requests ORDER BY request_id"))

    def assert_status(self, status, request, actor="agent:writer"):
        with self.assertRaises(DomainError) as caught:
            self.store.action("apply_ticket_action", request, actor)
        self.assertEqual(caught.exception.status, status)

    def test_validator_is_pure_canonical_bounded_and_rejects_invalid_inputs(self):
        first = {"request_id": "key 1", "action": "create_ticket",
                 "data": {"title": "Niño", "acceptance": ["Criterio"]}}
        second = {"data": {"acceptance": ["Criterio"], "title": "Niño"},
                  "action": "create_ticket", "request_id": "key 1"}
        normalized = validate_ticket_action_request(first)
        self.assertEqual(normalized["intent_json"],
                         validate_ticket_action_request(second)["intent_json"])
        self.assertEqual(normalized["request_id"], "key 1")
        first["data"]["title"] = "Changed after validation"
        self.assertEqual(normalized["data"]["title"], "Niño")
        invalid = [
            {}, {**first, "extra": True}, {**first, "request_id": True},
            {**first, "request_id": " key"}, {**first, "request_id": "k" * 129},
            {**first, "request_id": "\ud800"},
            {**first, "action": "check_sources"}, {**first, "action": "start_run"},
            {**first, "data": []}, {**first, "data": {"actor": "agent:other"}},
            {**first, "data": {"request_id": "inner"}},
            {**first, "data": {"title": float("nan")}},
            {**first, "data": {"title": "\ud800"}},
            {**first, "data": {"title": ("tuple",)}},
            {**first, "data": {1: "nonstring key"}},
        ]
        nested = []
        for _ in range(1200):
            nested = [nested]
        invalid.append({**first, "data": {"title": nested}})
        for index, request in enumerate(invalid):
            with self.subTest(invalid_case=index):
                with self.assertRaises(DomainError) as caught:
                    validate_ticket_action_request(request)
                self.assertEqual(caught.exception.status, 400)
        too_large = {**first, "data": {"title": "x" * MAX_ACTION_INTENT_BYTES}}
        with self.assertRaises(DomainError) as caught:
            validate_ticket_action_request(too_large)
        self.assertEqual(caught.exception.status, 413)

    def test_child_and_comment_exact_replay_no_extra_events_or_sequence(self):
        parent = self.ticket()
        child_data = {"title": "One intended child", "parent_id": parent["id"]}
        first = self.keyed("child-once", "create_ticket", child_data)
        comment_data = {"id": parent["id"], "body": "One intended comment"}
        commented = self.keyed("comment-once", "add_comment", comment_data)
        before_events = len(self.events())
        before_children = len(self.store.context(parent["id"])["children"])
        replay_child = self.keyed("child-once", "create_ticket", copy.deepcopy(child_data))
        replay_comment = self.keyed("comment-once", "add_comment", dict(comment_data))
        self.assertEqual(set(first), {"request_id", "action", "actor", "committed_at", "replayed", "result"})
        self.assertFalse(first["replayed"])
        self.assertTrue(replay_child["replayed"])
        self.assertEqual(replay_child["result"], first["result"])
        self.assertEqual(replay_child["committed_at"], first["committed_at"])
        self.assertEqual(replay_comment["result"], commented["result"])
        self.assertEqual(len(self.events()), before_events)
        self.assertEqual(len(self.store.context(parent["id"])["children"]), before_children)
        self.assertEqual(len(self.events("add_comment")), 1)
        next_ticket = self.ticket("Following ID")
        self.assertEqual(int(next_ticket["id"].split("-")[1]),
                         int(first["result"]["id"].split("-")[1]) + 1)

    def test_depth_boundary_cycles_and_shared_container_expansion_are_bounded(self):
        def request(value):
            return {"request_id": "bounded", "action": "create_ticket", "data": {"title": value}}
        value = []
        for _ in range(62):
            value = [value]
        # data is level 1; the deepest of these 63 lists is level 64.
        self.assertEqual(validate_ticket_action_request(request(value))["data"]["title"], value)
        with self.assertRaises(DomainError):
            validate_ticket_action_request(request([value]))
        cyclic = []
        cyclic.append(cyclic)
        with self.assertRaises(DomainError):
            validate_ticket_action_request(request(cyclic))
        shared = [0]
        for _ in range(30):
            shared = [shared, shared]
        with self.assertRaisesRegex(DomainError, "node budget"):
            validate_ticket_action_request(request(shared))
        self.assertEqual(self.receipts(), [])
        self.assertEqual(self.events(), [])

    def test_keyed_claim_requires_declarations_and_preserves_astra_lock(self):
        normal = self.ticket("Unknown host permitted", profile_id="sol")
        astra = self.ticket("Known coordinator required", profile_id="astra")
        for ticket in (normal, astra):
            base = {"id": ticket["id"], "expected_revision": 1, "assignee": "agent:writer"}
            for invalid in ({}, {"actual_model": None, "actual_effort": None},
                            {"actual_model": "", "actual_effort": " "}):
                with self.subTest(ticket=ticket["id"], invalid=invalid):
                    self.assert_status(400, {"request_id": "invalid-claim", "action": "claim_ticket",
                                            "data": {**base, **invalid}})
            self.assertEqual(self.store.context(ticket["id"])["ticket"]["status"], "queued")
        unknown = {"actual_model": "unknown", "actual_effort": "unknown"}
        self.keyed("normal-claim", "claim_ticket", {"id": normal["id"], "expected_revision": 1,
                                                     "assignee": "agent:writer", **unknown})
        self.assert_status(409, {"request_id": "unknown-astra", "action": "claim_ticket", "data": {
            "id": astra["id"], "expected_revision": 1, "assignee": "agent:writer", **unknown}})
        declared = self.keyed("known-astra", "claim_ticket", {
            "id": astra["id"], "expected_revision": 1, "assignee": "agent:writer",
            "actual_model": "gpt-6-astra", "actual_effort": "high"})
        self.assertEqual(declared["result"]["status"], "in_progress")
        self.assertEqual(len(self.events("claim_ticket")), 2)

    def test_historical_result_reopen_backup_and_export_scope(self):
        first = self.keyed("historical", "create_ticket", {"title": "Before"})
        ticket = first["result"]
        self.store.action("update_ticket", {"id": ticket["id"],
            "expected_revision": ticket["revision"], "title": "After"})
        reopened = Store(self.path)
        replay = self.keyed("historical", "create_ticket", {"title": "Before"}, store=reopened)
        self.assertEqual(replay["result"]["title"], "Before")
        self.assertEqual(reopened.context(ticket["id"])["ticket"]["title"], "After")
        backup = self.directory / "copy.sqlite"
        reopened.backup(backup)
        restored = Store(backup)
        self.assertEqual(self.keyed("historical", "create_ticket", {"title": "Before"},
                                    store=restored)["result"], first["result"])
        exported = reopened.export()
        self.assertNotIn("action_requests", exported)
        self.assertNotIn("historical", json.dumps(exported))

    def test_conflicting_reuse_and_failed_action_leave_receipt_and_events_unchanged(self):
        original = self.keyed("shared", "create_ticket", {"title": "Original"})
        before = (len(self.events()), len(self.receipts()))
        self.assert_status(409, {"request_id": "shared", "action": "create_ticket",
                                 "data": {"title": "Changed"}})
        self.assert_status(409, {"request_id": "shared", "action": "add_comment",
                                 "data": {"id": original["result"]["id"], "body": "Comment"}})
        self.assert_status(409, {"request_id": "shared", "action": "create_ticket",
                                 "data": {"title": "Original"}}, actor="agent:other")
        self.assertEqual((len(self.events()), len(self.receipts())), before)
        self.assertEqual(self.keyed("shared", "create_ticket", {"title": "Original"})["result"],
                         original["result"])
        self.assert_status(404, {"request_id": "invalid", "action": "create_ticket",
                                 "data": {"title": "Bad", "profile_id": "missing"}})
        self.assertEqual((len(self.events()), len(self.receipts())), before)

    def test_concurrent_stores_same_key_one_write_and_distinct_keys_two_writes(self):
        gate = threading.Barrier(2)
        def call(key):
            independent = Store(self.path)
            gate.wait(timeout=5)
            return self.keyed(key, "create_ticket", {"title": "Concurrent"}, store=independent)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = [future.result(timeout=10) for future in
                             (pool.submit(call, "parallel"), pool.submit(call, "parallel"))]
        self.assertEqual(first["result"], second["result"])
        self.assertEqual({first["replayed"], second["replayed"]}, {False, True})
        self.assertEqual(len(self.events("create_ticket")), 1)
        self.keyed("other-1", "create_ticket", {"title": "Concurrent"})
        self.keyed("other-2", "create_ticket", {"title": "Concurrent"})
        self.assertEqual(len(self.events("create_ticket")), 3)

    def test_result_limit_and_serialization_failures_roll_back_inner_action(self):
        original = self.store._dispatch_action
        for oversized in ({"padding": "x" * MAX_ACTION_RESULT_BYTES},
                          {"bad": object()}):
            with self.subTest(oversized=list(oversized)):
                before = (len(self.events()), len(self.receipts()), len(self.store.state()["tickets"]))
                def dispatch(db, action, data, actor):
                    original(db, action, data, actor)
                    return oversized
                with patch.object(self.store, "_dispatch_action", side_effect=dispatch):
                    with self.assertRaises(DomainError):
                        self.keyed("rollback-" + str(len(self.events())), "create_ticket",
                                   {"title": "Must rollback"})
                self.assertEqual((len(self.events()), len(self.receipts()),
                                  len(self.store.state()["tickets"])), before)
        first = self.keyed("after-rollback", "create_ticket", {"title": "Valid"})
        self.assertEqual(first["result"]["id"], "AR-0001")

    def test_help_split_and_complete_replay_do_not_repeat_side_effects(self):
        parent = self.ticket("Split parent")
        split = self.keyed("split", "split_ticket", {"id": parent["id"],
            "expected_revision": parent["revision"],
            "children": [{"title": "Part", "acceptance": ["Checked"]}]})
        self.assertEqual(len(split["result"]["children"]), 1)
        self.assertTrue(self.keyed("split", "split_ticket", {"id": parent["id"],
            "expected_revision": parent["revision"],
            "children": [{"title": "Part", "acceptance": ["Checked"]}]})["replayed"])
        self.assertEqual(len(self.store.context(parent["id"])["children"]), 1)
        helper_parent = self.ticket("Help parent")
        help_data = {"id": helper_parent["id"], "expected_revision": 1,
                     "title": "Need review", "description": "Please inspect"}
        helped = self.keyed("help", "request_help", help_data)
        self.assertEqual(self.keyed("help", "request_help", help_data)["result"], helped["result"])
        self.assertEqual(len(self.store.context(helper_parent["id"])["children"]), 1)

        ticket = self.ticket("Acceptance")
        claimed = self.store.action("claim_ticket", {"id": ticket["id"],
            "expected_revision": 1, "assignee": "owner"}, "agent:owner")
        submitted = self.store.action("submit_ticket", {"id": ticket["id"],
            "expected_revision": claimed["revision"], "summary": "Ready",
            "evidence": [{"kind": "test", "label": "Fixture", "uri": "fixture://result"}]},
            "agent:owner")
        complete_data = {"id": ticket["id"], "expected_revision": submitted["revision"],
            "expected_acceptance_context_token": self.store.context(ticket["id"])["acceptance_context"]["token"],
            "verification": "Independently reviewed", "accepted_criteria": ["Reviewed outcome"]}
        completed = self.keyed("completion", "complete_ticket", complete_data,
                               actor="agent:reviewer")
        before_events = len(self.events("complete_ticket"))
        self.assertEqual(completed["result"]["status"], "done")
        replay = self.keyed("completion", "complete_ticket", complete_data,
                            actor="agent:reviewer")
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["result"], completed["result"])
        self.assertEqual(len(self.events("complete_ticket")), before_events)
        reopened = self.store.action("transition", {"id": ticket["id"],
            "expected_revision": completed["result"]["revision"], "status": "queued",
            "reason": "New authorized work after historical acceptance"})
        after_reopen = len(self.events())
        replay_after_reopen = self.keyed("completion", "complete_ticket", complete_data,
                                        actor="agent:reviewer")
        self.assertEqual(replay_after_reopen["result"], completed["result"])
        self.assertEqual(self.store.context(ticket["id"])["ticket"], reopened)
        self.assertEqual(len(self.events()), after_reopen)
        self.assert_status(409, {"request_id": "completion", "action": "complete_ticket",
                                 "data": {**complete_data,
                                          "expected_acceptance_context_token": "sha256:" + "0" * 64}},
                           actor="agent:reviewer")
        self.assert_status(409, {"request_id": "new-completion", "action": "complete_ticket",
                                 "data": complete_data}, actor="agent:reviewer")

    def test_cross_namespace_guards_are_symmetric_and_preserve_legacy_replays(self):
        ticket = self.ticket()
        plan_data = {"request_id": "plan-first", "tickets": [{"key": "p", "title": "Planned"}]}
        plan = self.store.action("create_plan", plan_data)
        self.assert_status(409, {"request_id": "plan-first", "action": "add_comment",
                                 "data": {"id": ticket["id"], "body": "No"}})
        self.assertEqual(self.store.action("create_plan", plan_data), plan)
        claim_data = {"request_id": "claim-first", "candidates": [{"ticket_id": ticket["id"],
                      "expected_revision": 1}], "assignee": "agent:writer",
                      "actual_model": "unknown", "actual_effort": "unknown"}
        claim = self.store.action("claim_next_ticket", claim_data, "agent:writer")
        self.assert_status(409, {"request_id": "claim-first", "action": "add_comment",
                                 "data": {"id": ticket["id"], "body": "No"}})
        self.assertEqual(self.store.action("claim_next_ticket", claim_data, "agent:writer"), claim)

        root = self.directory / "project"
        root.mkdir()
        (root / "state.txt").write_text("State\n", encoding="utf-8")
        snapshot = self.directory / "snapshot"
        manifest = create_snapshot(root, ["state.txt"], snapshot)
        kwargs = {"ticket_id": ticket["id"], "expected_revision": claim["ticket"]["revision"],
                  "snapshot": snapshot, "expected_snapshot_id": manifest["snapshot_id"],
                  "root": root, "actor": "agent:checker"}
        source = check_sources(self.store, request_id="source-first", **kwargs)
        self.assert_status(409, {"request_id": "source-first", "action": "add_comment",
                                 "data": {"id": ticket["id"], "body": "No"}})
        self.assertEqual(check_sources(self.store, request_id="source-first", **kwargs), source)

        for key in ("action-plan", "action-claim", "action-source"):
            self.keyed(key, "add_comment", {"id": ticket["id"], "body": key})
        with self.assertRaises(DomainError) as caught:
            self.store.action("create_plan", {"request_id": "action-plan",
                "tickets": [{"key": "x", "title": "No"}]})
        self.assertEqual(caught.exception.status, 409)
        with self.assertRaises(DomainError) as caught:
            self.store.action("claim_next_ticket", {**claim_data, "request_id": "action-claim"},
                              "agent:writer")
        self.assertEqual(caught.exception.status, 409)
        with patch("agentrelay.source_checks.compare_snapshot", side_effect=AssertionError("compared")):
            with self.assertRaises(DomainError) as caught:
                check_sources(self.store, request_id="action-source", **kwargs)
        self.assertEqual(caught.exception.status, 409)

    def test_source_check_rechecks_namespace_after_external_comparison(self):
        ticket = self.ticket()
        root = self.directory / "project"
        root.mkdir()
        (root / "state.txt").write_text("State\n", encoding="utf-8")
        snapshot = self.directory / "snapshot"
        manifest = create_snapshot(root, ["state.txt"], snapshot)
        entered = threading.Event()
        release = threading.Event()
        from agentrelay import source_checks
        real_compare = source_checks.compare_snapshot
        def compare(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(timeout=5))
            return real_compare(*args, **kwargs)
        def run_check():
            return check_sources(Store(self.path), ticket_id=ticket["id"],
                expected_revision=1, snapshot=snapshot,
                expected_snapshot_id=manifest["snapshot_id"], root=root,
                request_id="raced", actor="agent:checker")
        with patch("agentrelay.source_checks.compare_snapshot", side_effect=compare):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(run_check)
                self.assertTrue(entered.wait(timeout=5))
                try:
                    self.keyed("raced", "add_comment", {"id": ticket["id"], "body": "Wins"})
                finally:
                    release.set()
                with self.assertRaises(DomainError) as caught:
                    future.result(timeout=10)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(len(self.events("add_comment")), 1)
        with self.store._connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM source_checks").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
