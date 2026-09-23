from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai_trading_lab.errors import InvalidStateTransition, PermissionDeniedError
from ai_trading_lab.models import Actor, ActorRole, SystemStatus
from ai_trading_lab.persistence import SQLiteStore
from ai_trading_lab.state import StateManager


class StateManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SQLiteStore()
        self.manager = StateManager(self.store)
        self.supervisor = Actor("supervisor-test", ActorRole.SUPERVISOR)
        self.human = Actor("human-test", ActorRole.HUMAN)
        self.validator = Actor("validator-test", ActorRole.VALIDATOR)

    def tearDown(self) -> None:
        self.store.close()

    def test_initial_state_is_idle(self) -> None:
        self.assertEqual(SystemStatus.IDLE, self.manager.snapshot.status)

    def test_transitions_to_running(self) -> None:
        snapshot = self.manager.transition(
            SystemStatus.RUNNING,
            "cycle started",
            actor=self.supervisor,
        )
        self.assertEqual(SystemStatus.RUNNING, snapshot.status)

    def test_transitions_to_paused(self) -> None:
        self.manager.transition(SystemStatus.RUNNING, actor=self.supervisor)
        snapshot = self.manager.transition(
            SystemStatus.PAUSED,
            "manual pause",
            actor=self.supervisor,
        )
        self.assertEqual(SystemStatus.PAUSED, snapshot.status)

    def test_transitions_to_error(self) -> None:
        self.manager.transition(SystemStatus.RUNNING, actor=self.supervisor)
        snapshot = self.manager.transition(
            SystemStatus.ERROR,
            "agent failed",
            actor=self.supervisor,
        )
        self.assertEqual(SystemStatus.ERROR, snapshot.status)

    def test_transitions_to_stopped(self) -> None:
        self.manager.transition(SystemStatus.RUNNING, actor=self.supervisor)
        snapshot = self.manager.transition(
            SystemStatus.STOPPED,
            "normal stop",
            actor=self.supervisor,
        )
        self.assertEqual(SystemStatus.STOPPED, snapshot.status)

    def test_transitions_to_emergency_stopped_from_active_state(self) -> None:
        self.manager.transition(SystemStatus.RUNNING, actor=self.supervisor)
        snapshot = self.manager.emergency_stop("kill switch", actor=self.human)
        self.assertEqual(SystemStatus.EMERGENCY_STOPPED, snapshot.status)
        self.assertEqual("kill switch", snapshot.reason)

    def test_emergency_state_cannot_resume_automatically(self) -> None:
        self.manager.emergency_stop("kill switch", actor=self.human)
        with self.assertRaises(InvalidStateTransition):
            self.manager.transition(SystemStatus.RUNNING, actor=self.supervisor)

    def test_supervisor_cannot_activate_emergency_stop(self) -> None:
        with self.assertRaises(PermissionDeniedError):
            self.manager.emergency_stop("not authorized", actor=self.supervisor)

        self.assertEqual(SystemStatus.IDLE, self.manager.snapshot.status)
        self.assertEqual("permission_denied", self.store.list_audit_events()[-1]["event_type"])

    def test_validator_cannot_manage_global_state(self) -> None:
        with self.assertRaises(PermissionDeniedError):
            self.manager.transition(SystemStatus.RUNNING, actor=self.validator)

        self.assertEqual(SystemStatus.IDLE, self.manager.snapshot.status)

    def test_rejects_invalid_transition(self) -> None:
        with self.assertRaises(InvalidStateTransition):
            self.manager.transition(SystemStatus.PAUSED, actor=self.supervisor)

    def test_persists_state_for_restart(self) -> None:
        self.manager.transition(SystemStatus.RUNNING, actor=self.supervisor)
        restarted = StateManager(self.store)
        self.assertEqual(SystemStatus.RUNNING, restarted.snapshot.status)

    def test_stale_manager_cannot_override_emergency_stop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "state.db"
            first_store = SQLiteStore(database_path)
            second_store = SQLiteStore(database_path)
            try:
                first = StateManager(first_store)
                stale = StateManager(second_store)
                first.transition(SystemStatus.RUNNING, actor=self.supervisor)
                stale.emergency_stop("kill switch", actor=self.human)

                with self.assertRaises(InvalidStateTransition):
                    first.transition(SystemStatus.PAUSED, actor=self.supervisor)

                persisted = first_store.load_system_state()
                self.assertIsNotNone(persisted)
                self.assertEqual(SystemStatus.EMERGENCY_STOPPED, persisted.status)
                self.assertEqual(SystemStatus.EMERGENCY_STOPPED, first.snapshot.status)
            finally:
                first_store.close()
                second_store.close()
