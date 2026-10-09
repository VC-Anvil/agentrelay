"""Multi-project summaries stay bounded and never activate configured workers."""

from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from agentrelay.overview import SUMMARY_FIELDS, project_overview
from agentrelay.store import DomainError, Store


class ProjectOverviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-overview-")
        self.root = Path(self.temp.name).resolve()

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def create(store, title, *, priority="normal", depends_on=None):
        return store.action("create_ticket", {
            "title": title,
            "priority": priority,
            "acceptance": [f"Verify {title}"],
            "depends_on": depends_on or [],
            "profile_id": "sol",
        })

    @staticmethod
    def domain(state):
        return {key: state[key] for key in ("tickets", "profiles", "events", "runs")}

    @staticmethod
    def tables(database):
        with closing(sqlite3.connect(database)) as connection:
            return {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}

    def prepare_registry(self):
        alpha_path = self.root / "alpha.sqlite"
        beta_path = self.root / "beta.sqlite"
        alpha, beta = Store(alpha_path), Store(beta_path)

        self.create(alpha, "Alpha urgent", priority="urgent")
        self.create(alpha, "Alpha high", priority="high")
        self.create(alpha, "Alpha normal")
        self.create(alpha, "Alpha low", priority="low")
        prerequisite = self.create(alpha, "Alpha prerequisite", priority="low")
        self.create(alpha, "Alpha derived blocker", priority="urgent",
                    depends_on=[prerequisite["id"]])
        blocked = self.create(alpha, "Alpha explicit block")
        alpha.action("transition", {"id": blocked["id"],
                     "expected_revision": blocked["revision"], "status": "blocked",
                     "reason": "Waiting for an external decision"})
        review = self.create(alpha, "Alpha review", priority="high")
        review = alpha.action("claim_ticket", {
            "id": review["id"], "expected_revision": review["revision"],
            "assignee": "agent:alpha", "actual_model": "fixture", "actual_effort": "high",
        }, actor="agent:alpha")
        alpha.action("submit_ticket", {
            "id": review["id"], "expected_revision": review["revision"],
            "summary": "Ready for independent review",
            "evidence": [{"kind": "test", "label": "Fixture", "uri": "fixture://alpha"}],
        }, actor="agent:alpha")

        self.create(beta, "Beta urgent", priority="urgent")
        closed = self.create(beta, "Beta closed urgent", priority="urgent")
        closed = beta.action("claim_ticket", {
            "id": closed["id"], "expected_revision": closed["revision"],
            "assignee": "agent:beta", "actual_model": "fixture", "actual_effort": "high",
        }, actor="agent:beta")
        closed = beta.action("submit_ticket", {
            "id": closed["id"], "expected_revision": closed["revision"],
            "summary": "Checked",
            "evidence": [{"kind": "test", "label": "Fixture", "uri": "fixture://beta"}],
        }, actor="agent:beta")
        beta.action("complete_ticket", {
            "id": closed["id"], "expected_revision": closed["revision"],
            "verification": "Independent fixture review",
            "accepted_criteria": closed["acceptance"],
        }, actor="agent:checker")
        with closing(sqlite3.connect(beta_path)) as connection:
            connection.execute("INSERT INTO metadata(key,value) VALUES('demo_seeded','1')")
            connection.commit()

        registry = self.root / "workspaces.json"
        registry.write_text(json.dumps({
            "default_workspace_id": "beta",
            "workspaces": [
                {"id": "alpha", "name": "Alpha project", "db": "alpha.sqlite",
                 "workers": "missing-alpha-workers.json"},
                {"id": "beta", "name": "Beta project", "db": "beta.sqlite",
                 "workers": "missing-beta-workers.json"},
            ],
        }), encoding="utf-8")
        return registry, {"alpha": alpha, "beta": beta}

    def test_bounded_isolated_overview_never_activates_workers_or_changes_domain(self):
        registry, stores = self.prepare_registry()
        before = {key: store.state() for key, store in stores.items()}
        calls = Counter()
        original_state = Store.state

        def counted_state(store):
            calls[str(Path(store.path).resolve())] += 1
            return original_state(store)

        with patch("agentrelay.execution.ExecutionManager",
                   side_effect=AssertionError("overview activated execution")) as manager:
            with patch.object(Store, "state", new=counted_state):
                result = project_overview(registry, limit=2)
        manager.assert_not_called()

        self.assertEqual(set(result), {"schema_version", "default_workspace_id", "count",
                                      "limit", "projects"})
        self.assertEqual((result["schema_version"], result["default_workspace_id"],
                          result["count"], result["limit"]), (1, "beta", 2, 2))
        self.assertNotIn("missing-alpha-workers.json", json.dumps(result))
        projects = {project["id"]: project for project in result["projects"]}
        self.assertEqual(list(projects), ["alpha", "beta"])
        self.assertEqual(calls, Counter({str((self.root / "alpha.sqlite").resolve()): 1,
                                         str((self.root / "beta.sqlite").resolve()): 1}))

        alpha, beta = projects["alpha"], projects["beta"]
        expected_project_fields = {"id", "name", "database", "demo", "stats", "urgent_open",
                                   "ready", "review", "blocked"}
        self.assertEqual(set(alpha), expected_project_fields)
        self.assertEqual(set(beta), expected_project_fields)
        self.assertFalse(alpha["demo"])
        self.assertTrue(beta["demo"])
        self.assertEqual(alpha["stats"], before["alpha"]["stats"])
        self.assertEqual(beta["stats"], before["beta"]["stats"])
        self.assertEqual((alpha["urgent_open"], beta["urgent_open"]), (2, 1))

        self.assertEqual(alpha["ready"]["total"], 5)
        self.assertEqual([ticket["title"] for ticket in alpha["ready"]["tickets"]],
                         ["Alpha urgent", "Alpha high"])
        self.assertEqual(alpha["review"]["total"], 1)
        self.assertEqual(alpha["review"]["tickets"][0]["title"], "Alpha review")
        self.assertEqual(alpha["blocked"]["total"], 2)
        self.assertEqual([ticket["title"] for ticket in alpha["blocked"]["tickets"]],
                         ["Alpha derived blocker", "Alpha explicit block"])
        for category in ("ready", "review", "blocked"):
            for ticket in alpha[category]["tickets"] + beta[category]["tickets"]:
                self.assertEqual(set(ticket), set(SUMMARY_FIELDS))
                self.assertNotIn("acceptance", ticket)
                self.assertNotIn("evidence", ticket)

        self.assertEqual(alpha["ready"]["tickets"][0]["id"], "AR-0001")
        self.assertEqual(beta["ready"]["tickets"][0]["id"], "AR-0001")
        self.assertNotEqual(alpha["ready"]["tickets"][0]["title"],
                            beta["ready"]["tickets"][0]["title"])

        after = {key: store.state() for key, store in stores.items()}
        for key in stores:
            self.assertEqual(self.domain(after[key]), self.domain(before[key]))
            self.assertNotIn("execution_runs", self.tables(self.root / f"{key}.sqlite"))

    def test_limit_is_strict_and_checked_before_registry_loading(self):
        invalid = (True, False, 0, 21, 1.0, "5", None)
        with patch("agentrelay.overview.load_workspaces",
                   side_effect=AssertionError("registry loaded before limit validation")) as loader:
            for value in invalid:
                with self.subTest(limit=value):
                    with self.assertRaisesRegex(DomainError, "limit must be an integer"):
                        project_overview(self.root / "missing.json", limit=value)
        loader.assert_not_called()

    def test_missing_and_duplicate_registry_entries_fail_without_creating_database(self):
        with self.assertRaises(DomainError):
            project_overview(self.root / "missing-registry.json")

        valid = self.root / "valid.sqlite"
        Store(valid)
        missing = self.root / "missing.sqlite"
        registry = self.root / "invalid.json"
        for entries in (
            [{"id": "missing", "name": "Missing", "db": "missing.sqlite"}],
            [{"id": "one", "name": "One", "db": "valid.sqlite"},
             {"id": "two", "name": "Two", "db": "valid.sqlite"}],
            [{"id": "same", "name": "One", "db": "valid.sqlite"},
             {"id": "same", "name": "Two", "db": "second.sqlite"}],
        ):
            if entries[-1]["db"] == "second.sqlite":
                Store(self.root / "second.sqlite")
            registry.write_text(json.dumps({"workspaces": entries}), encoding="utf-8")
            with self.subTest(entries=entries):
                with self.assertRaises(DomainError):
                    project_overview(registry)
        self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
