from __future__ import annotations

import json
import sqlite3
import unittest
from datetime import UTC, datetime, timedelta

from ai_trading_lab.data_models import DatasetStage, QualityReport, RejectedRecord, ValidatedPricePoint
from ai_trading_lab.data_persistence import DatasetStore
from ai_trading_lab.data_versioning import build_dataset_version
from ai_trading_lab.errors import DatasetVersionError, PersistenceError


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


def _empty_report(count: int) -> QualityReport:
    return QualityReport(
        total_input=count,
        total_accepted=count,
        total_rejected=0,
        duplicates_removed=0,
        gaps=(),
        duplicates=(),
        rejections=(),
    )


class DatasetStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = DatasetStore()

    def tearDown(self) -> None:
        self.store.close()

    def test_appends_and_loads_dataset_version(self) -> None:
        points = _points(5)
        version = build_dataset_version("DATA-000001", 1, points, DatasetStage.VALIDATED)

        self.store.append_dataset_version(version, points, _empty_report(5))

        loaded = self.store.load_dataset_version("DATA-000001", 1)
        self.assertIsNotNone(loaded)
        self.assertEqual(version.content_hash, loaded.content_hash)
        self.assertEqual(5, loaded.point_count)

        loaded_points = self.store.load_points("DATA-000001", 1)
        self.assertEqual(len(points), len(loaded_points))
        self.assertEqual(points[0].timestamp, loaded_points[0].timestamp)

    def test_cannot_overwrite_existing_version(self) -> None:
        points = _points(3)
        version = build_dataset_version("DATA-000002", 1, points, DatasetStage.VALIDATED)
        self.store.append_dataset_version(version, points, _empty_report(3))

        with self.assertRaises(PersistenceError):
            self.store.append_dataset_version(version, points, _empty_report(3))

    def test_rejects_version_with_hash_mismatch(self) -> None:
        points = _points(3)
        version = build_dataset_version("DATA-000003", 1, points, DatasetStage.VALIDATED)
        tampered_points = _points(4)  # conteúdo diferente do hash já calculado

        with self.assertRaises(DatasetVersionError):
            self.store.append_dataset_version(version, tampered_points, _empty_report(4))

    def test_latest_version_number_increments(self) -> None:
        points = _points(2)
        v1 = build_dataset_version("DATA-000004", 1, points, DatasetStage.VALIDATED)
        self.store.append_dataset_version(v1, points, _empty_report(2))

        self.assertEqual(1, self.store.latest_version_number("DATA-000004"))

        v2 = build_dataset_version("DATA-000004", 2, points, DatasetStage.VALIDATED)
        self.store.append_dataset_version(v2, points, _empty_report(2))

        self.assertEqual(2, self.store.latest_version_number("DATA-000004"))

    def test_unknown_dataset_has_zero_latest_version(self) -> None:
        self.assertEqual(0, self.store.latest_version_number("DATA-UNKNOWN"))

    def test_dataset_versions_are_append_only(self) -> None:
        points = _points(2)
        version = build_dataset_version("DATA-000005", 1, points, DatasetStage.VALIDATED)
        self.store.append_dataset_version(version, points, _empty_report(2))

        for statement in (
            "UPDATE dataset_versions SET point_count = 999",
            "DELETE FROM dataset_versions",
        ):
            with self.subTest(statement=statement):
                with self.assertRaises(sqlite3.DatabaseError):
                    self.store._connection.execute(statement)
                self.store._connection.rollback()

    def test_dataset_points_are_append_only(self) -> None:
        points = _points(2)
        version = build_dataset_version("DATA-000006", 1, points, DatasetStage.VALIDATED)
        self.store.append_dataset_version(version, points, _empty_report(2))

        for statement in (
            "UPDATE dataset_points SET price = 999.0",
            "DELETE FROM dataset_points",
        ):
            with self.subTest(statement=statement):
                with self.assertRaises(sqlite3.DatabaseError):
                    self.store._connection.execute(statement)
                self.store._connection.rollback()

    def test_quality_report_rejections_are_sanitized_before_persistence(self) -> None:
        points = _points(1)
        version = build_dataset_version("DATA-000007", 1, points, DatasetStage.VALIDATED)
        report = QualityReport(
            total_input=2,
            total_accepted=1,
            total_rejected=1,
            duplicates_removed=0,
            gaps=(),
            duplicates=(),
            rejections=(
                RejectedRecord(
                    reason="invalid_price",
                    raw_payload={"api_key": "raw-secret-value", "price": -1.0},
                ),
            ),
        )

        self.store.append_dataset_version(version, points, report)

        with self.store._connection as connection:
            row = connection.execute(
                "SELECT rejections_json FROM quality_reports WHERE dataset_id = ?",
                ("DATA-000007",),
            ).fetchone()
        payload = json.loads(row["rejections_json"])
        serialized = json.dumps(payload)
        self.assertNotIn("raw-secret-value", serialized)
        self.assertIn("***REDACTED***", serialized)

    def test_list_versions_returns_ascending_order(self) -> None:
        points = _points(1)
        for version_number in (1, 2, 3):
            version = build_dataset_version(
                "DATA-000008", version_number, points, DatasetStage.VALIDATED
            )
            self.store.append_dataset_version(version, points, _empty_report(1))

        versions = self.store.list_versions("DATA-000008")
        self.assertEqual([1, 2, 3], [v.version for v in versions])
