from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from ai_trading_lab.data_models import DatasetSplitPlan, ValidatedPricePoint
from ai_trading_lab.data_split import TestSetGuard, split_dataset
from ai_trading_lab.errors import DatasetSplitError


def _points(count: int) -> tuple[ValidatedPricePoint, ...]:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return tuple(
        ValidatedPricePoint(
            broker="Polarium",
            asset="EURUSD",
            timeframe="M1",
            timestamp=base + timedelta(minutes=i),
            price=1.0 + i * 0.0001,
            source="broker_capture",
        )
        for i in range(count)
    )


class SplitDatasetTests(unittest.TestCase):
    def test_split_respects_configured_percentages(self) -> None:
        points = _points(100)
        plan = DatasetSplitPlan(train_pct=0.6, validation_pct=0.2, test_pct=0.2)

        result = split_dataset(points, plan)

        self.assertEqual(60, len(result.train))
        self.assertEqual(20, len(result.validation))
        self.assertEqual(20, len(result.test))

    def test_split_partitions_never_overlap(self) -> None:
        points = _points(50)
        plan = DatasetSplitPlan(train_pct=0.7, validation_pct=0.15, test_pct=0.15)

        result = split_dataset(points, plan)

        train_ids = {id(point) for point in result.train}
        validation_ids = {id(point) for point in result.validation}
        test_ids = {id(point) for point in result.test}
        self.assertEqual(set(), train_ids & validation_ids)
        self.assertEqual(set(), train_ids & test_ids)
        self.assertEqual(set(), validation_ids & test_ids)
        self.assertEqual(len(points), len(train_ids) + len(validation_ids) + len(test_ids))

    def test_split_preserves_chronological_contiguity(self) -> None:
        points = _points(30)
        plan = DatasetSplitPlan(train_pct=0.6, validation_pct=0.2, test_pct=0.2)

        result = split_dataset(points, plan)

        self.assertTrue(result.train[-1].timestamp < result.validation[0].timestamp)
        self.assertTrue(result.validation[-1].timestamp < result.test[0].timestamp)

    def test_split_rejects_out_of_order_points(self) -> None:
        points = list(_points(5))
        points[1], points[2] = points[2], points[1]
        plan = DatasetSplitPlan(train_pct=0.6, validation_pct=0.2, test_pct=0.2)

        with self.assertRaises(DatasetSplitError):
            split_dataset(tuple(points), plan)

    def test_split_plan_rejects_percentages_not_summing_to_one(self) -> None:
        with self.assertRaises(ValueError):
            DatasetSplitPlan(train_pct=0.5, validation_pct=0.2, test_pct=0.2)

    def test_split_plan_rejects_zero_or_negative_percentage(self) -> None:
        with self.assertRaises(ValueError):
            DatasetSplitPlan(train_pct=1.0, validation_pct=0.0, test_pct=0.0)


class TestSetGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        points = _points(10)
        plan = DatasetSplitPlan(train_pct=0.6, validation_pct=0.2, test_pct=0.2)
        self.split = split_dataset(points, plan)

    def test_train_and_validation_are_always_accessible(self) -> None:
        guard = TestSetGuard(self.split)
        self.assertEqual(self.split.train, guard.train())
        self.assertEqual(self.split.validation, guard.validation())

    def test_test_partition_is_blocked_by_default(self) -> None:
        guard = TestSetGuard(self.split)
        with self.assertRaises(DatasetSplitError):
            guard.test()

    def test_test_partition_accessible_after_explicit_unlock(self) -> None:
        guard = TestSetGuard(self.split)
        guard.unlock_for_final_evaluation()
        self.assertEqual(self.split.test, guard.test())

    def test_test_partition_cannot_be_unlocked_twice(self) -> None:
        guard = TestSetGuard(self.split)
        guard.unlock_for_final_evaluation()
        with self.assertRaises(DatasetSplitError):
            guard.unlock_for_final_evaluation()
