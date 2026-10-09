"""Graph validation handles deep acyclic work and rejects real deadlocks."""

from pathlib import Path
import tempfile
import unittest

from agentrelay.store import DomainError, Store


class DeepGraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-deep-graph-")
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "graph.sqlite")

    def _seed_chain(self, length):
        """Prepare schema-coherent rows without measuring thousands of UI actions."""
        with self.store._write() as db:
            db.executemany("""INSERT INTO tickets
                (id,title,description,type,status,priority,parent_id,profile_id,acceptance,
                 checkpoint,evidence,assignee,actual_model,actual_effort,blocked_reason,
                 revision,created_at,updated_at)
                VALUES(?,?,'','task','queued','normal',?,NULL,'[]','','[]',NULL,NULL,NULL,'',
                       1,'2026-10-10T00:00:00Z','2026-10-10T00:00:00Z')""",
                ((f"AR-{number:04d}", f"Node {number}",
                  f"AR-{number-1:04d}" if number > 1 else None)
                 for number in range(1, length + 1)))
            db.execute("INSERT INTO metadata(key,value) VALUES('ticket_sequence',?)", (str(length),))

    def _counts(self):
        with self.store._connection() as db:
            return (db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0],
                    db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                    db.execute("SELECT value FROM metadata WHERE key='ticket_sequence'").fetchone()[0])

    def test_2500_valid_levels_accept_public_create_and_late_cycle_rolls_back(self):
        self._seed_chain(2500)
        created = self.store.action("create_ticket", {"title": "Valid next ticket"})
        self.assertEqual(created["id"], "AR-2501")
        self.assertEqual(self._counts(), (2501, 1, "2501"))
        with self.assertRaises(DomainError) as caught:
            self.store.action("update_ticket", {"id": "AR-2500", "expected_revision": 1,
                                                "depends_on": ["AR-0001"]})
        self.assertEqual(caught.exception.status, 409)
        with self.store._connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM dependencies").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT revision FROM tickets WHERE id='AR-2500'").fetchone()[0], 1)
        self.assertEqual(self._counts(), (2501, 1, "2501"))

    def test_shared_diamond_is_acyclic(self):
        root = self.store.action("create_ticket", {"title": "Root"})
        shared = self.store.action("create_ticket", {"title": "Shared prerequisite"})
        first = self.store.action("create_ticket", {"title": "First branch", "parent_id": root["id"],
                                                    "depends_on": [shared["id"]]})
        second = self.store.action("create_ticket", {"title": "Second branch", "parent_id": root["id"],
                                                     "depends_on": [shared["id"]]})
        changed = self.store.action("update_ticket", {"id": second["id"], "expected_revision": 1,
                                                      "description": "Both branches share one result"})
        self.assertEqual(changed["revision"], 2)
        self.assertEqual(first["depends_on"], [shared["id"]])
        self.assertEqual(self._counts(), (4, 5, "4"))

    def test_mixed_parent_dependency_cycle_rejected_without_partial_audit(self):
        parent = self.store.action("create_ticket", {"title": "Parent"})
        child = self.store.action("create_ticket", {"title": "Child", "parent_id": parent["id"]})
        before = self._counts()
        with self.assertRaises(DomainError) as caught:
            self.store.action("update_ticket", {"id": child["id"], "expected_revision": 1,
                                                "depends_on": [parent["id"]]})
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self._counts(), before)
        self.assertEqual(self.store.context(child["id"])["ticket"]["depends_on"], [])
        self.assertEqual(self.store.context(child["id"])["ticket"]["revision"], 1)


if __name__ == "__main__":
    unittest.main()
