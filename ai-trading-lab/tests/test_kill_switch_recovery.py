from __future__ import annotations

import sqlite3
import unittest

from ai_trading_lab.errors import InvalidStateTransition, PermissionDeniedError
from ai_trading_lab.models import Actor, ActorRole, SystemStatus
from ai_trading_lab.persistence import SQLiteStore
from ai_trading_lab.state import StateManager


class KillSwitchRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SQLiteStore()
        self.manager = StateManager(self.store)
        self.human = Actor("operator-test", ActorRole.HUMAN)
        self.supervisor = Actor("supervisor-test", ActorRole.SUPERVISOR)
        self.validator = Actor("validator-test", ActorRole.VALIDATOR)

    def tearDown(self) -> None:
        self.store.close()

    def test_human_can_clear_emergency_stop_to_stopped(self) -> None:
        self.manager.emergency_stop("incidente", actor=self.human)

        snapshot = self.manager.clear_emergency_stop("incidente resolvido", actor=self.human)

        self.assertIs(SystemStatus.STOPPED, snapshot.status)
        self.assertIs(SystemStatus.STOPPED, self.store.load_system_state().status)

    def test_clearing_does_not_resume_operation_directly(self) -> None:
        self.manager.emergency_stop("incidente", actor=self.human)
        self.manager.clear_emergency_stop("resolvido", actor=self.human)

        # STOPPED só vai para IDLE; retomar exige passos deliberados.
        self.assertIs(SystemStatus.STOPPED, self.manager.snapshot.status)
        resumed = self.manager.transition(SystemStatus.IDLE, actor=self.supervisor)
        self.assertIs(SystemStatus.IDLE, resumed.status)

    def test_supervisor_cannot_clear_emergency_stop(self) -> None:
        self.manager.emergency_stop("incidente", actor=self.human)

        with self.assertRaises(PermissionDeniedError):
            self.manager.clear_emergency_stop("tentativa indevida", actor=self.supervisor)

        self.assertIs(
            SystemStatus.EMERGENCY_STOPPED, self.store.load_system_state().status
        )

    def test_validator_cannot_clear_emergency_stop(self) -> None:
        self.manager.emergency_stop("incidente", actor=self.human)

        with self.assertRaises(PermissionDeniedError):
            self.manager.clear_emergency_stop("tentativa indevida", actor=self.validator)

    def test_cannot_clear_when_not_emergency_stopped(self) -> None:
        with self.assertRaises(InvalidStateTransition):
            self.manager.clear_emergency_stop("nada a limpar", actor=self.human)

    def test_normal_transition_still_cannot_leave_emergency_stopped(self) -> None:
        self.manager.emergency_stop("incidente", actor=self.human)

        with self.assertRaises(InvalidStateTransition):
            self.manager.transition(SystemStatus.RUNNING, actor=self.supervisor)
        with self.assertRaises(InvalidStateTransition):
            self.manager.transition(SystemStatus.STOPPED, actor=self.supervisor)

    def test_direct_sql_cannot_revive_to_running(self) -> None:
        self.manager.emergency_stop("incidente", actor=self.human)

        with self.assertRaises(sqlite3.DatabaseError):
            self.store._connection.execute(
                "UPDATE system_state SET status = 'RUNNING' WHERE singleton_id = 1"
            )
        self.store._connection.rollback()

        self.assertIs(
            SystemStatus.EMERGENCY_STOPPED, self.store.load_system_state().status
        )

    def test_clearing_is_audited(self) -> None:
        self.manager.emergency_stop("incidente", actor=self.human)
        self.manager.clear_emergency_stop("resolvido", actor=self.human)

        event_types = [event["event_type"] for event in self.store.list_audit_events()]
        self.assertIn("emergency_stop", event_types)
        self.assertIn("emergency_stop_cleared", event_types)


class GuardSchemaMigrationTests(unittest.TestCase):
    """Um banco criado com barreiras antigas deve ser atualizado na abertura."""

    def test_stale_trigger_is_replaced_on_open(self) -> None:
        import tempfile
        from pathlib import Path

        from ai_trading_lab.persistence import GUARD_SCHEMA_VERSION

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.db"

            first = SQLiteStore(database)
            manager = StateManager(first)
            manager.emergency_stop("incidente", actor=Actor("op", ActorRole.HUMAN))
            # Simula um banco antigo: troca a barreira por uma versão sem a
            # transição de recuperação.
            first._connection.executescript(
                """
                DROP TRIGGER IF EXISTS forbid_invalid_system_transition;
                CREATE TRIGGER forbid_invalid_system_transition
                BEFORE UPDATE ON system_state
                WHEN NOT (
                    OLD.status <> 'EMERGENCY_STOPPED'
                    AND NEW.status = 'EMERGENCY_STOPPED'
                )
                BEGIN SELECT RAISE(ABORT, 'invalid system transition'); END;
                """
            )
            first._connection.commit()
            first.close()

            reopened = SQLiteStore(database)
            try:
                version = reopened._connection.execute(
                    "SELECT value FROM schema_meta WHERE key = 'guard_schema_version'"
                ).fetchone()
                self.assertEqual(GUARD_SCHEMA_VERSION, version["value"])

                snapshot = StateManager(reopened).clear_emergency_stop(
                    "recuperado após atualização", actor=Actor("op", ActorRole.HUMAN)
                )
                self.assertIs(SystemStatus.STOPPED, snapshot.status)
            finally:
                reopened.close()
