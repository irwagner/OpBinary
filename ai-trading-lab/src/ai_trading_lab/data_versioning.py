"""Versionamento de dataset por hash de conteúdo (Fase 2).

Regra obrigatória: cada dataset registra hash e versão. O hash é determinístico
— calculado a partir do conteúdo ordenado dos pontos, nunca de metadados
voláteis como `created_at`. Duas ingestões idênticas produzem o mesmo hash;
qualquer mudança de conteúdo produz um hash diferente, permitindo detectar
dataset alterado silenciosamente.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from .data_models import DatasetStage, DatasetVersion, ValidatedPricePoint
from .errors import DatasetVersionError


def compute_content_hash(points: tuple[ValidatedPricePoint, ...]) -> str:
    """Calcula um hash SHA-256 determinístico do conteúdo dos pontos."""
    digest = hashlib.sha256()
    for point in points:
        row = "|".join(
            (
                point.broker,
                point.asset,
                point.timeframe,
                point.timestamp.isoformat(),
                repr(point.price),
                point.source,
            )
        )
        digest.update(row.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def build_dataset_version(
    dataset_id: str,
    version: int,
    points: tuple[ValidatedPricePoint, ...],
    stage: DatasetStage,
) -> DatasetVersion:
    """Constrói o metadado de versão a partir do conteúdo real do dataset."""
    if version < 1:
        raise DatasetVersionError("version deve começar em 1")
    if not points:
        raise DatasetVersionError("dataset vazio não pode ser versionado")

    brokers = {point.broker for point in points}
    assets = {point.asset for point in points}
    timeframes = {point.timeframe for point in points}
    if len(brokers) > 1 or len(assets) > 1 or len(timeframes) > 1:
        raise DatasetVersionError(
            "dataset não pode misturar broker/asset/timeframe diferentes em uma versão"
        )

    timestamps = [point.timestamp for point in points]
    return DatasetVersion(
        dataset_id=dataset_id,
        version=version,
        content_hash=compute_content_hash(points),
        broker=brokers.pop(),
        asset=assets.pop(),
        timeframe=timeframes.pop(),
        stage=stage,
        point_count=len(points),
        coverage_start=min(timestamps),
        coverage_end=max(timestamps),
        created_at=datetime.now(UTC),
    )
