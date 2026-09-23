"""Persistência SQLite append-only para o Data Engine (Fase 2).

Segue o mesmo padrão de `persistence.SQLiteStore`: histórico nunca é
sobrescrito, versões de dataset são imutáveis, e pontos rejeitados são
preservados para auditoria (nunca descartados silenciosamente).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from threading import RLock

from .data_models import DatasetStage, DatasetVersion, QualityReport, ValidatedPricePoint
from .errors import DatasetVersionError, PersistenceError
from .logging import sanitize


_DATASET_GUARD_TRIGGERS = """
DROP TRIGGER IF EXISTS forbid_dataset_version_update;
DROP TRIGGER IF EXISTS forbid_dataset_version_delete;
DROP TRIGGER IF EXISTS forbid_dataset_points_update;
DROP TRIGGER IF EXISTS forbid_dataset_points_delete;
DROP TRIGGER IF EXISTS forbid_quality_reports_update;
DROP TRIGGER IF EXISTS forbid_quality_reports_delete;

CREATE TRIGGER forbid_dataset_version_update
BEFORE UPDATE ON dataset_versions
BEGIN SELECT RAISE(ABORT, 'dataset_versions is append-only'); END;

CREATE TRIGGER forbid_dataset_version_delete
BEFORE DELETE ON dataset_versions
BEGIN SELECT RAISE(ABORT, 'dataset_versions is append-only'); END;

CREATE TRIGGER forbid_dataset_points_update
BEFORE UPDATE ON dataset_points
BEGIN SELECT RAISE(ABORT, 'dataset_points is append-only'); END;

CREATE TRIGGER forbid_dataset_points_delete
BEFORE DELETE ON dataset_points
BEGIN SELECT RAISE(ABORT, 'dataset_points is append-only'); END;

CREATE TRIGGER forbid_quality_reports_update
BEFORE UPDATE ON quality_reports
BEGIN SELECT RAISE(ABORT, 'quality_reports is append-only'); END;

CREATE TRIGGER forbid_quality_reports_delete
BEFORE DELETE ON quality_reports
BEGIN SELECT RAISE(ABORT, 'quality_reports is append-only'); END;
"""


class DatasetStore:
    """Armazena versões de dataset, pontos validados e relatórios de qualidade."""

    def __init__(self, database_path: Path | str = ":memory:") -> None:
        self._connection = sqlite3.connect(str(database_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = RLock()
        self._initialize_schema()

    def close(self) -> None:
        """Fecha a conexão local."""
        self._connection.close()

    def append_dataset_version(
        self,
        version: DatasetVersion,
        points: tuple[ValidatedPricePoint, ...],
        report: QualityReport,
    ) -> None:
        """Registra uma nova versão imutável, seus pontos e o relatório de qualidade.

        Rejeita a gravação se `dataset_id` + `version` já existir (nunca
        sobrescreve) e rejeita se o hash não corresponder aos pontos
        fornecidos (protege contra dataset corrompido silenciosamente).
        """
        from .data_versioning import compute_content_hash

        if compute_content_hash(points) != version.content_hash:
            raise DatasetVersionError(
                "hash informado não corresponde ao conteúdo dos pontos"
            )

        try:
            with self._transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO dataset_versions(
                        dataset_id, version, content_hash, broker, asset,
                        timeframe, stage, point_count, coverage_start,
                        coverage_end, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        version.dataset_id,
                        version.version,
                        version.content_hash,
                        version.broker,
                        version.asset,
                        version.timeframe,
                        version.stage.value,
                        version.point_count,
                        version.coverage_start.isoformat(),
                        version.coverage_end.isoformat(),
                        version.created_at.isoformat(),
                    ),
                )
                for point in points:
                    connection.execute(
                        """
                        INSERT INTO dataset_points(
                            dataset_id, version, broker, asset, timeframe,
                            timestamp, price, source
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            version.dataset_id,
                            version.version,
                            point.broker,
                            point.asset,
                            point.timeframe,
                            point.timestamp.isoformat(),
                            point.price,
                            point.source,
                        ),
                    )
                connection.execute(
                    """
                    INSERT INTO quality_reports(
                        dataset_id, version, total_input, total_accepted,
                        total_rejected, duplicates_removed, gaps_json,
                        duplicates_json, rejections_json, generated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        version.dataset_id,
                        version.version,
                        report.total_input,
                        report.total_accepted,
                        report.total_rejected,
                        report.duplicates_removed,
                        json.dumps(_gaps_to_json(report), sort_keys=True, default=str),
                        json.dumps(_duplicates_to_json(report), sort_keys=True, default=str),
                        json.dumps(
                            sanitize(_rejections_to_json(report)),
                            sort_keys=True,
                            default=str,
                        ),
                        report.generated_at.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise PersistenceError(
                "dataset_id + version já existe e não pode ser sobrescrito"
            ) from error
        except sqlite3.DatabaseError as error:
            raise PersistenceError("falha ao registrar versão de dataset") from error

    def load_dataset_version(self, dataset_id: str, version: int) -> DatasetVersion | None:
        """Carrega o metadado de uma versão específica."""
        with self._lock:
            row = self._connection.execute(
                """
                SELECT * FROM dataset_versions
                WHERE dataset_id = ? AND version = ?
                """,
                (dataset_id, version),
            ).fetchone()
        return _version_from_row(row) if row is not None else None

    def latest_version_number(self, dataset_id: str) -> int:
        """Retorna a maior versão já registrada para um dataset, ou 0 se inexistente."""
        with self._lock:
            row = self._connection.execute(
                "SELECT MAX(version) AS max_version FROM dataset_versions WHERE dataset_id = ?",
                (dataset_id,),
            ).fetchone()
        return int(row["max_version"]) if row and row["max_version"] is not None else 0

    def load_points(self, dataset_id: str, version: int) -> tuple[ValidatedPricePoint, ...]:
        """Carrega, em ordem cronológica, os pontos de uma versão."""
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM dataset_points
                WHERE dataset_id = ? AND version = ?
                ORDER BY timestamp ASC
                """,
                (dataset_id, version),
            ).fetchall()
        return tuple(_point_from_row(row) for row in rows)

    def list_versions(self, dataset_id: str) -> tuple[DatasetVersion, ...]:
        """Lista todas as versões conhecidas de um dataset, em ordem crescente."""
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM dataset_versions
                WHERE dataset_id = ?
                ORDER BY version ASC
                """,
                (dataset_id,),
            ).fetchall()
        return tuple(_version_from_row(row) for row in rows)

    def _initialize_schema(self) -> None:
        with self._transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS dataset_versions (
                    dataset_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    broker TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    point_count INTEGER NOT NULL,
                    coverage_start TEXT NOT NULL,
                    coverage_end TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (dataset_id, version)
                );
                CREATE TABLE IF NOT EXISTS dataset_points (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dataset_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    broker TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    price REAL NOT NULL,
                    source TEXT NOT NULL,
                    FOREIGN KEY (dataset_id, version)
                        REFERENCES dataset_versions(dataset_id, version)
                );
                CREATE TABLE IF NOT EXISTS quality_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dataset_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    total_input INTEGER NOT NULL,
                    total_accepted INTEGER NOT NULL,
                    total_rejected INTEGER NOT NULL,
                    duplicates_removed INTEGER NOT NULL,
                    gaps_json TEXT NOT NULL,
                    duplicates_json TEXT NOT NULL,
                    rejections_json TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    FOREIGN KEY (dataset_id, version)
                        REFERENCES dataset_versions(dataset_id, version)
                );
                """
            )
            # Recriados a cada inicialização para que um banco antigo nunca
            # fique com uma versão desatualizada das barreiras append-only.
            connection.executescript(_DATASET_GUARD_TRIGGERS)

    def _transaction(self) -> _Transaction:
        return _Transaction(self._connection, self._lock)


class _Transaction:
    """Context manager para transações imediatas com commit/rollback."""

    def __init__(self, connection: sqlite3.Connection, lock: RLock) -> None:
        self._connection = connection
        self._lock = lock

    def __enter__(self) -> sqlite3.Connection:
        self._lock.acquire()
        try:
            self._connection.execute("BEGIN IMMEDIATE")
        except BaseException:
            self._lock.release()
            raise
        return self._connection

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        try:
            if exc_type is None:
                self._connection.commit()
            else:
                self._connection.rollback()
        finally:
            self._lock.release()


def _gaps_to_json(report: QualityReport) -> list[dict[str, object]]:
    return [
        {
            "broker": gap.broker,
            "asset": gap.asset,
            "timeframe": gap.timeframe,
            "previous_timestamp": gap.previous_timestamp.isoformat(),
            "next_timestamp": gap.next_timestamp.isoformat(),
            "expected_interval_seconds": gap.expected_interval_seconds,
            "actual_gap_seconds": gap.actual_gap_seconds,
        }
        for gap in report.gaps
    ]


def _duplicates_to_json(report: QualityReport) -> list[dict[str, object]]:
    return [
        {
            "broker": duplicate.broker,
            "asset": duplicate.asset,
            "timeframe": duplicate.timeframe,
            "timestamp": duplicate.timestamp.isoformat(),
            "occurrences": duplicate.occurrences,
        }
        for duplicate in report.duplicates
    ]


def _rejections_to_json(report: QualityReport) -> list[dict[str, object]]:
    return [
        {
            "reason": rejection.reason,
            "raw_payload": dict(rejection.raw_payload),
            "detected_at": rejection.detected_at.isoformat(),
        }
        for rejection in report.rejections
    ]


def _version_from_row(row: sqlite3.Row) -> DatasetVersion:
    return DatasetVersion(
        dataset_id=row["dataset_id"],
        version=row["version"],
        content_hash=row["content_hash"],
        broker=row["broker"],
        asset=row["asset"],
        timeframe=row["timeframe"],
        stage=DatasetStage(row["stage"]),
        point_count=row["point_count"],
        coverage_start=_parse_timestamp(row["coverage_start"]),
        coverage_end=_parse_timestamp(row["coverage_end"]),
        created_at=_parse_timestamp(row["created_at"]),
    )


def _point_from_row(row: sqlite3.Row) -> ValidatedPricePoint:
    return ValidatedPricePoint(
        broker=row["broker"],
        asset=row["asset"],
        timeframe=row["timeframe"],
        timestamp=_parse_timestamp(row["timestamp"]),
        price=row["price"],
        source=row["source"],
    )


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)
