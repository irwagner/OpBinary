from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta, timezone

from ai_trading_lab.data_models import RawPricePoint
from ai_trading_lab.data_validation import validate_and_normalize


def _point(
    timestamp: datetime,
    price: float = 1.2345,
    broker: str = "Polarium",
    asset: str = "EURUSD",
    timeframe: str = "M1",
) -> RawPricePoint:
    return RawPricePoint(
        broker=broker,
        asset=asset,
        timeframe=timeframe,
        timestamp=timestamp,
        price=price,
    )


class TimestampAndTimezoneTests(unittest.TestCase):
    def test_rejects_naive_timestamp(self) -> None:
        with self.assertRaises(ValueError):
            RawPricePoint(
                broker="Polarium",
                asset="EURUSD",
                timeframe="M1",
                timestamp=datetime(2026, 1, 1, 12, 0, 0),  # naive, sem tzinfo
                price=1.0,
            )

    def test_rejects_timestamp_without_timezone_at_validation_boundary(self) -> None:
        now = datetime.now(UTC)
        aware_point = _point(now - timedelta(minutes=1))
        accepted, report = validate_and_normalize([aware_point], now=now)
        self.assertEqual(1, len(accepted))
        self.assertEqual(0, report.total_rejected)

    def test_normalizes_non_utc_timezone_to_utc(self) -> None:
        now = datetime.now(UTC)
        offset_tz = timezone(timedelta(hours=-3))
        local_time = (now - timedelta(minutes=5)).astimezone(offset_tz)
        point = _point(local_time)

        accepted, report = validate_and_normalize([point], now=now)

        self.assertEqual(1, len(accepted))
        self.assertEqual(UTC, accepted[0].timestamp.tzinfo)
        self.assertEqual(local_time.astimezone(UTC), accepted[0].timestamp)

    def test_validate_and_normalize_rejects_naive_now(self) -> None:
        with self.assertRaises(ValueError):
            validate_and_normalize([], now=datetime(2026, 1, 1))


class FutureDataTests(unittest.TestCase):
    def test_rejects_timestamp_in_the_future(self) -> None:
        now = datetime.now(UTC)
        future_point = _point(now + timedelta(minutes=10))

        accepted, report = validate_and_normalize([future_point], now=now)

        self.assertEqual(0, len(accepted))
        self.assertEqual(1, report.total_rejected)
        self.assertIn("future_timestamp", report.rejections[0].reason)

    def test_accepts_timestamp_within_small_clock_skew_tolerance(self) -> None:
        now = datetime.now(UTC)
        slightly_ahead = _point(now + timedelta(seconds=2))

        accepted, report = validate_and_normalize([slightly_ahead], now=now)

        self.assertEqual(1, len(accepted))
        self.assertEqual(0, report.total_rejected)


class OutOfOrderTests(unittest.TestCase):
    def test_rejects_point_out_of_chronological_order(self) -> None:
        now = datetime.now(UTC)
        base = now - timedelta(minutes=10)
        points = [
            _point(base),
            _point(base + timedelta(minutes=2)),
            _point(base + timedelta(minutes=1)),  # fora de ordem
            _point(base + timedelta(minutes=3)),
        ]

        accepted, report = validate_and_normalize(points, now=now)

        self.assertEqual(3, len(accepted))
        self.assertEqual(1, report.total_rejected)
        self.assertIn("out_of_order", report.rejections[0].reason)

    def test_accepted_points_remain_in_ascending_order(self) -> None:
        now = datetime.now(UTC)
        base = now - timedelta(minutes=10)
        points = [_point(base + timedelta(minutes=i)) for i in range(5)]

        accepted, _ = validate_and_normalize(points, now=now)

        timestamps = [point.timestamp for point in accepted]
        self.assertEqual(sorted(timestamps), timestamps)


class DuplicateTests(unittest.TestCase):
    def test_detects_and_removes_exact_duplicates(self) -> None:
        now = datetime.now(UTC)
        base = now - timedelta(minutes=10)
        duplicated_timestamp = base + timedelta(minutes=1)
        points = [
            _point(base),
            _point(duplicated_timestamp),
            _point(duplicated_timestamp),
            _point(duplicated_timestamp),
            _point(base + timedelta(minutes=2)),
        ]

        accepted, report = validate_and_normalize(points, now=now)

        self.assertEqual(3, len(accepted))
        self.assertEqual(1, report.duplicates_removed)
        self.assertEqual(1, len(report.duplicates))
        self.assertEqual(3, report.duplicates[0].occurrences)

    def test_keeps_first_occurrence_of_duplicate(self) -> None:
        now = datetime.now(UTC)
        base = now - timedelta(minutes=10)
        duplicated_timestamp = base + timedelta(minutes=1)
        first = _point(duplicated_timestamp, price=1.1111)
        second = _point(duplicated_timestamp, price=9.9999)

        accepted, _ = validate_and_normalize([first, second], now=now)

        self.assertEqual(1, len(accepted))
        self.assertEqual(1.1111, accepted[0].price)


class GapDetectionTests(unittest.TestCase):
    def test_detects_gap_larger_than_tolerance(self) -> None:
        now = datetime.now(UTC)
        base = now - timedelta(minutes=30)
        points = [
            _point(base),
            _point(base + timedelta(minutes=1)),
            _point(base + timedelta(minutes=10)),  # gap grande
            _point(base + timedelta(minutes=11)),
        ]

        _, report = validate_and_normalize(
            points, now=now, expected_interval_seconds=60.0
        )

        self.assertEqual(1, len(report.gaps))
        self.assertAlmostEqual(540.0, report.gaps[0].actual_gap_seconds)

    def test_no_gap_reported_within_tolerance(self) -> None:
        now = datetime.now(UTC)
        base = now - timedelta(minutes=10)
        points = [_point(base + timedelta(seconds=60 * i)) for i in range(5)]

        _, report = validate_and_normalize(
            points, now=now, expected_interval_seconds=60.0
        )

        self.assertEqual(0, len(report.gaps))

    def test_gaps_not_computed_without_expected_interval(self) -> None:
        now = datetime.now(UTC)
        base = now - timedelta(minutes=30)
        points = [_point(base), _point(base + timedelta(minutes=20))]

        _, report = validate_and_normalize(points, now=now)

        self.assertEqual(0, len(report.gaps))

    def test_rejects_non_positive_expected_interval(self) -> None:
        now = datetime.now(UTC)
        points = [_point(now - timedelta(minutes=1))]

        with self.assertRaises(ValueError):
            validate_and_normalize(points, now=now, expected_interval_seconds=0)


class InvalidPriceAndMixedSeriesTests(unittest.TestCase):
    def test_rejects_non_positive_price(self) -> None:
        now = datetime.now(UTC)
        point = _point(now - timedelta(minutes=1), price=-1.0)

        accepted, report = validate_and_normalize([point], now=now)

        self.assertEqual(0, len(accepted))
        self.assertIn("invalid_price", report.rejections[0].reason)

    def test_rejects_nan_price(self) -> None:
        now = datetime.now(UTC)
        point = _point(now - timedelta(minutes=1), price=float("nan"))

        accepted, report = validate_and_normalize([point], now=now)

        self.assertEqual(0, len(accepted))
        self.assertIn("invalid_price", report.rejections[0].reason)

    def test_rejects_point_from_mixed_series(self) -> None:
        now = datetime.now(UTC)
        base = now - timedelta(minutes=5)
        points = [
            _point(base, broker="Polarium"),
            _point(base + timedelta(minutes=1), broker="DayProfit"),
        ]

        accepted, report = validate_and_normalize(points, now=now)

        self.assertEqual(1, len(accepted))
        self.assertIn("mixed_series", report.rejections[0].reason)

    def test_rejection_never_invents_a_replacement_value(self) -> None:
        now = datetime.now(UTC)
        point = _point(now + timedelta(hours=1))  # inválido: futuro

        accepted, report = validate_and_normalize([point], now=now)

        self.assertEqual((), accepted)
        self.assertEqual(1, report.total_rejected)
        self.assertEqual(1, report.total_input)
