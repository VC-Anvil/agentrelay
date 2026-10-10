"""Historical ticket-action receipt lookup is scoped, bounded, and read-only."""

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from agentrelay.store import (DomainError, MAX_ACTION_RESULT_BYTES, Store,
                              validate_action_receipt_query)


class ActionReceiptLookupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-receipt-lookup-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "tickets.sqlite"
        self.store = Store(self.path)

    def keyed(self, key="lookup-key", *, actor="agent:writer"):
        return self.store.action("apply_ticket_action", {
            "request_id": key, "action": "create_ticket",
            "data": {"title": "Niño", "acceptance": ["Reviewed"]},
        }, actor)

    def lookup(self, key="lookup-key", *, actor="agent:writer"):
        return self.store.get_action_receipt(key, actor=actor)

    def assert_lookup_error(self, status, key, *, actor="agent:writer"):
        with self.assertRaises(DomainError) as caught:
            self.lookup(key, actor=actor)
        self.assertEqual(caught.exception.status, status)
        return str(caught.exception)

    def test_query_validator_is_pure_and_matches_wrapped_identity(self):
        valid = validate_action_receipt_query("á/" + "x" * 126,
                                              actor="  agent:writer  ")
        self.assertEqual(valid, {"request_id": "á/" + "x" * 126,
                                 "actor": "agent:writer"})
        for key in (None, True, 7, "", " key", "key ", "x" * 129, "\ud800"):
            with self.subTest(key=repr(key)), self.assertRaises(DomainError) as caught:
                validate_action_receipt_query(key, actor="agent:writer")
            self.assertEqual(caught.exception.status, 400)
        for actor in (None, "", "   ", "\ud800"):
            with self.subTest(actor=repr(actor)), self.assertRaises(DomainError) as caught:
                validate_action_receipt_query("key", actor=actor)
            self.assertEqual(caught.exception.status, 400)
        with patch.object(self.store, "_connection", side_effect=AssertionError("DB opened")):
            self.assert_lookup_error(400, " invalid")

    def test_historical_result_after_edit_reopen_backup_and_no_logical_writes(self):
        original = self.keyed()
        ticket_id = original["result"]["id"]
        self.store.action("update_ticket", {"id": ticket_id, "expected_revision": 1,
                                            "title": "Changed later"})
        self.store.action("transition", {"id": ticket_id, "expected_revision": 2,
                                          "status": "cancelled", "reason": "Pause"})
        self.store.action("transition", {"id": ticket_id, "expected_revision": 3,
                                          "status": "queued", "reason": "Resume"})
        with self.store._connection() as db:
            before = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("tickets", "events", "action_requests", "metadata")}
            before_revision = db.execute("SELECT revision FROM tickets WHERE id=?",
                                         (ticket_id,)).fetchone()[0]
        receipt = self.lookup(actor=" agent:writer ")
        self.assertEqual(set(receipt), {"schema_version", "receipt"})
        self.assertEqual(receipt["schema_version"], 1)
        self.assertEqual(receipt["receipt"], {
            "request_id": original["request_id"], "action": original["action"],
            "actor": original["actor"], "committed_at": original["committed_at"],
            "result": original["result"],
        })
        self.assertNotIn("replayed", receipt["receipt"])
        self.assertEqual(receipt["receipt"]["result"]["title"], "Niño")
        self.assertEqual(self.store.context(ticket_id)["ticket"]["title"], "Changed later")
        with self.store._connection() as db:
            after = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                     for table in before}
            after_revision = db.execute("SELECT revision FROM tickets WHERE id=?",
                                        (ticket_id,)).fetchone()[0]
        self.assertEqual(after, before)
        self.assertEqual(after_revision, before_revision)
        backup = self.store.backup(Path(self.temp.name) / "copy.sqlite")
        self.assertEqual(Store(backup).get_action_receipt("lookup-key", actor="agent:writer"), receipt)

    def test_absent_other_actor_and_other_namespaces_share_generic_404(self):
        self.keyed()
        ticket = self.store.action("create_ticket", {"title": "For source"})
        with self.store._connection() as db:
            db.execute("INSERT INTO plan_requests VALUES (?,?,?,?)",
                       ("plan-only", "agent:writer", "hash", "{}"))
            db.execute("INSERT INTO claim_requests VALUES (?,?,?,?)",
                       ("claim-only", "agent:writer", "hash", "{}"))
            db.execute("INSERT INTO source_checks(request_id,ticket_id,ticket_revision,actor,"
                       "intent_json,intent_sha256,snapshot_id,report_sha256,report_json,"
                       "summary_json,checked_at,recorded_at,receipt_json) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("source-only", ticket["id"], 1, "agent:writer", "{}", "hash",
                        "snap", "hash", "{}", "{}", "now", "now", "{}"))
        messages = [self.assert_lookup_error(404, key, actor=actor)
                    for key, actor in (("missing", "agent:writer"),
                                       ("lookup-key", "agent:other"),
                                       ("plan-only", "agent:writer"),
                                       ("claim-only", "agent:writer"),
                                       ("source-only", "agent:writer"))]
        self.assertEqual(len(set(messages)), 1)
        self.assertEqual(self.lookup()["receipt"]["request_id"], "lookup-key")

    def test_invalid_saved_result_and_metadata_fail_without_partial_response(self):
        self.keyed()
        base = self.lookup()
        nested = []
        for _ in range(64):
            nested = [nested]
        failures = [
            ("result_json", "[1]"),
            ("result_json", "{broken"),
            ("result_json", '{"x":NaN}'),
            ("result_json", '{"x":1e999}'),
            ("result_json", json.dumps({"x": "\ud800"})),
            ("result_json", json.dumps({"x": nested})),
            ("result_json", '{"x":"' + "x" * MAX_ACTION_RESULT_BYTES + '"}'),
            ("action", "not_a_ticket_action"),
            ("committed_at", ""),
            ("committed_at", "x" * 65),
        ]
        with self.store._connection() as db:
            for column, value in failures:
                with self.subTest(column=column, prefix=value[:20]):
                    db.execute(f"UPDATE action_requests SET {column}=? WHERE request_id='lookup-key'",
                               (value,))
                    self.assert_lookup_error(500, "lookup-key")
                    db.execute(f"UPDATE action_requests SET {column}=? WHERE request_id='lookup-key'",
                               (json.dumps(base["receipt"]["result"], ensure_ascii=False)
                                if column == "result_json" else base["receipt"][column],))
        self.assertEqual(self.lookup(), base)

    def test_real_action_is_invisible_until_commit_and_rollback_leaves_no_effect(self):
        def counts():
            with self.store._connection() as db:
                return tuple(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                             for table in ("tickets", "events", "action_requests"))

        for key, rollback in (("future-commit", False), ("future-rollback", True)):
            with self.subTest(key=key):
                writer = Store(self.path)  # Initialize before the write lock is held.
                original_write = writer._write
                inserted = threading.Event()
                release = threading.Event()
                before = counts()

                @contextmanager
                def gated_write():
                    with original_write() as db:
                        yield db  # The real action inserts the ticket, event and receipt.
                        self.assertEqual(db.execute(
                            "SELECT COUNT(*) FROM action_requests WHERE request_id=?",
                            (key,)).fetchone()[0], 1)
                        inserted.set()
                        if not release.wait(5):
                            raise TimeoutError("test did not release pending commit")
                        if rollback:
                            raise RuntimeError("test forces rollback before commit")

                request = {"request_id": key, "action": "create_ticket",
                           "data": {"title": key, "acceptance": ["Reviewed"]}}
                with patch.object(writer, "_write", gated_write):
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        future = pool.submit(writer.action, "apply_ticket_action", request,
                                             "agent:writer")
                        try:
                            self.assertTrue(inserted.wait(5), "write did not reach pre-commit gate")
                            self.assert_lookup_error(404, key)
                            self.assertEqual(counts(), before)
                        finally:
                            release.set()
                        if rollback:
                            with self.assertRaisesRegex(RuntimeError, "forces rollback"):
                                future.result(timeout=5)
                            self.assert_lookup_error(404, key)
                            self.assertEqual(counts(), before)
                        else:
                            committed = future.result(timeout=5)
                            self.assertEqual(self.lookup(key)["receipt"]["result"],
                                             committed["result"])
                            self.assertEqual(counts(), tuple(number + 1 for number in before))

    def test_legacy_table_absent_is_404_without_recreating_it(self):
        with self.store._connection() as db:
            db.execute("DROP TABLE action_requests")
        self.assert_lookup_error(404, "whatever")
        with self.store._connection() as db:
            tables = db.execute("SELECT name FROM sqlite_master WHERE name='action_requests'").fetchall()
        self.assertEqual(tables, [])


if __name__ == "__main__":
    unittest.main()
