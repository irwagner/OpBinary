"""Validação e normalização determinísticas de pontos de preço (Fase 2).

Regras obrigatórias desta fase (MASTER_SPEC seções 12, 23, 24, 25):

- nenhum dado é inventado — pontos inválidos são rejeitados, nunca corrigidos
  com interpolação, preenchimento artificial ou suposição de valor;
- timezone é sempre explícito; timestamps naive são rejeitados;
- dados futuros (posteriores ao momento da validação) são rejeitados —
  impede look-ahead bias na origem;
- dados fora de ordem cronológica são rejeitados;
- duplicatas exatas (broker/asset/timeframe/timestamp) são detectadas e
  removidas, mantendo apenas a primeira ocorrência;
- gaps entre pontos consecutivos são detectados e reportados, nunca
  preenchidos artificialmente.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from .data_models import (
    DuplicateFinding,
    GapFinding,
    QualityReport,
    RawPricePoint,
    RejectedRecord,
    ValidatedPricePoint,
)

_MAX_CLOCK_SKEW_SECONDS = 5.0


def _raw_payload(point: RawPricePoint) -> dict[str, object]:
    return {
        "broker": point.broker,
        "asset": point.asset,
        "timeframe": point.timeframe,
        "timestamp": point.timestamp.isoformat(),
        "price": point.price,
        "source": point.source,
    }


def _reject(reason: str, point: RawPricePoint) -> RejectedRecord:
    return RejectedRecord(reason=reason, raw_payload=_raw_payload(point))


def validate_and_normalize(
    points: Sequence[RawPricePoint],
    *,
    now: datetime | None = None,
    expected_interval_seconds: float | None = None,
) -> tuple[tuple[ValidatedPricePoint, ...], QualityReport]:
    """Valida, deduplica, detecta gaps e normaliza timestamps para UTC.

    Não aceita mistura de séries: todos os pontos devem pertencer à mesma
    combinação broker/asset/timeframe. Misturar séries é responsabilidade do
    chamador (rejeitado explicitamente para não mascarar erro de pipeline).
    """
    reference_now = now or datetime.now(UTC)
    if reference_now.tzinfo is None:
        raise ValueError("now deve ser timezone-aware")

    rejections: list[RejectedRecord] = []
    accepted_raw: list[RawPricePoint] = []

    series_key: tuple[str, str, str] | None = None
    for point in points:
        key = (point.broker, point.asset, point.timeframe)
        if series_key is None:
            series_key = key
        elif key != series_key:
            rejections.append(
                _reject(
                    "mixed_series: ponto pertence a broker/asset/timeframe diferente do lote",
                    point,
                )
            )
            continue

        if point.timestamp.tzinfo is None:
            rejections.append(_reject("naive_timestamp: timezone ausente", point))
            continue

        if not _is_finite_positive(point.price):
            rejections.append(_reject("invalid_price: preço não finito ou não positivo", point))
            continue

        delta_seconds = (point.timestamp - reference_now).total_seconds()
        if delta_seconds > _MAX_CLOCK_SKEW_SECONDS:
            rejections.append(_reject("future_timestamp: timestamp posterior ao momento atual", point))
            continue

        accepted_raw.append(point)

    ordered, out_of_order_rejections = _reject_out_of_order(accepted_raw)
    rejections.extend(out_of_order_rejections)

    deduplicated, duplicate_findings = _deduplicate(ordered)

    gaps = (
        _detect_gaps(deduplicated, expected_interval_seconds)
        if expected_interval_seconds is not None
        else ()
    )

    normalized = tuple(_normalize_to_utc(point) for point in deduplicated)

    report = QualityReport(
        total_input=len(points),
        total_accepted=len(normalized),
        total_rejected=len(rejections),
        duplicates_removed=len(duplicate_findings),
        gaps=gaps,
        duplicates=duplicate_findings,
        rejections=tuple(rejections),
    )
    return normalized, report


def _is_finite_positive(price: float) -> bool:
    return price == price and price not in (float("inf"), float("-inf")) and price > 0


def _reject_out_of_order(
    points: Iterable[RawPricePoint],
) -> tuple[list[RawPricePoint], list[RejectedRecord]]:
    ordered: list[RawPricePoint] = []
    rejected: list[RejectedRecord] = []
    last_timestamp: datetime | None = None
    for point in points:
        if last_timestamp is not None and point.timestamp < last_timestamp:
            rejected.append(
                _reject(
                    "out_of_order: timestamp anterior ao último ponto aceito na sequência",
                    point,
                )
            )
            continue
        ordered.append(point)
        last_timestamp = point.timestamp
    return ordered, rejected


def _deduplicate(
    points: Sequence[RawPricePoint],
) -> tuple[list[RawPricePoint], tuple[DuplicateFinding, ...]]:
    seen: dict[datetime, int] = {}
    kept: list[RawPricePoint] = []
    for point in points:
        seen[point.timestamp] = seen.get(point.timestamp, 0) + 1
        if seen[point.timestamp] == 1:
            kept.append(point)

    findings = tuple(
        DuplicateFinding(
            broker=kept[0].broker if kept else "",
            asset=kept[0].asset if kept else "",
            timeframe=kept[0].timeframe if kept else "",
            timestamp=timestamp,
            occurrences=count,
        )
        for timestamp, count in seen.items()
        if count > 1
    )
    return kept, findings


def _detect_gaps(
    points: Sequence[RawPricePoint], expected_interval_seconds: float
) -> tuple[GapFinding, ...]:
    if expected_interval_seconds <= 0:
        raise ValueError("expected_interval_seconds deve ser positivo")
    findings: list[GapFinding] = []
    tolerance = expected_interval_seconds * 1.5
    for previous, current in zip(points, points[1:]):
        actual_gap = (current.timestamp - previous.timestamp).total_seconds()
        if actual_gap > tolerance:
            findings.append(
                GapFinding(
                    broker=current.broker,
                    asset=current.asset,
                    timeframe=current.timeframe,
                    previous_timestamp=previous.timestamp,
                    next_timestamp=current.timestamp,
                    expected_interval_seconds=expected_interval_seconds,
                    actual_gap_seconds=actual_gap,
                )
            )
    return tuple(findings)


def _normalize_to_utc(point: RawPricePoint) -> ValidatedPricePoint:
    return ValidatedPricePoint(
        broker=point.broker,
        asset=point.asset,
        timeframe=point.timeframe,
        timestamp=point.timestamp.astimezone(UTC),
        price=point.price,
        source=point.source,
    )
