from __future__ import annotations

import io
import json
import sqlite3
import unittest

from ai_trading_lab.errors import (
    InvalidStateTransition,
    PermissionDeniedError,
    PersistenceError,
    PromotionApprovalRequired,
    PromotionRequestError,
)
from ai_trading_lab.logging import configure_structured_logger, log_event
from ai_trading_lab.models import (
    Actor,
    ActorRole,
    AuditEvent,
    PromotionStatus,
    StrategyStateSnapshot,
    StrategyStatus,
    SystemStateSnapshot,
    SystemStatus,
)
from ai_trading_lab.persistence import SQLiteStore
from ai_trading_lab.state import PromotionManager, StateManager, StrategyStateManager


class HighSecurityRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SQLiteStore()
        self.system_states = StateManager(self.store)
        self.strategy_states = StrategyStateManager(self.store)
        self.promotions = PromotionManager(self.store)
        self.supervisor = Actor("supervisor-test", ActorRole.SUPERVISOR)
        self.validator = Actor("validator-test", ActorRole.VALIDATOR)
        self.human = Actor("human-test", ActorRole.HUMAN)
        self.strategy_id = "HYP-HIGH-001"

    def tearDown(self) -> None:
        self.store.close()

    def test_store_cannot_reverse_emergency_stopped(self) -> None:
        self.system_states.transition(SystemStatus.RUNNING, actor=self.supervisor)
        self.system_states.emergency_stop("kill switch", actor=self.human)

        with self.assertRaises(InvalidStateTransition):
            self.store.transition_system_state(
                SystemStatus.EMERGENCY_STOPPED,
                SystemStateSnapshot(SystemStatus.RUNNING),
                AuditEvent("bypass", self.supervisor.actor_id, {}),
                actor=self.supervisor,
            )

        with self.assertRaises(sqlite3.DatabaseError):
            self.store._connection.execute(
                "UPDATE system_state SET status = 'RUNNING' WHERE singleton_id = 1"
            )
        self.store._connection.rollback()

        persisted = self.store.load_system_state()
        self.assertIsNotNone(persisted)
        self.assertEqual(SystemStatus.EMERGENCY_STOPPED, persisted.status)

    def test_store_enforces_strategy_sequence_authorization_and_approval(self) -> None:
        self.strategy_states.initialize(self.strategy_id, actor=self.supervisor)

        with self.assertRaises(PermissionDeniedError):
            self.store.transition_strategy_state(
                StrategyStatus.IDEA,
                StrategyStateSnapshot(self.strategy_id, StrategyStatus.BACKTEST),
                AuditEvent("bypass", self.supervisor.actor_id, {}),
                actor=self.supervisor,
            )

        with self.assertRaises(InvalidStateTransition):
            self.store.transition_strategy_state(
                StrategyStatus.IDEA,
                StrategyStateSnapshot(self.strategy_id, StrategyStatus.REAL),
                AuditEvent("bypass", self.validator.actor_id, {}),
                actor=self.validator,
            )

        self._advance_to_human_review()
        with self.assertRaises(PromotionApprovalRequired):
            self.store.transition_strategy_state(
                StrategyStatus.HUMAN_REVIEW,
                StrategyStateSnapshot(self.strategy_id, StrategyStatus.REAL),
                AuditEvent("bypass", self.validator.actor_id, {}),
                actor=self.validator,
            )

        with self.assertRaises(sqlite3.DatabaseError):
            self.store._connection.execute(
                "UPDATE strategy_state SET status = 'REAL' WHERE strategy_id = ?",
                (self.strategy_id,),
            )
        self.store._connection.rollback()

        state = self.store.load_strategy_state(self.strategy_id)
        self.assertIsNotNone(state)
        self.assertEqual(StrategyStatus.HUMAN_REVIEW, state.status)

    def test_access_token_is_redacted_in_logger_and_audit(self) -> None:
        stream = io.StringIO()
        logger = configure_structured_logger("test.access-token", stream)
        log_event(logger, "access_token=logger-live-secret; event=ok")
        self.assertNotIn("logger-live-secret", stream.getvalue())

        self.store.append_audit_event(
            AuditEvent(
                "token_test",
                "system",
                {"message": "refreshToken=audit-live-secret; event=ok"},
            )
        )
        payload = json.loads(self.store.list_audit_events()[-1]["payload"])
        self.assertNotIn("audit-live-secret", json.dumps(payload))

    def test_emergency_stop_and_audit_roll_back_together(self) -> None:
        self.system_states.transition(SystemStatus.RUNNING, actor=self.supervisor)
        self._fail_audit_for("emergency_stop")

        with self.assertRaises(PersistenceError):
            self.system_states.emergency_stop("kill switch", actor=self.human)

        persisted = self.store.load_system_state()
        self.assertIsNotNone(persisted)
        self.assertEqual(SystemStatus.RUNNING, persisted.status)
        self.assertEqual(SystemStatus.RUNNING, self.system_states.snapshot.status)

    def test_strategy_state_and_audit_roll_back_together(self) -> None:
        self.strategy_states.initialize(self.strategy_id, actor=self.supervisor)
        self._fail_audit_for("strategy_state_changed")

        with self.assertRaises(PersistenceError):
            self.strategy_states.transition(
                self.strategy_id,
                StrategyStatus.BACKTEST,
                actor=self.validator,
            )

        state = self.store.load_strategy_state(self.strategy_id)
        self.assertIsNotNone(state)
        self.assertEqual(StrategyStatus.IDEA, state.status)

    def test_promotion_request_and_audit_roll_back_together(self) -> None:
        self.strategy_states.initialize(self.strategy_id, actor=self.supervisor)
        self._advance_to_human_review()
        self._fail_audit_for("promotion_requested")

        with self.assertRaises((PersistenceError, PromotionRequestError)):
            self.promotions.request(
                "PROMO-HIGH-001",
                self.strategy_id,
                actor=self.supervisor,
            )

        self.assertIsNone(self.store.load_promotion_request("PROMO-HIGH-001"))

    def test_promotion_decision_and_audit_roll_back_together(self) -> None:
        self.strategy_states.initialize(self.strategy_id, actor=self.supervisor)
        self._advance_to_human_review()
        request = self.promotions.request(
            "PROMO-HIGH-001",
            self.strategy_id,
            actor=self.supervisor,
        )
        self._fail_audit_for("promotion_decided")

        with self.assertRaises(PersistenceError):
            self.promotions.decide(
                request.request_id,
                PromotionStatus.APPROVED,
                actor=self.human,
            )

        persisted = self.store.load_promotion_request(request.request_id)
        self.assertIsNotNone(persisted)
        self.assertEqual(PromotionStatus.PENDING, persisted.status)

    def _advance_to_human_review(self) -> None:
        state = self.store.load_strategy_state(self.strategy_id)
        self.assertIsNotNone(state)
        remaining = (
            StrategyStatus.BACKTEST,
            StrategyStatus.VALIDATION,
            StrategyStatus.OUT_OF_SAMPLE,
            StrategyStatus.MONTE_CARLO,
            StrategyStatus.DEMO_CANDIDATE,
            StrategyStatus.DEMO,
            StrategyStatus.HUMAN_REVIEW,
        )
        start = remaining.index(state.status) + 1 if state.status in remaining else 0
        for target in remaining[start:]:
            self.strategy_states.transition(
                self.strategy_id,
                target,
                actor=self.validator,
            )

    def _fail_audit_for(self, event_type: str) -> None:
        trigger_name = f"fail_{event_type}"
        self.store._connection.execute(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE INSERT ON audit_events
            WHEN NEW.event_type = '{event_type}'
            BEGIN SELECT RAISE(ABORT, 'forced audit failure'); END
            """
        )
        self.store._connection.commit()
