from __future__ import annotations

import unittest
from dataclasses import replace

from ai_trading_lab.agents.adversarial import (
    AdversarialAgent,
    find_duplicate_timestamps,
    verify_no_look_ahead,
)
from ai_trading_lab.agents.backtester import BacktesterAgent
from ai_trading_lab.agents.broker_risk import (
    BrokerRiskAgent,
    IntelligenceItem,
    NullIntelligenceSource,
)
from ai_trading_lab.agents.quant import QuantAgent
from ai_trading_lab.agents.researcher import ResearcherAgent, signature_of
from ai_trading_lab.agents.risk import RiskAgent
from ai_trading_lab.agents.statistician import StatisticianAgent
from ai_trading_lab.agents.supervisor import SupervisorAgent
from ai_trading_lab.backtest_engine import run_backtest
from ai_trading_lab.configuration import RiskConfig
from ai_trading_lab.contracts import (
    DatasetReference,
    Hypothesis,
    PermissionRequest,
    TaskType,
    Verdict,
)
from ai_trading_lab.errors import DataQualityError
from ai_trading_lab.models import StrategyStatus, SystemStatus
from ai_trading_lab.strategy import StrategyRule
from tests.fixtures import monotonic_series, series_from_prices, mixed_walk_series


def _dataset(payout: float = 0.87) -> DatasetReference:
    return DatasetReference(
        dataset_id="DATA-TEST",
        version=1,
        content_hash="hash",
        broker="TestBroker",
        asset="TESTPAIR",
        timeframe="M1",
        point_count=200,
        payout=payout,
    )


class SupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.supervisor = SupervisorAgent()

    def test_grants_permission_for_allowed_task(self) -> None:
        decision = self.supervisor.request_permission(
            PermissionRequest("backtester", TaskType.RUN_BACKTEST, strategy_id="HYP-000001"),
            system_status=SystemStatus.RUNNING,
            strategy_status=StrategyStatus.IDEA,
        )

        self.assertTrue(decision.granted)

    def test_denies_task_outside_agent_allowlist(self) -> None:
        decision = self.supervisor.request_permission(
            PermissionRequest("researcher", TaskType.DECIDE_VALIDATION),
            system_status=SystemStatus.RUNNING,
        )

        self.assertFalse(decision.granted)
        self.assertIn("não pode executar", decision.reason)

    def test_denies_everything_when_emergency_stopped(self) -> None:
        decision = self.supervisor.request_permission(
            PermissionRequest("backtester", TaskType.RUN_BACKTEST, strategy_id="HYP-000001"),
            system_status=SystemStatus.EMERGENCY_STOPPED,
            strategy_status=StrategyStatus.IDEA,
        )

        self.assertFalse(decision.granted)
        self.assertIn("EMERGENCY_STOPPED", decision.reason)

    def test_denies_when_strategy_state_is_wrong(self) -> None:
        decision = self.supervisor.request_permission(
            PermissionRequest("statistician", TaskType.RUN_STATISTICS, strategy_id="HYP-000001"),
            system_status=SystemStatus.RUNNING,
            strategy_status=StrategyStatus.IDEA,
        )

        self.assertFalse(decision.granted)

    def test_denies_rejected_strategy(self) -> None:
        decision = self.supervisor.request_permission(
            PermissionRequest("backtester", TaskType.RUN_BACKTEST, strategy_id="HYP-000001"),
            system_status=SystemStatus.RUNNING,
            strategy_status=StrategyStatus.REJECTED,
        )

        self.assertFalse(decision.granted)


class ResearcherAndQuantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.researcher = ResearcherAgent()
        self.quant = QuantAgent()

    def test_generates_requested_number_of_hypotheses(self) -> None:
        hypotheses = self.researcher.generate("TESTPAIR", "M1", limit=5)

        self.assertEqual(5, len(hypotheses))
        self.assertEqual(5, len({item.strategy_id for item in hypotheses}))

    def test_generation_is_deterministic(self) -> None:
        first = ResearcherAgent().generate("TESTPAIR", "M1", limit=4)
        second = ResearcherAgent().generate("TESTPAIR", "M1", limit=4)

        self.assertEqual(
            [dict(item.parameters) for item in first],
            [dict(item.parameters) for item in second],
        )

    def test_excluded_signature_is_not_regenerated(self) -> None:
        first = self.researcher.generate("TESTPAIR", "M1", limit=1)
        excluded = signature_of(dict(first[0].parameters))

        again = ResearcherAgent().generate(
            "TESTPAIR", "M1", limit=1, exclude=frozenset({excluded})
        )

        self.assertNotEqual(dict(first[0].parameters), dict(again[0].parameters))

    def test_quant_formalizes_valid_hypothesis(self) -> None:
        hypothesis = self.researcher.generate("TESTPAIR", "M1", limit=1)[0]

        strategy = self.quant.formalize(hypothesis)

        self.assertTrue(strategy.reproducible)
        self.assertIsNotNone(strategy.rule)

    def test_quant_rejects_vague_condition(self) -> None:
        hypothesis = Hypothesis(
            strategy_id="HYP-000001",
            asset="TESTPAIR",
            timeframe="M1",
            entry_conditions=("quando o mercado estiver forte",),
            exit_rule="expira_em_1_periodos",
            filters=(),
            parameters={"lookback": 2, "threshold": 0.001, "expiry_periods": 1, "mode": "FOLLOW"},
        )

        strategy = self.quant.formalize(hypothesis)

        self.assertFalse(strategy.reproducible)
        self.assertIsNone(strategy.rule)
        self.assertIn("não mensurável", strategy.rejection_reason or "")

    def test_quant_rejects_missing_parameters(self) -> None:
        hypothesis = Hypothesis(
            strategy_id="HYP-000002",
            asset="TESTPAIR",
            timeframe="M1",
            entry_conditions=("momentum_abs_over_2_periods >= 0.001",),
            exit_rule="expira_em_1_periodos",
            filters=(),
            parameters={"lookback": 2},
        )

        strategy = self.quant.formalize(hypothesis)

        self.assertFalse(strategy.reproducible)
        self.assertIn("ausentes", strategy.rejection_reason or "")


class BacktesterAgentTests(unittest.TestCase):
    def test_refuses_non_reproducible_strategy(self) -> None:
        agent = BacktesterAgent()
        strategy = QuantAgent().formalize(
            Hypothesis(
                strategy_id="HYP-000003",
                asset="TESTPAIR",
                timeframe="M1",
                entry_conditions=("mercado forte",),
                exit_rule="x",
                filters=(),
                parameters={},
            )
        )

        with self.assertRaises(DataQualityError):
            agent.run(
                strategy,
                monotonic_series(50),
                _dataset(),
                experiment_id="EXP-000001",
                capital_scenarios=(100,),
                risk_per_trade=0.02,
            )

    def test_refuses_non_positive_payout(self) -> None:
        agent = BacktesterAgent()
        strategy = QuantAgent().formalize(
            ResearcherAgent().generate("TESTPAIR", "M1", limit=1)[0]
        )

        with self.assertRaises(DataQualityError):
            agent.run(
                strategy,
                monotonic_series(50),
                _dataset(payout=0.0),
                experiment_id="EXP-000001",
                capital_scenarios=(100,),
                risk_per_trade=0.02,
            )


class AdversarialTests(unittest.TestCase):
    def test_look_ahead_verification_passes_for_engine_rule(self) -> None:
        rule = StrategyRule(lookback=3, threshold=0.0005, expiry_periods=2)
        self.assertTrue(verify_no_look_ahead(mixed_walk_series(120), rule))

    def test_detects_duplicate_timestamps(self) -> None:
        points = series_from_prices((1.0, 1.1, 1.2))
        duplicated = (*points, points[1])

        self.assertEqual(1, find_duplicate_timestamps(duplicated))

    def test_flags_overfitting_when_sample_is_small(self) -> None:
        points = mixed_walk_series(60)
        rule = StrategyRule(lookback=2, threshold=0.0005, expiry_periods=1)
        strategy = QuantAgent().formalize(
            Hypothesis(
                strategy_id="HYP-000004",
                asset="TESTPAIR",
                timeframe="M1",
                entry_conditions=("momentum",),
                exit_rule="expira",
                filters=(),
                parameters=rule.as_dict(),
            )
        )
        backtest = run_backtest(
            points, rule, payout=0.87, capital_scenarios=(100,), risk_per_trade=0.02
        )
        statistics = StatisticianAgent().analyze(
            strategy,
            points,
            _dataset(),
            backtest,
            experiment_id="EXP-000002",
            walk_forward_folds=3,
            monte_carlo_runs=20,
            capital_scenarios=(100,),
            risk_per_trade=0.02,
        )

        verdict = AdversarialAgent().challenge(
            strategy, points, statistics, experiment_id="EXP-000002"
        )

        self.assertIn(verdict.verdict, {Verdict.WARN, Verdict.FAIL})
        self.assertTrue(verdict.findings)


class BrokerRiskTests(unittest.TestCase):
    def test_fails_closed_without_intelligence_source(self) -> None:
        agent = BrokerRiskAgent(source=NullIntelligenceSource())

        report = agent.evaluate("Polarium Broker")

        self.assertIs(Verdict.FAIL, report.status)
        self.assertTrue(report.basis_risk)
        self.assertEqual((), report.sources)

    def test_basis_risk_is_always_flagged(self) -> None:
        report = BrokerRiskAgent().evaluate("DayProfit")
        self.assertTrue(report.basis_risk)

    def test_discards_evidence_without_source_url(self) -> None:
        class SourceWithoutUrl:
            def gather(self, broker_name: str) -> tuple[IntelligenceItem, ...]:
                return (
                    IntelligenceItem("regulatory", "sem fonte", "", Verdict.PASS),
                )

        report = BrokerRiskAgent(source=SourceWithoutUrl()).evaluate("Polarium Broker")

        self.assertIs(Verdict.FAIL, report.status)
        self.assertEqual((), report.sources)

    def test_passes_only_with_complete_evidence(self) -> None:
        class CompleteSource:
            def gather(self, broker_name: str) -> tuple[IntelligenceItem, ...]:
                return tuple(
                    IntelligenceItem(
                        category,
                        f"evidência para {category}",
                        f"https://example.test/{category}",
                        Verdict.PASS,
                    )
                    for category in (
                        "regulatory",
                        "complaints",
                        "withdrawal_pattern",
                        "pricing_transparency",
                        "demo_availability",
                        "historical_data_availability",
                    )
                )

        report = BrokerRiskAgent(source=CompleteSource()).evaluate("Polarium Broker")

        self.assertIs(Verdict.PASS, report.status)
        self.assertEqual(6, len(report.sources))
        self.assertIsNotNone(report.next_review_due)

    def test_detects_regression_from_pass_to_fail(self) -> None:
        agent = BrokerRiskAgent(source=NullIntelligenceSource())
        report = agent.evaluate("Polarium Broker", previous_status=Verdict.PASS)

        self.assertTrue(agent.detect_regression(report))

    def test_no_regression_when_previous_was_not_pass(self) -> None:
        agent = BrokerRiskAgent(source=NullIntelligenceSource())
        report = agent.evaluate("Polarium Broker", previous_status=Verdict.WARN)

        self.assertFalse(agent.detect_regression(report))


class RiskAgentTests(unittest.TestCase):
    def test_fails_when_capital_is_depleted(self) -> None:
        rule = StrategyRule(lookback=2, threshold=0.0, expiry_periods=1)
        backtest = run_backtest(
            monotonic_series(60), rule, payout=0.87, capital_scenarios=(100,), risk_per_trade=0.02
        )
        depleted = replace(backtest, outcomes=tuple([False] * 30), max_loss_streak=30)

        report = RiskAgent().assess(
            depleted,
            RiskConfig(risk_per_trade=0.02, max_drawdown_limit=0.30, max_risk_of_ruin=0.05),
            experiment_id="EXP-000003",
            strategy_id="HYP-000005",
            monte_carlo_runs=20,
        )

        self.assertIs(Verdict.FAIL, report.verdict)

    def test_rejects_backtest_without_outcomes(self) -> None:
        rule = StrategyRule(lookback=2, threshold=10.0, expiry_periods=1)
        backtest = run_backtest(
            monotonic_series(40), rule, payout=0.87, capital_scenarios=(100,), risk_per_trade=0.02
        )

        with self.assertRaises(DataQualityError):
            RiskAgent().assess(
                backtest,
                RiskConfig(),
                experiment_id="EXP-000004",
                strategy_id="HYP-000006",
                monte_carlo_runs=10,
            )
