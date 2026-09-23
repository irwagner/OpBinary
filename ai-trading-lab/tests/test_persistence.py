from __future__ import annotations

import json
import sqlite3
import unittest

from ai_trading_lab.errors import PersistenceError
from ai_trading_lab.models import Actor, ActorRole, AuditEvent, Experiment, SystemStatus
from ai_trading_lab.persistence import SQLiteStore
from ai_trading_lab.state import StateManager


class PersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SQLiteStore()
        self.supervisor = Actor("supervisor-test", ActorRole.SUPERVISOR)

    def tearDown(self) -> None:
        self.store.close()

    def test_state_is_initialized_and_loaded_only_through_state_manager(self) -> None:
        manager = StateManager(self.store)
        manager.transition(
            SystemStatus.RUNNING,
            "cycle started",
            actor=self.supervisor,
        )

        loaded = self.store.load_system_state()
        self.assertIsNotNone(loaded)
        self.assertEqual(SystemStatus.RUNNING, loaded.status)
        self.assertFalse(hasattr(self.store, "save_system_state"))

    def test_state_and_audit_roll_back_together(self) -> None:
        manager = StateManager(self.store)
        events_before = len(self.store.list_audit_events())
        self.store._connection.executescript(
            """
            CREATE TRIGGER fail_state_change_audit
            BEFORE INSERT ON audit_events
            WHEN NEW.event_type = 'system_state_changed'
            BEGIN SELECT RAISE(ABORT, 'forced audit failure'); END;
            """
        )

        with self.assertRaises(PersistenceError):
            manager.transition(SystemStatus.RUNNING, actor=self.supervisor)

        persisted = self.store.load_system_state()
        self.assertIsNotNone(persisted)
        self.assertEqual(SystemStatus.IDLE, persisted.status)
        self.assertEqual(SystemStatus.IDLE, manager.snapshot.status)
        self.assertEqual(events_before, len(self.store.list_audit_events()))

    def test_audit_payload_is_sanitized_before_persistence(self) -> None:
        self.store.append_audit_event(
            AuditEvent(
                "credentials_checked",
                "system",
                {
                    "api_key": "raw-api-key",
                    "Authorization": "Bearer live-token",
                    "message": "credential=secret with spaces; done",
                },
            )
        )

        payload = json.loads(self.store.list_audit_events()[-1]["payload"])
        serialized = json.dumps(payload)
        self.assertEqual("***REDACTED***", payload["api_key"])
        self.assertEqual("***REDACTED***", payload["Authorization"])
        self.assertNotIn("raw-api-key", serialized)
        self.assertNotIn("live-token", serialized)
        self.assertNotIn("secret with spaces", serialized)

    def test_audit_events_are_append_only(self) -> None:
        self.store.append_audit_event(AuditEvent("created", "system", {"value": 1}))

        for statement in (
            "UPDATE audit_events SET actor = 'changed'",
            "DELETE FROM audit_events",
        ):
            with self.subTest(statement=statement):
                with self.assertRaises(sqlite3.DatabaseError):
                    self.store._connection.execute(statement)
                self.store._connection.rollback()

        self.assertEqual(1, len(self.store.list_audit_events()))

    def test_experiment_cannot_be_overwritten_updated_or_deleted(self) -> None:
        experiment = Experiment(
            "EXP-000001",
            "HYP-000001",
            "DATA-000001",
            "v0.1.0",
            "v0.1.0",
        )
        self.store.append_experiment(experiment)

        with self.assertRaises(PersistenceError):
            self.store.append_experiment(experiment)

        for statement in (
            "UPDATE experiments SET status = 'CHANGED'",
            "DELETE FROM experiments",
        ):
            with self.subTest(statement=statement):
                with self.assertRaises(sqlite3.DatabaseError):
                    self.store._connection.execute(statement)
                self.store._connection.rollback()
