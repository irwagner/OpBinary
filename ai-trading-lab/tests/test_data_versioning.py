from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from ai_trading_lab.data_models import DatasetStage, ValidatedPricePoint
from ai_trading_lab.data_versioning import build_dataset_version, compute_content_hash
from ai_trading_lab.errors import DatasetVersionError


def _points(count: int, price_offset: float = 0.0) -> tuple[ValidatedPricePoint, ...]:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return tuple(
        ValidatedPricePoint(
            broker="Polarium",
            asset="EURUSD",
            timeframe="M1",
            timestamp=base + timedelta(minutes=i),
            price=1.0 + i * 0.0001 + price_offset,
            source="broker_capture",
        )
        for i in range(count)
    )


class ContentHashTests(unittest.TestCase):
    def test_identical_content_produces_identical_hash(self) -> None:
        first = _points(10)
        second = _points(10)

        self.assertEqual(compute_content_hash(first), compute_content_hash(second))

    def test_different_content_produces_different_hash(self) -> None:
        first = _points(10)
        second = _points(10, price_offset=0.5)

        self.assertNotEqual(compute_content_hash(first), compute_content_hash(second))

    def test_hash_is_order_sensitive(self) -> None:
        points = _points(3)
        reordered = (points[1], points[0], points[2])

        self.assertNotEqual(compute_content_hash(points), compute_content_hash(reordered))


class BuildDatasetVersionTests(unittest.TestCase):
    def test_builds_version_with_correct_coverage(self) -> None:
        points = _points(5)

        version = build_dataset_version("DATA-000001", 1, points, DatasetStage.VALIDATED)

        self.assertEqual("DATA-000001", version.dataset_id)
        self.assertEqual(1, version.version)
        self.assertEqual(5, version.point_count)
        self.assertEqual(points[0].timestamp, version.coverage_start)
        self.assertEqual(points[-1].timestamp, version.coverage_end)
        self.assertEqual(compute_content_hash(points), version.content_hash)

    def test_rejects_version_below_one(self) -> None:
        points = _points(1)
        with self.assertRaises(DatasetVersionError):
            build_dataset_version("DATA-000001", 0, points, DatasetStage.VALIDATED)

    def test_rejects_empty_dataset(self) -> None:
        with self.assertRaises(DatasetVersionError):
            build_dataset_version("DATA-000001", 1, (), DatasetStage.VALIDATED)

    def test_rejects_mixed_broker_in_same_version(self) -> None:
        base = datetime(2026, 1, 1, tzinfo=UTC)
        points = (
            ValidatedPricePoint("Polarium", "EURUSD", "M1", base, 1.0, "broker_capture"),
            ValidatedPricePoint(
                "DayProfit", "EURUSD", "M1", base + timedelta(minutes=1), 1.0, "broker_capture"
            ),
        )
        with self.assertRaises(DatasetVersionError):
            build_dataset_version("DATA-000001", 1, points, DatasetStage.VALIDATED)
