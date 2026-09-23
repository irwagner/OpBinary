from __future__ import annotations

import unittest

from ai_trading_lab.backtest_engine import TradeOutcome, resolve_trade, run_backtest
from ai_trading_lab.errors import DataQualityError
from ai_trading_lab.strategy import (
    RuleMode,
    Signal,
    SignalDirection,
    StrategyRule,
    evaluate_at,
    generate_signals,
)
from tests.fixtures import monotonic_series, series_from_prices, mixed_walk_series


class LookAheadBarrierTests(unittest.TestCase):
    def test_signal_is_identical_when_series_is_truncated_at_decision(self) -> None:
        points = monotonic_series(60)
        rule = StrategyRule(lookback=3, threshold=0.0001, expiry_periods=2)

        for signal in generate_signals(points, rule):
            truncated = points[: signal.index + 1]
            replayed = evaluate_at(truncated, len(truncated) - 1, rule)
            self.assertIs(
                signal.direction,
                replayed,
                msg=f"sinal divergiu ao truncar a série no índice {signal.index}",
            )

    def test_evaluate_at_cannot_read_beyond_index(self) -> None:
        points = monotonic_series(20)
        rule = StrategyRule(lookback=2, threshold=0.0, expiry_periods=1)

        with self.assertRaises(IndexError):
            evaluate_at(points, len(points), rule)

    def test_no_signal_before_lookback_is_available(self) -> None:
        points = monotonic_series(10)
        rule = StrategyRule(lookback=5, threshold=0.0, expiry_periods=1)

        self.assertIsNone(evaluate_at(points, 4, rule))

    def test_signals_never_generated_without_resolvable_expiry(self) -> None:
        points = monotonic_series(20)
        rule = StrategyRule(lookback=2, threshold=0.0, expiry_periods=4)

        signals = generate_signals(points, rule)

        self.assertTrue(signals)
        for signal in signals:
            self.assertLess(signal.index + rule.expiry_periods, len(points))


class RuleSemanticsTests(unittest.TestCase):
    def test_follow_mode_calls_on_rising_momentum(self) -> None:
        points = series_from_prices((1.0, 1.0, 1.1))
        rule = StrategyRule(lookback=2, threshold=0.01, expiry_periods=1)

        self.assertIs(SignalDirection.CALL, evaluate_at(points, 2, rule))

    def test_revert_mode_inverts_direction(self) -> None:
        points = series_from_prices((1.0, 1.0, 1.1))
        rule = StrategyRule(lookback=2, threshold=0.01, expiry_periods=1, mode=RuleMode.REVERT)

        self.assertIs(SignalDirection.PUT, evaluate_at(points, 2, rule))

    def test_threshold_suppresses_weak_momentum(self) -> None:
        points = series_from_prices((1.0, 1.0, 1.0001))
        rule = StrategyRule(lookback=2, threshold=0.01, expiry_periods=1)

        self.assertIsNone(evaluate_at(points, 2, rule))

    def test_rule_rejects_invalid_parameters(self) -> None:
        with self.assertRaises(ValueError):
            StrategyRule(lookback=0, threshold=0.01, expiry_periods=1)
        with self.assertRaises(ValueError):
            StrategyRule(lookback=2, threshold=0.01, expiry_periods=0)
        with self.assertRaises(ValueError):
            StrategyRule(lookback=2, threshold=-0.01, expiry_periods=1)


class TradeResolutionTests(unittest.TestCase):
    def test_call_wins_when_price_rises(self) -> None:
        points = series_from_prices((1.0, 1.2))
        trade = resolve_trade(points, Signal(0, points[0].timestamp, SignalDirection.CALL), 1)

        self.assertIs(TradeOutcome.WIN, trade.outcome)

    def test_put_wins_when_price_falls(self) -> None:
        points = series_from_prices((1.2, 1.0))
        trade = resolve_trade(points, Signal(0, points[0].timestamp, SignalDirection.PUT), 1)

        self.assertIs(TradeOutcome.WIN, trade.outcome)

    def test_tie_is_treated_as_loss(self) -> None:
        points = series_from_prices((1.0, 1.0))
        trade = resolve_trade(points, Signal(0, points[0].timestamp, SignalDirection.CALL), 1)

        self.assertIs(TradeOutcome.LOSS, trade.outcome)

    def test_resolution_beyond_series_is_rejected(self) -> None:
        points = series_from_prices((1.0, 1.1))
        with self.assertRaises(DataQualityError):
            resolve_trade(points, Signal(1, points[1].timestamp, SignalDirection.CALL), 1)


class RunBacktestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rule = StrategyRule(lookback=2, threshold=0.0005, expiry_periods=1)
        self.scenarios = (100, 500)

    def test_backtest_is_deterministic(self) -> None:
        points = mixed_walk_series(80)
        first = run_backtest(
            points, self.rule, payout=0.87, capital_scenarios=self.scenarios, risk_per_trade=0.02
        )
        second = run_backtest(
            points, self.rule, payout=0.87, capital_scenarios=self.scenarios, risk_per_trade=0.02
        )

        self.assertEqual(first.trades, second.trades)
        self.assertEqual(first.wins, second.wins)
        self.assertEqual(first.expectancy, second.expectancy)
        self.assertEqual(first.outcomes, second.outcomes)

    def test_wins_and_losses_add_up_to_trades(self) -> None:
        points = mixed_walk_series(80)
        result = run_backtest(
            points, self.rule, payout=0.87, capital_scenarios=self.scenarios, risk_per_trade=0.02
        )

        self.assertEqual(result.trades, result.wins + result.losses)

    def test_one_scenario_per_capital_value(self) -> None:
        points = monotonic_series(60)
        result = run_backtest(
            points,
            self.rule,
            payout=0.87,
            capital_scenarios=(100, 300, 500),
            risk_per_trade=0.02,
        )

        self.assertEqual(3, len(result.scenarios))
        self.assertEqual(
            [100.0, 300.0, 500.0],
            [scenario.initial_capital for scenario in result.scenarios],
        )

    def test_payout_must_come_from_caller(self) -> None:
        points = monotonic_series(30)
        with self.assertRaises(ValueError):
            run_backtest(
                points,
                self.rule,
                payout=0.0,
                capital_scenarios=self.scenarios,
                risk_per_trade=0.02,
            )

    def test_empty_series_is_rejected(self) -> None:
        with self.assertRaises(DataQualityError):
            run_backtest(
                (), self.rule, payout=0.87, capital_scenarios=self.scenarios, risk_per_trade=0.02
            )

    def test_out_of_order_series_is_rejected(self) -> None:
        points = list(monotonic_series(30))
        points[5], points[6] = points[6], points[5]
        with self.assertRaises(DataQualityError):
            run_backtest(
                tuple(points),
                self.rule,
                payout=0.87,
                capital_scenarios=self.scenarios,
                risk_per_trade=0.02,
            )

    def test_monotonic_series_with_call_bias_has_no_losses(self) -> None:
        # Verificação de mecânica contábil: série estritamente crescente e
        # regra FOLLOW resolve toda operação CALL como vitória.
        points = monotonic_series(60)
        result = run_backtest(
            points, self.rule, payout=0.87, capital_scenarios=self.scenarios, risk_per_trade=0.02
        )

        self.assertGreater(result.trades, 0)
        self.assertEqual(0, result.losses)
        self.assertEqual(0, result.max_loss_streak)
