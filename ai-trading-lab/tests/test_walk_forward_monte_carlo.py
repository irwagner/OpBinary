from __future__ import annotations

import unittest

from ai_trading_lab.backtest_engine import run_backtest
from ai_trading_lab.errors import DataQualityError
from ai_trading_lab.monte_carlo import run_monte_carlo
from ai_trading_lab.strategy import StrategyRule
from ai_trading_lab.walk_forward import run_walk_forward
from tests.fixtures import monotonic_series, mixed_walk_series


class WalkForwardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rule = StrategyRule(lookback=2, threshold=0.0005, expiry_periods=1)
        self.scenarios = (100,)

    def test_produces_requested_number_of_folds(self) -> None:
        result = run_walk_forward(
            monotonic_series(200),
            self.rule,
            folds=5,
            payout=0.87,
            capital_scenarios=self.scenarios,
            risk_per_trade=0.02,
        )

        self.assertEqual(5, len(result.folds))
        self.assertEqual([0, 1, 2, 3, 4], [fold.fold_index for fold in result.folds])

    def test_fold_pass_ratio_is_one_when_all_folds_positive(self) -> None:
        result = run_walk_forward(
            monotonic_series(200),
            self.rule,
            folds=4,
            payout=0.87,
            capital_scenarios=self.scenarios,
            risk_per_trade=0.02,
        )

        self.assertEqual(1.0, result.fold_pass_ratio)
        self.assertTrue(result.all_folds_positive)

    def test_fold_pass_ratio_below_one_blocks_all_folds_positive(self) -> None:
        result = run_walk_forward(
            mixed_walk_series(200),
            self.rule,
            folds=4,
            payout=0.87,
            capital_scenarios=self.scenarios,
            risk_per_trade=0.02,
        )

        self.assertLessEqual(result.fold_pass_ratio, 1.0)
        if result.fold_pass_ratio < 1.0:
            self.assertFalse(result.all_folds_positive)

    def test_requires_at_least_two_folds(self) -> None:
        with self.assertRaises(ValueError):
            run_walk_forward(
                monotonic_series(100),
                self.rule,
                folds=1,
                payout=0.87,
                capital_scenarios=self.scenarios,
                risk_per_trade=0.02,
            )

    def test_rejects_insufficient_sample(self) -> None:
        with self.assertRaises(DataQualityError):
            run_walk_forward(
                monotonic_series(10),
                self.rule,
                folds=5,
                payout=0.87,
                capital_scenarios=self.scenarios,
                risk_per_trade=0.02,
            )

    def test_walk_forward_is_deterministic(self) -> None:
        points = mixed_walk_series(200)
        kwargs = {
            "folds": 4,
            "payout": 0.87,
            "capital_scenarios": self.scenarios,
            "risk_per_trade": 0.02,
        }
        first = run_walk_forward(points, self.rule, **kwargs)
        second = run_walk_forward(points, self.rule, **kwargs)

        self.assertEqual(
            [fold.expectancy for fold in first.folds],
            [fold.expectancy for fold in second.folds],
        )


class MonteCarloTests(unittest.TestCase):
    def setUp(self) -> None:
        points = mixed_walk_series(120)
        rule = StrategyRule(lookback=2, threshold=0.0005, expiry_periods=1)
        self.backtest = run_backtest(
            points, rule, payout=0.87, capital_scenarios=(100,), risk_per_trade=0.02
        )

    def test_same_seed_produces_identical_result(self) -> None:
        kwargs = {
            "runs": 50,
            "initial_capital": 100.0,
            "payout": 0.87,
            "risk_per_trade": 0.02,
            "seed": 42,
        }
        first = run_monte_carlo(self.backtest.outcomes, **kwargs)
        second = run_monte_carlo(self.backtest.outcomes, **kwargs)

        self.assertEqual(first.mean_final_capital, second.mean_final_capital)
        self.assertEqual(first.ruin_probability, second.ruin_probability)
        self.assertEqual(first.worst_loss_streak, second.worst_loss_streak)

    def test_different_seed_is_allowed_to_differ(self) -> None:
        base = {
            "runs": 50,
            "initial_capital": 100.0,
            "payout": 0.87,
            "risk_per_trade": 0.02,
        }
        first = run_monte_carlo(self.backtest.outcomes, seed=1, **base)
        second = run_monte_carlo(self.backtest.outcomes, seed=2, **base)

        self.assertEqual(first.runs, second.runs)
        self.assertEqual(first.seed, 1)
        self.assertEqual(second.seed, 2)

    def test_probabilities_are_within_bounds(self) -> None:
        result = run_monte_carlo(
            self.backtest.outcomes,
            runs=100,
            initial_capital=100.0,
            payout=0.87,
            risk_per_trade=0.02,
        )

        self.assertGreaterEqual(result.ruin_probability, 0.0)
        self.assertLessEqual(result.ruin_probability, 1.0)
        self.assertGreaterEqual(result.loss_probability, 0.0)
        self.assertLessEqual(result.loss_probability, 1.0)
        self.assertLessEqual(result.p05_final_capital, result.p95_final_capital)

    def test_all_losses_guarantees_ruin(self) -> None:
        result = run_monte_carlo(
            tuple([False] * 40),
            runs=10,
            initial_capital=100.0,
            payout=0.87,
            risk_per_trade=1.0,
        )

        self.assertEqual(1.0, result.ruin_probability)

    def test_rejects_empty_outcomes(self) -> None:
        with self.assertRaises(DataQualityError):
            run_monte_carlo(
                (), runs=10, initial_capital=100.0, payout=0.87, risk_per_trade=0.02
            )

    def test_rejects_zero_runs(self) -> None:
        with self.assertRaises(ValueError):
            run_monte_carlo(
                self.backtest.outcomes,
                runs=0,
                initial_capital=100.0,
                payout=0.87,
                risk_per_trade=0.02,
            )


class FractionalBettingScaleInvarianceTests(unittest.TestCase):
    """Aposta fracionária torna drawdown relativo e ruína independentes do capital.

    Isso justifica calcular Monte Carlo uma única vez por estratégia em vez de
    uma vez por cenário de capital.
    """

    def setUp(self) -> None:
        points = mixed_walk_series(150)
        rule = StrategyRule(lookback=2, threshold=0.0005, expiry_periods=1)
        self.outcomes = run_backtest(
            points, rule, payout=0.89, capital_scenarios=(100,), risk_per_trade=0.02
        ).outcomes

    def test_ruin_probability_is_scale_invariant(self) -> None:
        base = {
            "runs": 60,
            "payout": 0.89,
            "risk_per_trade": 0.02,
            "seed": 99,
        }
        pequeno = run_monte_carlo(self.outcomes, initial_capital=100.0, **base)
        grande = run_monte_carlo(self.outcomes, initial_capital=1000.0, **base)

        self.assertEqual(pequeno.ruin_probability, grande.ruin_probability)
        self.assertAlmostEqual(
            pequeno.mean_max_drawdown, grande.mean_max_drawdown, places=9
        )
        self.assertAlmostEqual(
            pequeno.worst_max_drawdown, grande.worst_max_drawdown, places=9
        )

    def test_final_capital_scales_proportionally(self) -> None:
        base = {
            "runs": 60,
            "payout": 0.89,
            "risk_per_trade": 0.02,
            "seed": 99,
        }
        pequeno = run_monte_carlo(self.outcomes, initial_capital=100.0, **base)
        grande = run_monte_carlo(self.outcomes, initial_capital=1000.0, **base)

        self.assertAlmostEqual(
            pequeno.mean_final_capital * 10.0, grande.mean_final_capital, places=6
        )
