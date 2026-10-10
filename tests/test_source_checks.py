"""Source checks are historical observations, never automatic ticket decisions."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from agentrelay import freshness
from agentrelay.snapshots import create_snapshot
from agentrelay.source_checks import check_sources, get_source_check, list_source_checks
from agentrelay.store import DomainError, Store


class SourceCheckTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="agentrelay-source-check-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root = self.directory / "project"
        self.root.mkdir()
        (self.root / "state.txt").write_text("Música y revisión\n", encoding="utf-8")
        self.snapshot = self.directory / "snapshot"
        self.manifest = create_snapshot(self.root, ["state.txt"], self.snapshot)
        self.store = Store(self.directory / "work.sqlite")
        self.ticket = self.store.action("create_ticket", {"title": "Revisar fuentes",
            "acceptance": ["Informe revisado por otra persona."]})

    def kwargs(self, request_id="source-1", **changes):
        result = {"ticket_id": self.ticket["id"], "expected_revision": self.ticket["revision"],
                  "snapshot": self.snapshot, "expected_snapshot_id": self.manifest["snapshot_id"],
                  "root": self.root, "request_id": request_id, "actor": "agent:checker"}
        result.update(changes)
        return result

    def test_canonical_report_receipt_and_no_ticket_mutation(self):
        receipt = check_sources(self.store, **self.kwargs())
        self.assertEqual(set(receipt), {"schema_version", "check_id", "request_id", "ticket_id",
            "ticket_revision", "actor", "method", "snapshot_id", "report_sha256", "summary",
            "checked_at", "recorded_at"})
        self.assertEqual(receipt["summary"], {"total": 1, "unchanged": 1,
            "modified": 0, "missing": 0, "uncheckable": 0})
        self.assertEqual(receipt["method"], "local_compare_snapshot_v1")
        detail = get_source_check(self.store, receipt["check_id"])
        encoded = json.dumps(detail["report"], sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.assertEqual(hashlib.sha256(encoded).hexdigest(), receipt["report_sha256"])
        self.assertEqual(detail["report"]["root"], str(self.root.resolve()))
        self.assertEqual(self.store.context(self.ticket["id"])["ticket"]["revision"], 1)
        events = self.store.ticket_events(self.ticket["id"])["events"]
        self.assertEqual(events[0]["action"], "source_check_recorded")
        self.assertNotIn("report", events[0]["details"])
        self.assertNotIn("report_json", json.dumps(self.store.state()))
        self.assertNotIn("source_checks", self.store.export())

    def test_exact_replay_after_paths_disappear_and_revision_advances(self):
        args = self.kwargs()
        original = check_sources(self.store, **args)
        moved_snapshot = self.directory / "snapshot-moved"
        moved_root = self.directory / "project-moved"
        self.snapshot.rename(moved_snapshot)
        self.root.rename(moved_root)
        self.store.action("update_ticket", {"id": self.ticket["id"], "expected_revision": 1,
                                            "title": "Fuentes revisadas"})
        with patch("agentrelay.source_checks.compare_snapshot", side_effect=AssertionError("rechecked")):
            self.assertEqual(check_sources(self.store, **args), original)
            with self.assertRaises(DomainError) as conflict:
                check_sources(self.store, **self.kwargs(root=moved_root))
            self.assertEqual(conflict.exception.status, 409)
        self.assertEqual(list_source_checks(self.store, self.ticket["id"])["total"], 1)
        self.assertEqual(self.store.context(self.ticket["id"])["source_checks"][0]
                         ["ticket_revision_matches_now"], False)

    def test_snapshot_mismatch_precedes_current_root_inspection(self):
        with patch("agentrelay.freshness._prepare_current_root",
                   side_effect=AssertionError("root inspected")):
            with self.assertRaises(freshness.SnapshotError):
                freshness.compare_snapshot(self.snapshot, self.root,
                    expected_snapshot_id="sha256:" + "0" * 64)
        with self.assertRaises(freshness.SnapshotError):
            check_sources(self.store, **self.kwargs(expected_snapshot_id="sha256:" + "0" * 64))
        self.assertEqual(list_source_checks(self.store, self.ticket["id"])["total"], 0)

    def test_revision_change_during_comparison_rolls_back_record_and_event(self):
        report = freshness.compare_snapshot(self.snapshot, self.root)
        before = self.store.ticket_events(self.ticket["id"])["total"]

        def concurrent_edit(*args, **kwargs):
            self.store.action("update_ticket", {"id": self.ticket["id"],
                "expected_revision": 1, "title": "Nueva revisión"})
            return report

        with patch("agentrelay.source_checks.compare_snapshot", side_effect=concurrent_edit):
            with self.assertRaises(DomainError) as conflict:
                check_sources(self.store, **self.kwargs())
        self.assertEqual(conflict.exception.status, 409)
        self.assertEqual(list_source_checks(self.store, self.ticket["id"])["total"], 0)
        self.assertEqual(self.store.ticket_events(self.ticket["id"])["total"], before + 1)
        self.assertEqual(self.store.ticket_events(self.ticket["id"])["events"][0]["action"],
                         "update_ticket")

    def test_report_limit_rejects_without_mutation(self):
        report = freshness.compare_snapshot(self.snapshot, self.root)
        report["padding"] = "x" * 1_048_576
        before = self.store.ticket_events(self.ticket["id"])["total"]
        with patch("agentrelay.source_checks.compare_snapshot", return_value=report):
            with self.assertRaises(DomainError):
                check_sources(self.store, **self.kwargs())
        self.assertEqual(list_source_checks(self.store, self.ticket["id"])["total"], 0)
        self.assertEqual(self.store.ticket_events(self.ticket["id"])["total"], before)

    def test_namespace_collisions_both_directions(self):
        first = check_sources(self.store, **self.kwargs("shared-source"))
        events = self.store.ticket_events(self.ticket["id"])["total"]
        with self.assertRaises(DomainError) as plan_conflict:
            self.store.action("create_plan", {"request_id": "shared-source",
                "tickets": [{"key": "x", "title": "Should not exist"}]})
        self.assertEqual(plan_conflict.exception.status, 409)
        with self.assertRaises(DomainError) as claim_conflict:
            self.store.action("claim_next_ticket", {"request_id": "shared-source",
                "candidates": [{"ticket_id": self.ticket["id"], "expected_revision": 1}],
                "assignee": "agent:checker", "actual_model": "unknown",
                "actual_effort": "unknown"}, actor="agent:checker")
        self.assertEqual(claim_conflict.exception.status, 409)
        self.assertEqual(self.store.ticket_events(self.ticket["id"])["total"], events)
        self.assertEqual(check_sources(self.store, **self.kwargs("shared-source")), first)

        self.store.action("create_plan", {"request_id": "plan-id",
            "tickets": [{"key": "x", "title": "Plan item"}]})
        self.store.action("claim_next_ticket", {"request_id": "claim-id",
            "candidates": [{"ticket_id": self.ticket["id"], "expected_revision": 1}],
            "assignee": "agent:checker", "actual_model": "unknown",
            "actual_effort": "unknown"}, actor="agent:checker")
        for request_id in ("plan-id", "claim-id"):
            with patch("agentrelay.source_checks.compare_snapshot",
                       side_effect=AssertionError("compared")):
                with self.assertRaises(DomainError) as cross:
                    check_sources(self.store, **self.kwargs(request_id))
            self.assertEqual(cross.exception.status, 409)
        self.assertEqual(list_source_checks(self.store, self.ticket["id"])["total"], 1)

    def test_concurrent_identical_requests_share_one_receipt(self):
        gate = threading.Barrier(2)
        report = freshness.compare_snapshot(self.snapshot, self.root)

        def compare(*args, **kwargs):
            gate.wait(timeout=5)
            return report

        def worker():
            return check_sources(Store(self.store.path), **self.kwargs("concurrent"))

        with patch("agentrelay.source_checks.compare_snapshot", side_effect=compare):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(worker) for _ in range(2)]
                receipts = [future.result(timeout=10) for future in futures]
        self.assertEqual(receipts[0], receipts[1])
        self.assertEqual(list_source_checks(self.store, self.ticket["id"])["total"], 1)
        self.assertEqual(sum(event["action"] == "source_check_recorded" for event in
                             self.store.ticket_events(self.ticket["id"])["events"]), 1)

    def test_pagination_context_bounds_and_backup(self):
        for number in range(5):
            check_sources(self.store, **self.kwargs(f"check-{number}"))
        other = self.store.action("create_ticket", {"title": "Other"})
        check_sources(self.store, **self.kwargs("other", ticket_id=other["id"],
                                               expected_revision=other["revision"]))
        context = self.store.context(self.ticket["id"], event_limit=20)
        self.assertEqual(len(context["source_checks"]), 3)
        self.assertEqual(context["source_checks_page"], {"total": 5, "count": 3,
            "limit": 3, "next_before_id": context["source_checks"][-1]["check_id"]})
        self.assertTrue(all(item["ticket_revision_matches_now"] for item in context["source_checks"]))
        self.assertNotIn("report", context["source_checks"][0])
        first = list_source_checks(self.store, self.ticket["id"], limit=2)
        check_sources(self.store, **self.kwargs("newer"))
        collected = first["checks"][:]
        cursor = first["next_before_id"]
        while cursor is not None:
            page = list_source_checks(self.store, self.ticket["id"], limit=2, before_id=cursor)
            collected.extend(page["checks"])
            cursor = page["next_before_id"]
        self.assertEqual(len(collected), 5)
        self.assertEqual(len({item["check_id"] for item in collected}), 5)
        self.assertTrue(all(item["ticket_id"] == self.ticket["id"] for item in collected))
        self.assertEqual(first["total"], 5)
        self.assertEqual(list_source_checks(self.store, self.ticket["id"])["total"], 6)
        backup = Store(self.store.backup(self.directory / "backup.sqlite"))
        self.assertEqual(get_source_check(backup, collected[0]["check_id"]),
                         get_source_check(self.store, collected[0]["check_id"]))
        self.assertEqual(list_source_checks(backup, self.ticket["id"])["total"], 6)

    def test_detail_rejects_corrupt_stored_report_without_rewriting(self):
        receipt = check_sources(self.store, **self.kwargs())
        with self.store._write() as db:
            db.execute("UPDATE source_checks SET report_json=? WHERE id=?",
                       ('{"tampered":true}', receipt["check_id"]))
        with self.assertRaises(DomainError) as invalid:
            get_source_check(self.store, receipt["check_id"])
        self.assertEqual(invalid.exception.status, 500)
        with self.store._connection() as db:
            self.assertEqual(db.execute("SELECT report_json FROM source_checks WHERE id=?",
                (receipt["check_id"],)).fetchone()[0], '{"tampered":true}')
        self.assertEqual(list_source_checks(self.store, self.ticket["id"])["total"], 1)

    def test_strict_inputs_and_not_found(self):
        bad = ({"expected_revision": True}, {"expected_revision": 0},
               {"request_id": " bad"}, {"actor": "bad "},
               {"expected_snapshot_id": "sha256:" + "A" * 64},
               {"ticket_id": self.ticket["id"] + " "})
        for change in bad:
            with self.subTest(change=change), self.assertRaises(DomainError):
                check_sources(self.store, **self.kwargs(**change))
        for value in (True, 0, 2**63, "1"):
            with self.subTest(value=value), self.assertRaises(DomainError):
                get_source_check(self.store, value)
            with self.subTest(cursor=value), self.assertRaises(DomainError):
                list_source_checks(self.store, self.ticket["id"], before_id=value)
        for value in (True, 0, 101, 1.5):
            with self.subTest(limit=value), self.assertRaises(DomainError):
                list_source_checks(self.store, self.ticket["id"], limit=value)
        with self.assertRaises(DomainError) as absent:
            get_source_check(self.store, 1)
        self.assertEqual(absent.exception.status, 404)
        with self.assertRaises(DomainError) as absent_ticket:
            list_source_checks(self.store, "AR-9999")
        self.assertEqual(absent_ticket.exception.status, 404)


if __name__ == "__main__":
    unittest.main()
