"""Integration review regressions: real competing writers and closed scope."""

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from agentrelay.store import DomainError, Store


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-integrity-")
        self.store = Store(Path(self.temp.name) / "integrity.sqlite")

    def tearDown(self):
        self.temp.cleanup()

    def test_concurrent_workers_only_one_claim_succeeds(self):
        ticket = self.store.action("create_ticket", {"title": "Exclusive ownership"})
        barrier = Barrier(2)

        def claim(name):
            barrier.wait(timeout=5)
            try:
                self.store.action("claim_ticket", {"id": ticket["id"], "expected_revision": 1, "assignee": name}, name)
                return "claimed"
            except DomainError as exc:
                return exc.status

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, ["agent:first", "agent:second"]))
        self.assertCountEqual(results, ["claimed", 409])
        self.assertEqual(self.store.context(ticket["id"])["ticket"]["revision"], 2)

    def test_closed_parent_cannot_acquire_new_unreviewed_scope(self):
        parent = self.store.action("create_ticket", {"title": "Closed goal", "acceptance": ["Integrated result reviewed"]})
        parent = self.store.action("claim_ticket", {"id": parent["id"], "expected_revision": 1, "assignee": "agent:worker"})
        parent = self.store.action("submit_ticket", {"id": parent["id"], "expected_revision": parent["revision"], "summary": "Delivered", "evidence": [{"kind": "test", "label": "Fixture", "uri": "test://closed"}]})
        parent = self.store.action("complete_ticket", {"id": parent["id"], "expected_revision": parent["revision"], "verification": "Reviewed", "accepted_criteria": parent["acceptance"]})
        with self.assertRaises(DomainError) as error:
            self.store.action("create_ticket", {"title": "New child", "parent_id": parent["id"]})
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(len(self.store.state()["tickets"]), 1)

    def test_models_without_reasoning_setting_are_supported(self):
        for effort in ("none", "default"):
            profile = self.store.action("create_profile", {"name": "Local", "role": "extraction", "model": "user-configured-local-model", "effort": effort})
            self.assertEqual(profile["effort"], effort)


if __name__ == "__main__":
    unittest.main()
