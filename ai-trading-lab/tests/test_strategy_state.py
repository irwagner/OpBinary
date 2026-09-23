from __future__ import annotations

import json
import unittest

from ai_trading_lab.errors import (
    InvalidStateTransition,
    PermissionDeniedError,
    PromotionApprovalRequired,
    PromotionRequestError,
)
from ai_trading_lab.models import (
    Actor,
    ActorRole,
    PromotionStatus,
    StrategyStatus,
)
from ai_trading_lab.persistence import SQLiteStore
from ai_trading_lab.state import PromotionManager, StrategyStateManager


class StrategyStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SQLiteStore()
        self.states = StrategyStateManager(self.store)
        self.promotions = PromotionManager(self.store)
        self.supervisor = Actor("supervisor-test", ActorRole.SUPERVISOR)
        self.validator = Actor("validator-test", ActorRole.VALIDATOR)
        self.human = Actor("human-test", ActorRole.HUMAN)
        self.strategy_id = "HYP-000001"

    def tearDown(self) -> None:
        self.store.close()

    def test_strategy_cannot_skip_validation_stage(self) -> None:
        self.states.initialize(self.strategy_id, actor=self.supervisor)

        with self.assertRaises(InvalidStateTransition):
            self.states.transition(
                self.strategy_id,
                StrategyStatus.VALIDATION,
                actor=self.validator,
            )

        state = self.store.load_strategy_state(self.strategy_id)
        self.assertIsNotNone(state)
        self.assertEqual(StrategyStatus.IDEA, state.status)

    def test_only_validator_can_transition_strategy(self) -> None:
        self.states.initialize(self.strategy_id, actor=self.supervisor)

        with self.assertRaises(PermissionDeniedError):
            self.states.transition(
                self.strategy_id,
                StrategyStatus.BACKTEST,
                actor=self.supervisor,
            )

        event = self.store.list_audit_events()[-1]
        payload = json.loads(event["payload"])
        self.assertEqual("permission_denied", event["event_type"])
        self.assertEqual("TRANSITION_STRATEGY", payload["capability"])

    def test_real_state_requires_persisted_human_approval(self) -> None:
        self._advance_to_human_review()

        with self.assertRaises(PromotionApprovalRequired):
            self.states.transition(
                self.strategy_id,
                StrategyStatus.REAL,
                actor=self.validator,
            )

        request = self.promotions.request(
            "PROMO-000001",
            self.strategy_id,
            actor=self.supervisor,
        )
        self.assertEqual(PromotionStatus.PENDING, request.status)

        with self.assertRaises(PermissionDeniedError):
            self.promotions.decide(
                request.request_id,
                PromotionStatus.APPROVED,
                actor=self.validator,
            )

        approved = self.promotions.decide(
            request.request_id,
            PromotionStatus.APPROVED,
            actor=self.human,
            reason="explicit human approval",
        )
        self.assertEqual(PromotionStatus.APPROVED, approved.status)
        self.assertEqual(self.human.actor_id, approved.decided_by)

        real_state = self.states.transition(
            self.strategy_id,
            StrategyStatus.REAL,
            actor=self.validator,
        )
        self.assertEqual(StrategyStatus.REAL, real_state.status)

    def test_promotion_cannot_be_requested_before_human_review(self) -> None:
        self.states.initialize(self.strategy_id, actor=self.supervisor)

        with self.assertRaises(PromotionRequestError):
            self.promotions.request(
                "PROMO-000001",
                self.strategy_id,
                actor=self.supervisor,
            )

    def test_rejected_strategy_cannot_reenter_pipeline(self) -> None:
        self.states.initialize(self.strategy_id, actor=self.supervisor)
        self.states.transition(
            self.strategy_id,
            StrategyStatus.REJECTED,
            actor=self.validator,
            reason="validation failure",
        )

        with self.assertRaises(InvalidStateTransition):
            self.states.transition(
                self.strategy_id,
                StrategyStatus.BACKTEST,
                actor=self.validator,
            )

    def _advance_to_human_review(self) -> None:
        self.states.initialize(self.strategy_id, actor=self.supervisor)
        for status in (
            StrategyStatus.BACKTEST,
            StrategyStatus.VALIDATION,
            StrategyStatus.OUT_OF_SAMPLE,
            StrategyStatus.MONTE_CARLO,
            StrategyStatus.DEMO_CANDIDATE,
            StrategyStatus.DEMO,
            StrategyStatus.HUMAN_REVIEW,
        ):
            self.states.transition(
                self.strategy_id,
                status,
                actor=self.validator,
            )
