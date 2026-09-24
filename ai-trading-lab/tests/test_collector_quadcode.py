from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime
from unittest import mock

from ai_trading_lab.collectors.quadcode import (
    SSID_ENVIRONMENT_VARIABLE,
    CollectorConfig,
    candle_to_point,
    extract_candles,
    read_ssid_from_environment,
)
from ai_trading_lab.data_models import DataOrigin
from ai_trading_lab.errors import DataIngestionError
from ai_trading_lab.logging import sanitize


def _config() -> CollectorConfig:
    return CollectorConfig(
        active_id=76,
        timeframe_seconds=60,
        asset="EURUSD-OTC",
        broker="Polarium",
    )


class SsidHandlingTests(unittest.TestCase):
    def test_reads_ssid_from_environment(self) -> None:
        with mock.patch.dict(os.environ, {SSID_ENVIRONMENT_VARIABLE: "abc123"}):
            self.assertEqual("abc123", read_ssid_from_environment())

    def test_missing_ssid_fails_explicitly(self) -> None:
        with mock.patch.dict(os.environ, {SSID_ENVIRONMENT_VARIABLE: ""}):
            with self.assertRaises(DataIngestionError):
                read_ssid_from_environment()

    def test_ssid_is_masked_by_sanitizer(self) -> None:
        payload = sanitize(
            {
                "name": "authenticate",
                "msg": {"ssid": "ca32eb5177c4b97f4cdfd2880267248i", "protocol": 3},
            }
        )

        self.assertEqual("***REDACTED***", payload["msg"]["ssid"])
        self.assertEqual(3, payload["msg"]["protocol"])

    def test_session_id_is_masked_by_sanitizer(self) -> None:
        payload = sanitize({"session_id": "s-1", "client_session_id": "c-1"})

        self.assertEqual("***REDACTED***", payload["session_id"])
        self.assertEqual("***REDACTED***", payload["client_session_id"])

    def test_ssid_masked_in_free_text(self) -> None:
        sanitized = sanitize('conectando com ssid=ca32eb5177c4b97f4c; ok')

        self.assertIn("***REDACTED***", sanitized)
        self.assertNotIn("ca32eb5177c4b97f4c", sanitized)


class ExtractCandlesTests(unittest.TestCase):
    def test_extracts_from_candles_key(self) -> None:
        message = {"name": "candles", "msg": {"candles": [{"from": 1, "close": 1.1}]}}

        self.assertEqual(1, len(extract_candles(message)))

    def test_extracts_from_data_key(self) -> None:
        message = {"name": "candles", "msg": {"data": [{"at": 1, "c": 1.1}]}}

        self.assertEqual(1, len(extract_candles(message)))

    def test_extracts_single_candle_envelope(self) -> None:
        message = {"name": "candle-generated", "msg": {"from": 1, "close": 1.1}}

        self.assertEqual(1, len(extract_candles(message)))

    def test_extracts_from_bare_list(self) -> None:
        message = {"name": "candles", "msg": [{"from": 1, "close": 1.1}]}

        self.assertEqual(1, len(extract_candles(message)))

    def test_ignores_message_without_candles(self) -> None:
        message = {"name": "profile", "msg": {"balance": 100}}

        self.assertEqual([], extract_candles(message))


class CandleConversionTests(unittest.TestCase):
    def test_converts_full_ohlc_candle(self) -> None:
        candle = {
            "from": 1767225600,
            "open": 1.1000,
            "max": 1.1050,
            "min": 1.0980,
            "close": 1.1020,
        }

        point = candle_to_point(candle, _config())

        self.assertIsNotNone(point)
        self.assertEqual(1.1020, point.price)
        self.assertEqual(1.1000, point.open)
        self.assertEqual(1.1050, point.high)
        self.assertEqual(1.0980, point.low)
        self.assertEqual(UTC, point.timestamp.tzinfo)
        self.assertIs(DataOrigin.BROKER_OTC, point.origin)

    def test_converts_abbreviated_keys(self) -> None:
        candle = {"at": 1767225600, "o": 1.10, "h": 1.11, "l": 1.09, "c": 1.105}

        point = candle_to_point(candle, _config())

        self.assertIsNotNone(point)
        self.assertEqual(1.105, point.price)
        self.assertEqual(1.11, point.high)

    def test_converts_close_only_candle(self) -> None:
        point = candle_to_point({"time": 1767225600, "close": 1.1}, _config())

        self.assertIsNotNone(point)
        self.assertIsNone(point.open)
        self.assertEqual(1.1, point.price)

    def test_normalizes_milliseconds(self) -> None:
        seconds = candle_to_point({"from": 1767225600, "close": 1.1}, _config())
        millis = candle_to_point({"from": 1767225600000, "close": 1.1}, _config())

        self.assertEqual(seconds.timestamp, millis.timestamp)

    def test_normalizes_microseconds(self) -> None:
        seconds = candle_to_point({"from": 1767225600, "close": 1.1}, _config())
        micros = candle_to_point({"from": 1767225600000000, "close": 1.1}, _config())

        self.assertEqual(seconds.timestamp, micros.timestamp)

    def test_normalizes_nanoseconds(self) -> None:
        # A plataforma envia o campo `at` em nanossegundos.
        seconds = candle_to_point({"from": 1767225600, "close": 1.1}, _config())
        nanos = candle_to_point({"at": 1767225600000000000, "close": 1.1}, _config())

        self.assertEqual(seconds.timestamp, nanos.timestamp)

    def test_real_platform_candle_shape(self) -> None:
        # Formato real observado na plataforma (Quadcode / protocolo IQ Option).
        candle = {
            "id": 3322821,
            "from": 1790207520,
            "at": 1790207580000000000,
            "to": 1790207580,
            "open": 1.13825,
            "close": 1.138235,
            "min": 1.138225,
            "max": 1.138255,
            "volume": 27,
        }

        point = candle_to_point(candle, _config())

        self.assertIsNotNone(point)
        # `from` (início da vela, em segundos) tem precedência sobre `at`.
        self.assertEqual(
            datetime.fromtimestamp(1790207520, tz=UTC), point.timestamp
        )
        self.assertEqual(1.138235, point.price)
        self.assertEqual(1.13825, point.open)
        self.assertEqual(1.138255, point.high)
        self.assertEqual(1.138225, point.low)

    def test_rejects_candle_without_time(self) -> None:
        self.assertIsNone(candle_to_point({"close": 1.1}, _config()))

    def test_rejects_candle_without_close(self) -> None:
        self.assertIsNone(candle_to_point({"from": 1767225600}, _config()))

    def test_rejects_non_positive_close(self) -> None:
        self.assertIsNone(candle_to_point({"from": 1767225600, "close": 0}, _config()))
        self.assertIsNone(candle_to_point({"from": 1767225600, "close": -1}, _config()))

    def test_rejects_invalid_time(self) -> None:
        self.assertIsNone(candle_to_point({"from": 0, "close": 1.1}, _config()))
        self.assertIsNone(candle_to_point({"from": "abc", "close": 1.1}, _config()))

    def test_drops_invalid_ohlc_without_inventing(self) -> None:
        candle = {"from": 1767225600, "close": 1.1, "open": "ruim", "max": None}

        point = candle_to_point(candle, _config())

        self.assertIsNotNone(point)
        self.assertIsNone(point.open)
        self.assertIsNone(point.high)

    def test_produces_timezone_aware_timestamp(self) -> None:
        point = candle_to_point({"from": 1767225600, "close": 1.1}, _config())

        self.assertIsNotNone(point.timestamp.tzinfo)
        self.assertEqual(
            datetime.fromtimestamp(1767225600, tz=UTC), point.timestamp
        )


class CollectorConfigTests(unittest.TestCase):
    def test_rejects_invalid_timeframe(self) -> None:
        with self.assertRaises(ValueError):
            CollectorConfig(active_id=1, timeframe_seconds=0)

    def test_rejects_invalid_active_id(self) -> None:
        with self.assertRaises(ValueError):
            CollectorConfig(active_id=0, timeframe_seconds=60)

    def test_defaults_to_otc_origin(self) -> None:
        self.assertIs(DataOrigin.BROKER_OTC, _config().origin)


class ReadOnlyGuaranteeTests(unittest.TestCase):
    """O coletor não deve expor nenhuma operação de execução."""

    def test_module_has_no_order_placement_api(self) -> None:
        from ai_trading_lab.collectors import quadcode

        proibidos = (
            "buy",
            "sell",
            "place_order",
            "open_position",
            "close_position",
            "withdraw",
            "deposit",
        )
        exportados = {name.lower() for name in dir(quadcode)}
        for nome in proibidos:
            with self.subTest(operacao=nome):
                self.assertNotIn(nome, exportados)
