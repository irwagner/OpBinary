"""Modelos imutáveis do Data Engine (Fase 2).

Nenhum destes modelos representa execução de operação ou integração com
corretora. Servem apenas para transportar pontos de preço já capturados
(por um processo externo, fora de escopo desta fase) através do pipeline
de ingestão, validação, deduplicação e split.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Mapping


class DatasetStage(StrEnum):
    """Estágios de dados previstos pela seção 12/19 da MASTER_SPEC."""

    RAW = "RAW"
    VALIDATED = "VALIDATED"
    PROCESSED = "PROCESSED"


class DatasetSplitKind(StrEnum):
    """Partições de dataset. Nunca podem se misturar."""

    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    TEST = "TEST"


@dataclass(frozen=True, slots=True)
class RawPricePoint:
    """Ponto de preço bruto, exatamente como recebido da fonte de captura.

    ``timestamp`` deve ser timezone-aware (nunca naive) — timezone explícito
    é uma regra obrigatória desta fase, não um valor assumido por padrão.
    """

    broker: str
    asset: str
    timeframe: str
    timestamp: datetime
    price: float
    source: str = "broker_capture"

    def __post_init__(self) -> None:
        if not self.broker.strip():
            raise ValueError("broker não pode ser vazio")
        if not self.asset.strip():
            raise ValueError("asset não pode ser vazio")
        if not self.timeframe.strip():
            raise ValueError("timeframe não pode ser vazio")
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp deve ser timezone-aware")


@dataclass(frozen=True, slots=True)
class ValidatedPricePoint:
    """Ponto de preço após passar por validação e normalização para UTC."""

    broker: str
    asset: str
    timeframe: str
    timestamp: datetime
    price: float
    source: str

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp deve ser timezone-aware")
        if self.timestamp.utcoffset() != UTC.utcoffset(self.timestamp):
            raise ValueError("timestamp validado deve estar normalizado em UTC")


@dataclass(frozen=True, slots=True)
class RejectedRecord:
    """Registro de um ponto rejeitado, preservado para auditoria (nunca descartado)."""

    reason: str
    raw_payload: Mapping[str, object]
    detected_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class GapFinding:
    """Lacuna detectada entre dois pontos consecutivos de uma série."""

    broker: str
    asset: str
    timeframe: str
    previous_timestamp: datetime
    next_timestamp: datetime
    expected_interval_seconds: float
    actual_gap_seconds: float


@dataclass(frozen=True, slots=True)
class DuplicateFinding:
    """Duplicata detectada (mesmo broker/asset/timeframe/timestamp)."""

    broker: str
    asset: str
    timeframe: str
    timestamp: datetime
    occurrences: int


@dataclass(frozen=True, slots=True)
class QualityReport:
    """Relatório de qualidade de uma etapa de ingestão/validação."""

    total_input: int
    total_accepted: int
    total_rejected: int
    duplicates_removed: int
    gaps: tuple[GapFinding, ...]
    duplicates: tuple[DuplicateFinding, ...]
    rejections: tuple[RejectedRecord, ...]
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_clean(self) -> bool:
        """Verdadeiro quando não há rejeições, gaps ou duplicatas remanescentes."""
        return not self.rejections and not self.gaps and not self.duplicates


@dataclass(frozen=True, slots=True)
class DatasetVersion:
    """Metadado imutável de uma versão de dataset, com hash de conteúdo."""

    dataset_id: str
    version: int
    content_hash: str
    broker: str
    asset: str
    timeframe: str
    stage: DatasetStage
    point_count: int
    coverage_start: datetime
    coverage_end: datetime
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class DatasetSplitPlan:
    """Percentuais de split, configuráveis, nunca hardcoded no código de negócio."""

    train_pct: float
    validation_pct: float
    test_pct: float

    def __post_init__(self) -> None:
        total = round(self.train_pct + self.validation_pct + self.test_pct, 6)
        if total != 1.0:
            raise ValueError("train_pct + validation_pct + test_pct deve somar 1.0")
        for name, value in (
            ("train_pct", self.train_pct),
            ("validation_pct", self.validation_pct),
            ("test_pct", self.test_pct),
        ):
            if not 0.0 < value < 1.0:
                raise ValueError(f"{name} deve estar entre 0 e 1")


DEFAULT_SPLIT_PLAN = DatasetSplitPlan(train_pct=0.6, validation_pct=0.2, test_pct=0.2)
