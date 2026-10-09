"""Bounded per-ticket event reads preserve complete context and durable history."""

from pathlib import Path
import tempfile
import unittest

from agentrelay.store import DomainError, Store


class TicketHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-ticket-history-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "history.sqlite"
        self.store = Store(self.path)
        self.ticket = self.store.action("create_ticket", {"title": "Target"})["id"]
        self.other = self.store.action("create_ticket", {"title": "Other"})["id"]
        for index in range(60):
            self.store.action("add_comment", {"id": self.ticket, "body": f"Target note {index}"})
            if index % 3 == 0:
                self.store.action("add_comment", {"id": self.other, "body": f"Other note {index}"})

    def test_pages_are_descending_ticket_scoped_and_complete(self):
        full = self.store.context(self.ticket)
        self.assertEqual(len(full["events"]), 61)
        self.assertNotIn("events_page", full)
        expected = [event["id"] for event in full["events"]]
        collected = []
        cursor = None
        counts = []
        while True:
            page = self.store.ticket_events(self.ticket, limit=20, before_id=cursor)
            counts.append(page["count"])
            self.assertEqual(page["ticket_id"], self.ticket)
            self.assertEqual(page["total"], 61)
            self.assertEqual(page["limit"], 20)
            self.assertEqual(page["before_id"], cursor)
            self.assertEqual(page["count"], len(page["events"]))
            self.assertTrue(all(event["ticket_id"] == self.ticket for event in page["events"]))
            ids = [event["id"] for event in page["events"]]
            self.assertEqual(ids, sorted(ids, reverse=True))
            if cursor is not None:
                self.assertTrue(all(identity < cursor for identity in ids))
            collected.extend(ids)
            if page["next_before_id"] is None:
                break
            self.assertEqual(page["next_before_id"], ids[-1])
            cursor = page["next_before_id"]
        self.assertEqual(counts, [20, 20, 20, 1])
        self.assertEqual(collected, expected)
        self.assertEqual(self.store.ticket_events(self.ticket, limit=20, before_id=expected[-1])["events"], [])
        self.assertEqual(len(self.store.export()["events"]), 82)  # 61 target + 21 other.

    def test_new_events_do_not_shift_older_cursor_and_total_is_current(self):
        first = self.store.ticket_events(self.ticket, limit=9)
        older_before = first["next_before_id"]
        self.assertIsNotNone(older_before)
        self.store.action("add_comment", {"id": self.ticket, "body": "Arrived later"})
        second = self.store.ticket_events(self.ticket, limit=9, before_id=older_before)
        self.assertEqual(second["total"], 62)
        self.assertEqual(second["before_id"], older_before)
        self.assertTrue(all(event["id"] < older_before for event in second["events"]))
        self.assertTrue(set(event["id"] for event in first["events"]).isdisjoint(
            event["id"] for event in second["events"]))
        self.assertEqual(self.store.ticket_events(self.ticket, limit=1)["events"][0]["details"]["body"],
                         "Arrived later")

    def test_context_bounded_and_default_full_in_one_ticket_read(self):
        bounded = self.store.context(self.ticket, event_limit=7)
        self.assertEqual(len(bounded["events"]), 7)
        self.assertEqual(bounded["events_page"], {
            "total": 61, "count": 7, "limit": 7,
            "next_before_id": bounded["events"][-1]["id"],
        })
        self.assertEqual(bounded["events"], self.store.ticket_events(self.ticket, limit=7)["events"])
        full = self.store.context(self.ticket)
        self.assertEqual(len(full["events"]), 61)
        self.assertNotIn("events_page", full)
        large = self.store.context(self.ticket, event_limit=100)
        self.assertEqual(len(large["events"]), 61)
        self.assertEqual(large["events_page"]["next_before_id"], None)
        self.assertEqual(self.store.context(self.other, event_limit=5)["events_page"]["total"], 21)

    def test_invalid_arguments_unknown_ticket_and_empty_boundary(self):
        for value in (True, False, 0, -1, 101, 1.5, "20", None):
            if value is None:
                continue  # None is the documented full-history context default.
            with self.subTest(limit=value), self.assertRaises(DomainError) as caught:
                self.store.ticket_events(self.ticket, limit=value)
            self.assertEqual(caught.exception.status, 400)
            with self.subTest(event_limit=value), self.assertRaises(DomainError) as caught:
                self.store.context(self.ticket, event_limit=value)
            self.assertEqual(caught.exception.status, 400)
        for value in (True, False, 0, -1, 2**63, 1.5, "8"):
            with self.subTest(before_id=value), self.assertRaises(DomainError) as caught:
                self.store.ticket_events(self.ticket, before_id=value)
            self.assertEqual(caught.exception.status, 400)
        with self.assertRaises(DomainError) as caught:
            self.store.ticket_events("AR-9999")
        self.assertEqual(caught.exception.status, 404)
        with self.assertRaises(DomainError) as caught:
            self.store.context("AR-9999", event_limit=3)
        self.assertEqual(caught.exception.status, 404)
        empty = self.store.ticket_events(self.ticket, before_id=1)
        self.assertEqual((empty["count"], empty["total"], empty["next_before_id"]), (0, 61, None))
        max_cursor = self.store.ticket_events(self.ticket, limit=2, before_id=2**63 - 1)
        self.assertEqual(max_cursor["count"], 2)
        self.assertEqual(max_cursor["next_before_id"], max_cursor["events"][-1]["id"])

    def test_reopen_and_backup_preserve_full_events(self):
        before = self.store.context(self.ticket)["events"]
        reopened = Store(self.path)
        self.assertEqual(reopened.context(self.ticket)["events"], before)
        backup = Path(self.temp.name) / "backup.sqlite"
        self.store.backup(backup)
        restored = Store(backup)
        self.assertEqual(restored.context(self.ticket)["events"], before)
        self.assertEqual(restored.ticket_events(self.ticket, limit=10)["total"], 61)


if __name__ == "__main__":
    unittest.main()
