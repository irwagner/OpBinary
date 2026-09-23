from __future__ import annotations

import unittest

from ai_trading_lab.metrics import (
    build_equity_curve,
    expectancy,
    max_loss_streak,
    max_win_streak,
    profit,
    profit_pct,
    win_rate,
)


class ExpectancyTests(unittest.TestCase):
    def test_expectancy_uses_payout_not_win_rate_alone(self) -> None:
        # 50% de acerto com payout 0.87 é negativo: acerto alto não valida nada.
        self.assertAlmostEqual(-0.065, expectancy(0.5, 0.87), places=6)

    def test_expectancy_breakeven_point_depends_on_payout(self) -> None:
        payout = 0.87
        breakeven = 1.0 / (1.0 + payout)
        self.assertAlmostEqual(0.0, expectancy(breakeven, payout), places=9)

    def test_expectancy_positive_above_breakeven(self) -> None:
        self.assertGreater(expectancy(0.60, 0.87), 0.0)

    def test_expectancy_rejects_invalid_win_rate(self) -> None:
        with self.assertRaises(ValueError):
            expectancy(1.2, 0.87)

    def test_expectancy_rejects_non_positive_payout(self) -> None:
        with self.assertRaises(ValueError):
            expectancy(0.5, 0.0)


class StreakTests(unittest.TestCase):
    def test_max_loss_streak(self) -> None:
        self.assertEqual(3, max_loss_streak([True, False, False, False, True, False]))

    def test_max_win_streak(self) -> None:
        self.assertEqual(2, max_win_streak([True, True, False, True]))

    def test_streaks_on_empty_sequence(self) -> None:
        self.assertEqual(0, max_loss_streak([]))
        self.assertEqual(0, max_win_streak([]))


class EquityCurveTests(unittest.TestCase):
    def test_curve_grows_on_wins(self) -> None:
        curve = build_equity_curve([True, True], 100.0, 1.0, 0.1)
        self.assertGreater(curve.values[-1], 100.0)
        self.assertFalse(curve.ruined)

    def test_curve_drawdown_measured_from_peak(self) -> None:
        curve = build_equity_curve([True, False, False], 100.0, 1.0, 0.5)
        # 100 -> 150 -> 75 -> 37.5; pico 150, vale 37.5 => 75% de drawdown
        self.assertAlmostEqual(0.75, curve.max_drawdown, places=6)

    def test_curve_never_goes_negative(self) -> None:
        curve = build_equity_curve([False] * 50, 100.0, 0.87, 1.0)
        self.assertGreaterEqual(min(curve.values), 0.0)
        self.assertTrue(curve.ruined)

    def test_profit_and_profit_pct(self) -> None:
        curve = build_equity_curve([True], 100.0, 0.5, 0.2)
        self.assertAlmostEqual(10.0, profit(curve, 100.0), places=6)
        self.assertAlmostEqual(0.1, profit_pct(curve, 100.0), places=6)

    def test_rejects_invalid_inputs(self) -> None:
        with self.assertRaises(ValueError):
            build_equity_curve([True], 0.0, 0.87, 0.02)
        with self.assertRaises(ValueError):
            build_equity_curve([True], 100.0, 0.87, 0.0)
        with self.assertRaises(ValueError):
            build_equity_curve([True], 100.0, 0.0, 0.02)


class WinRateTests(unittest.TestCase):
    def test_win_rate_without_sample_is_zero(self) -> None:
        self.assertEqual(0.0, win_rate(0, 0))

    def test_win_rate_computation(self) -> None:
        self.assertAlmostEqual(0.25, win_rate(1, 4), places=9)
