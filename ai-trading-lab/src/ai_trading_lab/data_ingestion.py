"""Pipeline de ingestão do Data Engine: RAW → VALIDATED → PROCESSED.

Nenhuma etapa deste pipeline inventa dados, envia operações ou se conecta a
uma corretora real. A entrada (`RawPricePoint`) é assumida como já capturada
por um processo externo (fora de escopo desta fase, conforme ADR-005) —
este módulo apenas valida, versiona e persiste o que foi recebido.

Datasets inválidos (sem nenhum ponto aceito) são rejeitados explicitamente,
nunca persistidos como se fossem válidos.
"""

from __future__ import annotations

from dataclasses import dataclass

from .data_models import (
    DatasetStage,
    DatasetVersion,
    QualityReport,
    RawPricePoint,
    ValidatedPricePoint,
)
from .data_persistence import DatasetStore
from .data_validation import validate_and_normalize
from .data_versioning import build_dataset_version
from .errors import DataQualityError


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Resultado de uma ingestão completa: versão registrada + relatório."""

    dataset_version: DatasetVersion
    points: tuple[ValidatedPricePoint, ...]
    report: QualityReport


def ingest_raw_batch(
    store: DatasetStore,
    dataset_id: str,
    raw_points: tuple[RawPricePoint, ...],
    *,
    stage: DatasetStage = DatasetStage.VALIDATED,
    expected_interval_seconds: float | None = None,
) -> IngestionResult:
    """Executa RAW → VALIDATED (ou PROCESSED) e persiste uma nova versão.

    Rejeita o lote inteiro (sem persistir nada) se nenhum ponto sobreviver à
    validação — um dataset sem pontos válidos não é uma versão utilizável e
    não deve ser registrado como se fosse.
    """
    normalized_points, report = validate_and_normalize(
        raw_points, expected_interval_seconds=expected_interval_seconds
    )

    if not normalized_points:
        raise DataQualityError(
            f"dataset '{dataset_id}' rejeitado: nenhum ponto válido após "
            f"validação ({report.total_rejected} de {report.total_input} rejeitados)"
        )

    next_version = store.latest_version_number(dataset_id) + 1
    version = build_dataset_version(dataset_id, next_version, normalized_points, stage)

    store.append_dataset_version(version, normalized_points, report)

    return IngestionResult(dataset_version=version, points=normalized_points, report=report)


def promote_to_processed(
    store: DatasetStore,
    dataset_id: str,
    source_version: int,
) -> IngestionResult:
    """Cria uma nova versão PROCESSED a partir de uma versão VALIDATED existente.

    Não transforma os dados (nenhuma normalização adicional é aplicada aqui
    — isso fica para agentes futuros de feature engineering, fora de escopo
    desta fase). Apenas formaliza a transição de estágio com uma nova versão
    imutável e um relatório de qualidade vazio (sem novas rejeições).
    """
    existing = store.load_dataset_version(dataset_id, source_version)
    if existing is None:
        raise DataQualityError(
            f"versão {source_version} do dataset '{dataset_id}' não encontrada"
        )
    if existing.stage is not DatasetStage.VALIDATED:
        raise DataQualityError(
            f"apenas datasets VALIDATED podem ser promovidos a PROCESSED "
            f"(versão {source_version} está em {existing.stage.value})"
        )

    points = store.load_points(dataset_id, source_version)
    next_version = store.latest_version_number(dataset_id) + 1
    version = build_dataset_version(dataset_id, next_version, points, DatasetStage.PROCESSED)

    empty_report = QualityReport(
        total_input=len(points),
        total_accepted=len(points),
        total_rejected=0,
        duplicates_removed=0,
        gaps=(),
        duplicates=(),
        rejections=(),
    )
    store.append_dataset_version(version, points, empty_report)

    return IngestionResult(dataset_version=version, points=points, report=empty_report)
