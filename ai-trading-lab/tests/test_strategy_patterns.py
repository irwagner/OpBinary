from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from ai_trading_lab.agents.researcher import (
    ResearcherAgent,
    build_search_space,
    required_expectancy_margin,
    signature_of,
    signature_of_rule,
)
from ai_trading_lab.data_models import ValidatedPricePoint
from ai_trading_lab.strategy import (
    CandleColor,
    RuleMode,
    SignalDirection,
    SignalSource,
    StrategyRule,
    candle_color,
    evaluate_at,
    generate_signals,
)
from tests.fixtures import mixed_walk_series


def _ohlc_series(
    candles: tuple[tuple[float, float, float, float], ...],
    *,
    start_hour: int = 12,
) -> tuple[ValidatedPricePoint, ...]:
    """Série com OHLC explícito: (open, high, low, close)."""
    origin = datetime(2026, 1, 1, start_hour, tzinfo=UTC)
    return tuple(
        ValidatedPricePoint(
            broker="TestBroker",
            asset="TESTPAIR",
            timeframe="M1",
            timestamp=origin + timedelta(minutes=index),
            price=close,
            source="test_fixture",
            open=open_,
            high=high,
            low=low,
        )
        for index, (open_, high, low, close) in enumerate(candles)
    )


def _colored(colors: str, *, start_hour: int = 12) -> tuple[ValidatedPricePoint, ...]:
    """Constrói velas com cores declaradas: 'u' alta, 'd' baixa, 'x' doji."""
    candles = []
    for letter in colors:
        if letter == "u":
            candles.append((1.0, 1.2, 0.9, 1.1))
        elif letter == "d":
            candles.append((1.1, 1.2, 0.9, 1.0))
        else:
            candles.append((1.0, 1.2, 0.9, 1.0))
    return _ohlc_series(tuple(candles), start_hour=start_hour)


class CandleColorTests(unittest.TestCase):
    def test_color_from_open_close(self) -> None:
        points = _colored("ud x".replace(" ", ""))

        self.assertIs(CandleColor.UP, candle_color(points, 0))
        self.assertIs(CandleColor.DOWN, candle_color(points, 1))
        self.assertIs(CandleColor.DOJI, candle_color(points, 2))

    def test_color_falls_back_to_previous_close_without_ohlc(self) -> None:
        origin = datetime(2026, 1, 1, 12, tzinfo=UTC)
        points = tuple(
            ValidatedPricePoint(
                broker="TestBroker",
                asset="TESTPAIR",
                timeframe="M1",
                timestamp=origin + timedelta(minutes=index),
                price=price,
                source="test_fixture",
            )
            for index, price in enumerate((1.0, 1.1, 1.05))
        )

        self.assertIs(CandleColor.DOJI, candle_color(points, 0))
        self.assertIs(CandleColor.UP, candle_color(points, 1))
        self.assertIs(CandleColor.DOWN, candle_color(points, 2))

    def test_rejects_index_out_of_range(self) -> None:
        with self.assertRaises(IndexError):
            candle_color(_colored("uu"), 5)


class StreakRuleTests(unittest.TestCase):
    def _streak_rule(self, length: int, mode: RuleMode = RuleMode.FOLLOW) -> StrategyRule:
        return StrategyRule(
            lookback=1,
            threshold=0.0,
            expiry_periods=1,
            mode=mode,
            signal_source=SignalSource.STREAK,
            streak_length=length,
        )

    def test_signals_after_required_streak(self) -> None:
        # minimum_history exige uma vela extra além da sequência exigida.
        points = _colored("duuu")

        self.assertIs(SignalDirection.CALL, evaluate_at(points, 3, self._streak_rule(3)))

    def test_no_signal_before_required_streak(self) -> None:
        points = _colored("dduu")

        self.assertIsNone(evaluate_at(points, 3, self._streak_rule(3)))

    def test_revert_mode_bets_against_the_streak(self) -> None:
        points = _colored("duuu")

        self.assertIs(
            SignalDirection.PUT,
            evaluate_at(points, 3, self._streak_rule(3, RuleMode.REVERT)),
        )

    def test_down_streak_signals_put_in_follow_mode(self) -> None:
        points = _colored("uddd")

        self.assertIs(SignalDirection.PUT, evaluate_at(points, 3, self._streak_rule(3)))

    def test_doji_breaks_the_streak(self) -> None:
        points = _colored("uuux")

        self.assertIsNone(evaluate_at(points, 3, self._streak_rule(2)))


class AlternationRuleTests(unittest.TestCase):
    def _alternation_rule(self, mode: RuleMode = RuleMode.FOLLOW) -> StrategyRule:
        return StrategyRule(
            lookback=4,
            threshold=0.0,
            expiry_periods=1,
            mode=mode,
            signal_source=SignalSource.ALTERNATION,
        )

    def test_signals_when_colors_strictly_alternate(self) -> None:
        # 5 velas: minimum_history é lookback + 1.
        points = _colored("dudud")

        # Última vela é baixa; a continuação da alternância prevê alta.
        self.assertIs(SignalDirection.CALL, evaluate_at(points, 4, self._alternation_rule()))

    def test_no_signal_when_alternation_breaks(self) -> None:
        points = _colored("duduu")

        self.assertIsNone(evaluate_at(points, 4, self._alternation_rule()))

    def test_revert_mode_inverts_expectation(self) -> None:
        points = _colored("dudud")

        self.assertIs(
            SignalDirection.PUT,
            evaluate_at(points, 4, self._alternation_rule(RuleMode.REVERT)),
        )

    def test_alternation_requires_lookback_of_two(self) -> None:
        with self.assertRaises(ValueError):
            StrategyRule(
                lookback=1,
                threshold=0.0,
                expiry_periods=1,
                signal_source=SignalSource.ALTERNATION,
            )


class BodyRatioRuleTests(unittest.TestCase):
    def test_signals_on_large_body(self) -> None:
        points = _ohlc_series((((1.0, 1.10, 1.00, 1.10)),))
        rule = StrategyRule(
            lookback=1,
            threshold=0.9,
            expiry_periods=1,
            signal_source=SignalSource.BODY_RATIO,
        )

        self.assertIs(SignalDirection.CALL, evaluate_at(points, 0, rule))

    def test_no_signal_on_small_body(self) -> None:
        points = _ohlc_series((((1.0, 1.20, 0.80, 1.01)),))
        rule = StrategyRule(
            lookback=1,
            threshold=0.9,
            expiry_periods=1,
            signal_source=SignalSource.BODY_RATIO,
        )

        self.assertIsNone(evaluate_at(points, 0, rule))

    def test_no_signal_without_ohlc(self) -> None:
        points = mixed_walk_series(20)
        rule = StrategyRule(
            lookback=1,
            threshold=0.5,
            expiry_periods=1,
            signal_source=SignalSource.BODY_RATIO,
        )

        self.assertIsNone(evaluate_at(points, 10, rule))


class HourWindowTests(unittest.TestCase):
    def _windowed_rule(self, window: tuple[int, int]) -> StrategyRule:
        return StrategyRule(
            lookback=1,
            threshold=0.0,
            expiry_periods=1,
            signal_source=SignalSource.STREAK,
            streak_length=3,
            hour_window=window,
        )

    def test_signal_suppressed_outside_window(self) -> None:
        points = _colored("duuu", start_hour=3)

        self.assertIsNone(evaluate_at(points, 3, self._windowed_rule((12, 17))))

    def test_signal_allowed_inside_window(self) -> None:
        points = _colored("duuu", start_hour=13)

        self.assertIs(
            SignalDirection.CALL, evaluate_at(points, 3, self._windowed_rule((12, 17)))
        )

    def test_window_crossing_midnight(self) -> None:
        rule = self._windowed_rule((22, 3))

        self.assertIs(
            SignalDirection.CALL,
            evaluate_at(_colored("duuu", start_hour=23), 3, rule),
        )
        self.assertIsNone(evaluate_at(_colored("duuu", start_hour=10), 3, rule))

    def test_rejects_invalid_hour(self) -> None:
        with self.assertRaises(ValueError):
            StrategyRule(
                lookback=1, threshold=0.0, expiry_periods=1, hour_window=(0, 99)
            )


class LookAheadBarrierForAllFamiliesTests(unittest.TestCase):
    def test_every_family_is_reproducible_on_truncated_series(self) -> None:
        points = mixed_walk_series(200)
        rules = (
            StrategyRule(3, 0.0005, 2, signal_source=SignalSource.MOMENTUM),
            StrategyRule(1, 0.0, 2, signal_source=SignalSource.STREAK, streak_length=3),
            StrategyRule(3, 0.0, 2, signal_source=SignalSource.ALTERNATION),
        )

        for rule in rules:
            with self.subTest(family=rule.signal_source.value):
                for signal in generate_signals(points, rule):
                    truncated = points[: signal.index + 1]
                    replayed = evaluate_at(truncated, len(truncated) - 1, rule)
                    self.assertIs(signal.direction, replayed)


class SearchSpaceTests(unittest.TestCase):
    def test_space_covers_all_families(self) -> None:
        space = build_search_space()
        families = {rule.signal_source for rule in space}

        self.assertEqual(set(SignalSource), families)

    def test_space_is_deterministic(self) -> None:
        first = build_search_space()
        second = build_search_space()

        self.assertEqual(
            [rule.as_dict() for rule in first], [rule.as_dict() for rule in second]
        )

    def test_space_has_no_duplicate_signatures(self) -> None:
        space = build_search_space()
        signatures = {signature_of_rule(rule) for rule in space}

        self.assertEqual(len(space), len(signatures))

    def test_signature_round_trip_through_parameters(self) -> None:
        for rule in build_search_space()[:50]:
            with self.subTest(rule=rule.describe()):
                self.assertEqual(
                    signature_of_rule(rule), signature_of(dict(rule.as_dict()))
                )

    def test_parameter_count_reflects_family(self) -> None:
        momentum = StrategyRule(3, 0.001, 2, signal_source=SignalSource.MOMENTUM)
        streak = StrategyRule(
            1, 0.0, 2, signal_source=SignalSource.STREAK, streak_length=4
        )

        self.assertEqual(4, momentum.parameter_count)
        self.assertEqual(3, streak.parameter_count)
        self.assertEqual(
            5,
            StrategyRule(
                3, 0.001, 2, signal_source=SignalSource.MOMENTUM, hour_window=(0, 5)
            ).parameter_count,
        )

    def test_families_are_interleaved_so_short_runs_cover_all(self) -> None:
        space = build_search_space()
        first_families = {rule.signal_source for rule in space[:8]}

        # Um ciclo curto precisa alcançar todas as famílias, não só momentum.
        self.assertEqual(set(SignalSource), first_families)

    def test_researcher_generates_across_families(self) -> None:
        agent = ResearcherAgent()
        hypotheses = agent.generate("TESTPAIR", "M1", limit=12)

        sources = {item.parameters["signal_source"] for item in hypotheses}
        self.assertGreater(agent.search_space_size, 1000)
        self.assertEqual(
            {source.value for source in SignalSource},
            sources,
        )

    def test_excluded_signatures_are_skipped(self) -> None:
        agent = ResearcherAgent()
        first = agent.generate("TESTPAIR", "M1", limit=5)
        excluded = frozenset(signature_of(dict(item.parameters)) for item in first)

        again = ResearcherAgent().generate(
            "TESTPAIR", "M1", limit=5, exclude=excluded
        )
        repeated = {signature_of(dict(item.parameters)) for item in again} & excluded

        self.assertEqual(set(), repeated)


class ExpectancyMarginTests(unittest.TestCase):
    def test_no_margin_for_single_hypothesis(self) -> None:
        self.assertEqual(0.0, required_expectancy_margin(1))
        self.assertEqual(0.0, required_expectancy_margin(0))

    def test_margin_grows_with_search_space(self) -> None:
        small = required_expectancy_margin(10)
        large = required_expectancy_margin(10_000)

        self.assertGreater(small, 0.0)
        self.assertGreater(large, small)

    def test_margin_is_monotonic(self) -> None:
        values = [required_expectancy_margin(count) for count in (10, 100, 1000, 10000)]

        self.assertEqual(values, sorted(values))
