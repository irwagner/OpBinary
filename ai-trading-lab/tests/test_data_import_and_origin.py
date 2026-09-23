from __future__ import annotations

import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from ai_trading_lab.configuration import load_config_file, load_system_config
from ai_trading_lab.data_import import FileMarketDataSource, collect_from_sources
from ai_trading_lab.data_ingestion import ingest_raw_batch
from ai_trading_lab.data_models import DataOrigin, DatasetStage, RawPricePoint
from ai_trading_lab.data_persistence import DatasetStore
from ai_trading_lab.data_validation import validate_and_normalize
from ai_trading_lab.data_versioning import build_dataset_version, compute_content_hash
from ai_trading_lab.errors import ConfigurationError, DataIngestionError, DatasetVersionError
from tests.fixtures import past_start

CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs"


def _csv_rows(count: int, *, tz_suffix: str = "+00:00") -> str:
    start = past_start(count + 10)
    lines = ["timestamp,price"]
    for index in range(count):
        moment = (start + timedelta(minutes=index)).replace(microsecond=0)
        stamp = moment.strftime("%Y-%m-%dT%H:%M:%S")
        lines.append(f"{stamp}{tz_suffix},{1.0 + index * 0.001:.6f}")
    return "\n".join(lines) + "\n"


class FileImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.directory = Path(self._temp.name)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _source(self, path: Path, origin: DataOrigin = DataOrigin.BROKER_OTC):
        return FileMarketDataSource(
            path=path,
            broker="Polarium",
            asset="EURUSD-OTC",
            timeframe="M1",
            origin=origin,
        )

    def test_imports_csv_with_declared_origin(self) -> None:
        path = self.directory / "serie.csv"
        path.write_text(_csv_rows(20), encoding="utf-8")

        result = self._source(path).read()

        self.assertEqual(20, result.accepted)
        self.assertEqual((), result.rejections)
        self.assertTrue(
            all(point.origin is DataOrigin.BROKER_OTC for point in result.points)
        )

    def test_imports_json_list(self) -> None:
        path = self.directory / "serie.json"
        start = past_start(30)
        payload = [
            {
                "timestamp": (start + timedelta(minutes=index)).isoformat(),
                "price": 1.0 + index * 0.001,
            }
            for index in range(10)
        ]
        path.write_text(json.dumps(payload), encoding="utf-8")

        result = self._source(path).read()

        self.assertEqual(10, result.accepted)

    def test_rejects_timestamp_without_timezone(self) -> None:
        path = self.directory / "naive.csv"
        path.write_text("timestamp,price\n2026-01-01T10:00:00,1.2345\n", encoding="utf-8")

        result = self._source(path).read()

        self.assertEqual(0, result.accepted)
        self.assertEqual(1, len(result.rejections))
        self.assertIn("sem timezone", result.rejections[0].reason)

    def test_rejects_invalid_price_without_inventing_value(self) -> None:
        path = self.directory / "precos.csv"
        path.write_text(
            "timestamp,price\n"
            "2026-01-01T10:00:00+00:00,abc\n"
            "2026-01-01T10:01:00+00:00,-1.0\n"
            "2026-01-01T10:02:00+00:00,\n",
            encoding="utf-8",
        )

        result = self._source(path).read()

        self.assertEqual(0, result.accepted)
        self.assertEqual(3, len(result.rejections))

    def test_accepts_epoch_seconds(self) -> None:
        path = self.directory / "epoch.csv"
        path.write_text("timestamp,price\n1767225600,1.2345\n", encoding="utf-8")

        result = self._source(path).read()

        self.assertEqual(1, result.accepted)
        self.assertIsNotNone(result.points[0].timestamp.tzinfo)

    def test_rejects_missing_required_column(self) -> None:
        path = self.directory / "ruim.csv"
        path.write_text("data,valor\n2026-01-01,1.0\n", encoding="utf-8")

        with self.assertRaises(DataIngestionError):
            self._source(path).read()

    def test_rejects_unsupported_extension(self) -> None:
        path = self.directory / "serie.txt"
        path.write_text("qualquer coisa", encoding="utf-8")

        with self.assertRaises(DataIngestionError):
            self._source(path).read()

    def test_rejects_missing_file(self) -> None:
        with self.assertRaises(DataIngestionError):
            self._source(self.directory / "inexistente.csv").read()

    def test_end_to_end_import_then_ingest(self) -> None:
        path = self.directory / "serie.csv"
        path.write_text(_csv_rows(120), encoding="utf-8")
        store = DatasetStore()
        try:
            points = collect_from_sources([self._source(path)])

            result = ingest_raw_batch(store, "DATA-OTC-001", points)

            self.assertEqual(1, result.dataset_version.version)
            self.assertIs(DataOrigin.BROKER_OTC, result.dataset_version.origin)
            self.assertTrue(result.dataset_version.basis_risk_high)
        finally:
            store.close()


class OriginIsolationTests(unittest.TestCase):
    def _point(self, origin: DataOrigin, minutes: int) -> RawPricePoint:
        return RawPricePoint(
            broker="Polarium",
            asset="EURUSD-OTC",
            timeframe="M1",
            timestamp=past_start(60) + timedelta(minutes=minutes),
            price=1.0 + minutes * 0.001,
            origin=origin,
        )

    def test_validation_rejects_mixed_origins(self) -> None:
        points = [
            self._point(DataOrigin.BROKER_OTC, 0),
            self._point(DataOrigin.MARKET_PROXY, 1),
            self._point(DataOrigin.BROKER_OTC, 2),
        ]

        accepted, report = validate_and_normalize(points)

        self.assertEqual(2, len(accepted))
        self.assertEqual(1, report.total_rejected)
        self.assertIn("mixed_series", report.rejections[0].reason)

    def test_versioning_rejects_mixed_origins(self) -> None:
        accepted_otc, _ = validate_and_normalize(
            [self._point(DataOrigin.BROKER_OTC, index) for index in range(3)]
        )
        accepted_proxy, _ = validate_and_normalize(
            [self._point(DataOrigin.MARKET_PROXY, index) for index in range(3, 6)]
        )

        with self.assertRaises(DatasetVersionError):
            build_dataset_version(
                "DATA-MIX", 1, accepted_otc + accepted_proxy, DatasetStage.VALIDATED
            )

    def test_origin_changes_content_hash(self) -> None:
        otc, _ = validate_and_normalize(
            [self._point(DataOrigin.BROKER_OTC, index) for index in range(5)]
        )
        proxy, _ = validate_and_normalize(
            [self._point(DataOrigin.MARKET_PROXY, index) for index in range(5)]
        )

        self.assertNotEqual(compute_content_hash(otc), compute_content_hash(proxy))

    def test_market_proxy_has_no_high_basis_risk(self) -> None:
        self.assertFalse(DataOrigin.MARKET_PROXY.has_high_basis_risk)
        self.assertTrue(DataOrigin.BROKER_OTC.has_high_basis_risk)

    def test_origin_survives_persistence_round_trip(self) -> None:
        store = DatasetStore()
        try:
            accepted, _ = validate_and_normalize(
                [self._point(DataOrigin.MARKET_PROXY, index) for index in range(10)]
            )
            result = ingest_raw_batch(store, "DATA-PROXY", accepted_raw(accepted))

            loaded = store.load_dataset_version("DATA-PROXY", 1)
            points = store.load_points("DATA-PROXY", 1)

            self.assertIsNotNone(loaded)
            self.assertIs(DataOrigin.MARKET_PROXY, loaded.origin)
            self.assertFalse(loaded.basis_risk_high)
            self.assertTrue(all(p.origin is DataOrigin.MARKET_PROXY for p in points))
            self.assertEqual(result.dataset_version.content_hash, loaded.content_hash)
        finally:
            store.close()


def accepted_raw(validated) -> tuple[RawPricePoint, ...]:
    """Converte pontos validados de volta para brutos, preservando a origem."""
    return tuple(
        RawPricePoint(
            broker=point.broker,
            asset=point.asset,
            timeframe=point.timeframe,
            timestamp=point.timestamp,
            price=point.price,
            source=point.source,
            origin=point.origin,
        )
        for point in validated
    )


class BrokerRiskGateConfigTests(unittest.TestCase):
    def test_research_and_demo_do_not_block_on_broker_risk(self) -> None:
        for name in ("research", "demo"):
            with self.subTest(config=name):
                config = load_config_file(CONFIG_DIR / f"{name}.yaml")
                self.assertFalse(config.broker_risk.blocking)

    def test_real_requires_blocking_broker_risk(self) -> None:
        config = load_config_file(CONFIG_DIR / "real.yaml")
        self.assertTrue(config.broker_risk.blocking)

    def test_real_without_blocking_gate_is_rejected(self) -> None:
        with self.assertRaises(ConfigurationError):
            load_system_config(
                {
                    "mode": "REAL",
                    "execution": {"enabled": False},
                    "broker_risk": {"blocking": False},
                }
            )

    def test_gate_defaults_to_non_blocking(self) -> None:
        config = load_system_config(
            {"mode": "RESEARCH", "execution": {"enabled": False}}
        )
        self.assertFalse(config.broker_risk.blocking)
