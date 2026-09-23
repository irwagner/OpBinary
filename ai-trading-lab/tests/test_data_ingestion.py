from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from ai_trading_lab.data_ingestion import ingest_raw_batch, promote_to_processed
from ai_trading_lab.data_models import DatasetStage, RawPricePoint
from ai_trading_lab.data_persistence import DatasetStore
from ai_trading_lab.errors import DataQualityError


def _raw_points(count: int, start: datetime) -> tuple[RawPricePoint, ...]:
    return tuple(
        RawPricePoint(
            broker="Polarium",
            asset="EURUSD",
            timeframe="M1",
            timestamp=start + timedelta(minutes=i),
            price=1.0 + i * 0.0001,
        )
        for i in range(count)
    )


class IngestRawBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = DatasetStore()
        self.now = datetime.now(UTC)

    def tearDown(self) -> None:
        self.store.close()

    def test_ingests_valid_batch_as_first_version(self) -> None:
        points = _raw_points(10, self.now - timedelta(minutes=20))

        result = ingest_raw_batch(self.store, "DATA-000001", points)

        self.assertEqual(1, result.dataset_version.version)
        self.assertEqual(DatasetStage.VALIDATED, result.dataset_version.stage)
        self.assertEqual(10, len(result.points))
        self.assertEqual(0, result.report.total_rejected)

    def test_second_ingestion_creates_new_version_without_overwriting(self) -> None:
        first_points = _raw_points(5, self.now - timedelta(minutes=30))
        ingest_raw_batch(self.store, "DATA-000002", first_points)

        second_points = _raw_points(5, self.now - timedelta(minutes=10))
        result = ingest_raw_batch(self.store, "DATA-000002", second_points)

        self.assertEqual(2, result.dataset_version.version)
        self.assertEqual(1, self.store.load_dataset_version("DATA-000002", 1).version)
        self.assertEqual(2, self.store.load_dataset_version("DATA-000002", 2).version)

    def test_rejects_batch_with_no_valid_points(self) -> None:
        all_future = tuple(
            RawPricePoint(
                broker="Polarium",
                asset="EURUSD",
                timeframe="M1",
                timestamp=self.now + timedelta(hours=1, minutes=i),
                price=1.0,
            )
            for i in range(3)
        )

        with self.assertRaises(DataQualityError):
            ingest_raw_batch(self.store, "DATA-000003", all_future)

        self.assertEqual(0, self.store.latest_version_number("DATA-000003"))

    def test_partial_rejection_still_persists_accepted_points_and_report(self) -> None:
        base = self.now - timedelta(minutes=10)
        points = (
            RawPricePoint("Polarium", "EURUSD", "M1", base, 1.0),
            RawPricePoint("Polarium", "EURUSD", "M1", base + timedelta(hours=2), 1.0),  # futuro
            RawPricePoint("Polarium", "EURUSD", "M1", base + timedelta(minutes=1), 1.0),
        )

        result = ingest_raw_batch(self.store, "DATA-000004", points)

        self.assertEqual(2, len(result.points))
        self.assertEqual(1, result.report.total_rejected)
        stored_points = self.store.load_points("DATA-000004", 1)
        self.assertEqual(2, len(stored_points))


class PromoteToProcessedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = DatasetStore()
        self.now = datetime.now(UTC)

    def tearDown(self) -> None:
        self.store.close()

    def test_promotes_validated_dataset_to_processed_as_new_version(self) -> None:
        points = _raw_points(5, self.now - timedelta(minutes=20))
        ingested = ingest_raw_batch(self.store, "DATA-000005", points)

        result = promote_to_processed(self.store, "DATA-000005", ingested.dataset_version.version)

        self.assertEqual(2, result.dataset_version.version)
        self.assertEqual(DatasetStage.PROCESSED, result.dataset_version.stage)
        self.assertEqual(ingested.points, result.points)

    def test_cannot_promote_nonexistent_version(self) -> None:
        with self.assertRaises(DataQualityError):
            promote_to_processed(self.store, "DATA-UNKNOWN", 1)

    def test_cannot_promote_already_processed_dataset(self) -> None:
        points = _raw_points(3, self.now - timedelta(minutes=10))
        ingested = ingest_raw_batch(self.store, "DATA-000006", points)
        promoted = promote_to_processed(self.store, "DATA-000006", ingested.dataset_version.version)

        with self.assertRaises(DataQualityError):
            promote_to_processed(self.store, "DATA-000006", promoted.dataset_version.version)
