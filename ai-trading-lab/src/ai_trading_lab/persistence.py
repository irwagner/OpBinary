"""Persistência SQLite local e auditável para a Fase 1."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from threading import RLock

from .authorization import AuthorizationPolicy, Capability
from .errors import (
    ConcurrentStateUpdate,
    InvalidStateTransition,
    PermissionDeniedError,
    PersistenceError,
    PromotionApprovalRequired,
    PromotionRequestError,
)
from .logging import sanitize
from .models import (
    Actor,
    AuditEvent,
    Experiment,
    PromotionRequest,
    PromotionStatus,
    StrategyStateSnapshot,
    StrategyStatus,
    SystemStateSnapshot,
    SystemStatus,
)
from .transitions import validate_strategy_transition, validate_system_transition


GUARD_SCHEMA_VERSION = "2"

_GUARD_TRIGGERS = """
DROP TRIGGER IF EXISTS forbid_invalid_system_transition;
DROP TRIGGER IF EXISTS forbid_invalid_strategy_transition;
DROP TRIGGER IF EXISTS forbid_real_without_approval;
DROP TRIGGER IF EXISTS forbid_audit_update;
DROP TRIGGER IF EXISTS forbid_audit_delete;
DROP TRIGGER IF EXISTS forbid_experiment_update;
DROP TRIGGER IF EXISTS forbid_experiment_delete;

CREATE TRIGGER forbid_invalid_system_transition
BEFORE UPDATE ON system_state
WHEN NOT (
    (OLD.status <> 'EMERGENCY_STOPPED' AND NEW.status = 'EMERGENCY_STOPPED')
    -- Saída do emergency stop só para STOPPED, e apenas pelo caminho humano
    -- dedicado (clear_emergency_stop). Nenhum agente alcança esta transição.
    OR (OLD.status = 'EMERGENCY_STOPPED' AND NEW.status = 'STOPPED')
    OR (OLD.status = 'IDLE' AND NEW.status IN ('RUNNING', 'STOPPED'))
    OR (OLD.status = 'RUNNING' AND NEW.status IN ('PAUSED', 'ERROR', 'STOPPED'))
    OR (OLD.status = 'PAUSED' AND NEW.status IN ('RUNNING', 'STOPPED'))
    OR (OLD.status = 'ERROR' AND NEW.status IN ('RUNNING', 'STOPPED'))
    OR (OLD.status = 'STOPPED' AND NEW.status = 'IDLE')
)
BEGIN SELECT RAISE(ABORT, 'invalid system transition'); END;

CREATE TRIGGER forbid_invalid_strategy_transition
BEFORE UPDATE ON strategy_state
WHEN NOT (
    (OLD.status = 'IDEA' AND NEW.status IN ('BACKTEST', 'REJECTED', 'NEEDS_RESEARCH'))
    OR (OLD.status = 'BACKTEST' AND NEW.status IN ('VALIDATION', 'REJECTED', 'NEEDS_RESEARCH'))
    OR (OLD.status = 'VALIDATION' AND NEW.status IN ('OUT_OF_SAMPLE', 'REJECTED', 'NEEDS_RESEARCH'))
    OR (OLD.status = 'OUT_OF_SAMPLE' AND NEW.status IN ('MONTE_CARLO', 'REJECTED', 'NEEDS_RESEARCH'))
    OR (OLD.status = 'MONTE_CARLO' AND NEW.status IN ('DEMO_CANDIDATE', 'REJECTED', 'NEEDS_RESEARCH'))
    OR (OLD.status = 'DEMO_CANDIDATE' AND NEW.status IN ('DEMO', 'REJECTED', 'NEEDS_RESEARCH'))
    OR (OLD.status = 'DEMO' AND NEW.status IN ('HUMAN_REVIEW', 'REJECTED', 'NEEDS_RESEARCH'))
    OR (OLD.status = 'HUMAN_REVIEW' AND NEW.status IN ('REAL', 'REJECTED', 'NEEDS_RESEARCH'))
)
BEGIN SELECT RAISE(ABORT, 'invalid strategy transition'); END;

CREATE TRIGGER forbid_real_without_approval
BEFORE UPDATE ON strategy_state
WHEN NEW.status = 'REAL' AND NOT EXISTS (
    SELECT 1 FROM promotion_requests
    WHERE strategy_id = NEW.strategy_id AND status = 'APPROVED'
)
BEGIN SELECT RAISE(ABORT, 'human approval required'); END;

CREATE TRIGGER forbid_audit_update
BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;

CREATE TRIGGER forbid_audit_delete
BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;

CREATE TRIGGER forbid_experiment_update
BEFORE UPDATE ON experiments
BEGIN SELECT RAISE(ABORT, 'experiments is append-only'); END;

CREATE TRIGGER forbid_experiment_delete
BEFORE DELETE ON experiments
BEGIN SELECT RAISE(ABORT, 'experiments is append-only'); END;
"""


class SQLiteStore:
    """Armazena estado e auditoria sem credenciais ou conexões externas."""

    def __init__(self, database_path: Path | str = ":memory:") -> None:
        self._connection = sqlite3.connect(str(database_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._lock = RLock()
        self._authorization = AuthorizationPolicy()
        self._initialize_schema()

    def close(self) -> None:
        """Fecha a conexão local."""
        self._connection.close()

    def load_system_state(self) -> SystemStateSnapshot | None:
        """Retorna o estado global salvo, se existir."""
        with self._lock:
            row = self._connection.execute(
                "SELECT status, updated_at, reason FROM system_state WHERE singleton_id = 1"
            ).fetchone()
        return _system_state_from_row(row) if row is not None else None

    def initialize_system_state(
        self, snapshot: SystemStateSnapshot, event: AuditEvent
    ) -> SystemStateSnapshot:
        """Inicializa o singleton sem sobrescrever inicialização concorrente."""
        if snapshot.status is not SystemStatus.IDLE:
            raise InvalidStateTransition("estado global deve iniciar em IDLE")
        try:
            with self._transaction() as connection:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO system_state(singleton_id, status, updated_at, reason)
                    VALUES (1, ?, ?, ?)
                    """,
                    (snapshot.status.value, snapshot.updated_at.isoformat(), snapshot.reason),
                )
                if cursor.rowcount == 1:
                    _insert_audit_event(connection, event)
                row = connection.execute(
                    "SELECT status, updated_at, reason FROM system_state WHERE singleton_id = 1"
                ).fetchone()
                if row is None:
                    raise PersistenceError("não foi possível inicializar o estado global")
                return _system_state_from_row(row)
        except sqlite3.DatabaseError as error:
            raise PersistenceError("falha ao inicializar o estado global") from error

    def transition_system_state(
        self,
        expected_status: SystemStatus,
        snapshot: SystemStateSnapshot,
        event: AuditEvent,
        *,
        actor: Actor,
    ) -> None:
        """Valida, compara, muda e audita o estado em uma transação."""
        self._require(actor, Capability.MANAGE_SYSTEM_STATE)
        validate_system_transition(expected_status, snapshot.status)
        try:
            with self._transaction() as connection:
                cursor = connection.execute(
                    """
                    UPDATE system_state
                    SET status = ?, updated_at = ?, reason = ?
                    WHERE singleton_id = 1 AND status = ?
                    """,
                    (
                        snapshot.status.value,
                        snapshot.updated_at.isoformat(),
                        snapshot.reason,
                        expected_status.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ConcurrentStateUpdate(
                        "estado global mudou durante a transição"
                    )
                _insert_audit_event(connection, event)
        except sqlite3.DatabaseError as error:
            raise PersistenceError("falha na transição atômica de estado") from error

    def emergency_stop_system(
        self,
        snapshot: SystemStateSnapshot,
        event: AuditEvent,
        *,
        actor: Actor,
    ) -> SystemStateSnapshot:
        """Faz o emergency stop vencer qualquer estado atual de modo atômico."""
        self._require(actor, Capability.EMERGENCY_STOP)
        if snapshot.status is not SystemStatus.EMERGENCY_STOPPED:
            raise InvalidStateTransition(
                "emergency_stop_system aceita apenas EMERGENCY_STOPPED"
            )
        try:
            with self._transaction() as connection:
                row = connection.execute(
                    "SELECT status, updated_at, reason FROM system_state WHERE singleton_id = 1"
                ).fetchone()
                if row is None:
                    raise PersistenceError("estado global não inicializado")
                current = _system_state_from_row(row)
                if current.status is SystemStatus.EMERGENCY_STOPPED:
                    return current
                cursor = connection.execute(
                    """
                    UPDATE system_state
                    SET status = ?, updated_at = ?, reason = ?
                    WHERE singleton_id = 1 AND status = ?
                    """,
                    (
                        snapshot.status.value,
                        snapshot.updated_at.isoformat(),
                        snapshot.reason,
                        current.status.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ConcurrentStateUpdate(
                        "estado global mudou durante o emergency stop"
                    )
                audited_event = replace(
                    event,
                    payload={
                        **event.payload,
                        "previous_status": current.status.value,
                    },
                )
                _insert_audit_event(connection, audited_event)
                return snapshot
        except sqlite3.DatabaseError as error:
            raise PersistenceError("falha no emergency stop atômico") from error

    def clear_emergency_stop(
        self,
        snapshot: SystemStateSnapshot,
        event: AuditEvent,
        *,
        actor: Actor,
    ) -> SystemStateSnapshot:
        """Caminho humano dedicado para sair de EMERGENCY_STOPPED para STOPPED.

        Não reativa o sistema: leva a STOPPED, exigindo um segundo passo
        deliberado para voltar a operar. Nenhum agente possui esta capacidade.
        """
        self._require(actor, Capability.CLEAR_EMERGENCY_STOP)
        if snapshot.status is not SystemStatus.STOPPED:
            raise InvalidStateTransition("clear_emergency_stop deve levar a STOPPED")
        try:
            with self._transaction() as connection:
                cursor = connection.execute(
                    """
                    UPDATE system_state
                    SET status = ?, updated_at = ?, reason = ?
                    WHERE singleton_id = 1 AND status = ?
                    """,
                    (
                        snapshot.status.value,
                        snapshot.updated_at.isoformat(),
                        snapshot.reason,
                        SystemStatus.EMERGENCY_STOPPED.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise InvalidStateTransition(
                        "sistema não está em EMERGENCY_STOPPED"
                    )
                _insert_audit_event(connection, event)
                return snapshot
        except sqlite3.DatabaseError as error:
            raise PersistenceError("falha ao limpar emergency stop") from error

    def load_strategy_state(self, strategy_id: str) -> StrategyStateSnapshot | None:
        """Retorna o estado atual de uma estratégia."""
        with self._lock:
            row = self._connection.execute(
                """
                SELECT strategy_id, status, updated_at, reason
                FROM strategy_state WHERE strategy_id = ?
                """,
                (strategy_id,),
            ).fetchone()
        return _strategy_state_from_row(row) if row is not None else None

    def initialize_strategy_state(
        self,
        snapshot: StrategyStateSnapshot,
        event: AuditEvent,
        *,
        actor: Actor,
    ) -> None:
        """Cria o estado IDEA por autorização do Supervisor."""
        self._require(actor, Capability.INITIALIZE_STRATEGY)
        if snapshot.status is not StrategyStatus.IDEA:
            raise InvalidStateTransition("estratégia deve iniciar em IDEA")
        try:
            with self._transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO strategy_state(strategy_id, status, updated_at, reason)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        snapshot.strategy_id,
                        snapshot.status.value,
                        snapshot.updated_at.isoformat(),
                        snapshot.reason,
                    ),
                )
                _insert_audit_event(connection, event)
        except sqlite3.IntegrityError as error:
            raise PersistenceError("strategy_id já possui estado") from error
        except sqlite3.DatabaseError as error:
            raise PersistenceError("falha ao inicializar estado da estratégia") from error

    def transition_strategy_state(
        self,
        expected_status: StrategyStatus,
        snapshot: StrategyStateSnapshot,
        event: AuditEvent,
        *,
        actor: Actor,
    ) -> None:
        """Valida autorização, sequência, aprovação e CAS no mesmo limite."""
        self._require(actor, Capability.TRANSITION_STRATEGY)
        validate_strategy_transition(expected_status, snapshot.status)
        try:
            with self._transaction() as connection:
                if snapshot.status is StrategyStatus.REAL:
                    approved = connection.execute(
                        """
                        SELECT 1 FROM promotion_requests
                        WHERE strategy_id = ? AND status = ? LIMIT 1
                        """,
                        (snapshot.strategy_id, PromotionStatus.APPROVED.value),
                    ).fetchone()
                    if approved is None:
                        raise PromotionApprovalRequired(
                            "REAL exige aprovação humana persistida"
                        )
                cursor = connection.execute(
                    """
                    UPDATE strategy_state
                    SET status = ?, updated_at = ?, reason = ?
                    WHERE strategy_id = ? AND status = ?
                    """,
                    (
                        snapshot.status.value,
                        snapshot.updated_at.isoformat(),
                        snapshot.reason,
                        snapshot.strategy_id,
                        expected_status.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ConcurrentStateUpdate(
                        "estado da estratégia mudou durante a transição"
                    )
                _insert_audit_event(connection, event)
        except sqlite3.DatabaseError as error:
            raise PersistenceError("falha na transição da estratégia") from error

    def append_promotion_request(
        self,
        request: PromotionRequest,
        event: AuditEvent,
        *,
        actor: Actor,
    ) -> None:
        """Registra solicitação pendente autorizada e auditada."""
        self._require(actor, Capability.REQUEST_REAL_PROMOTION)
        if request.status is not PromotionStatus.PENDING:
            raise PromotionRequestError("nova solicitação deve estar PENDING")
        try:
            with self._transaction() as connection:
                strategy = connection.execute(
                    "SELECT status FROM strategy_state WHERE strategy_id = ?",
                    (request.strategy_id,),
                ).fetchone()
                if strategy is None or strategy["status"] != StrategyStatus.HUMAN_REVIEW.value:
                    raise PromotionRequestError(
                        "promoção só pode ser solicitada em HUMAN_REVIEW"
                    )
                connection.execute(
                    """
                    INSERT INTO promotion_requests(
                        request_id, strategy_id, status, created_at,
                        decided_at, decided_by, reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request.request_id,
                        request.strategy_id,
                        request.status.value,
                        request.created_at.isoformat(),
                        None,
                        None,
                        request.reason,
                    ),
                )
                _insert_audit_event(connection, event)
        except sqlite3.IntegrityError as error:
            raise PromotionRequestError(
                "solicitação de promoção duplicada ou estratégia inexistente"
            ) from error
        except sqlite3.DatabaseError as error:
            raise PersistenceError("falha ao registrar solicitação de promoção") from error

    def load_promotion_request(self, request_id: str) -> PromotionRequest | None:
        """Retorna uma solicitação de promoção."""
        with self._lock:
            row = self._connection.execute(
                """
                SELECT request_id, strategy_id, status, created_at,
                       decided_at, decided_by, reason
                FROM promotion_requests WHERE request_id = ?
                """,
                (request_id,),
            ).fetchone()
        return _promotion_from_row(row) if row is not None else None

    def decide_promotion_request(
        self,
        request_id: str,
        status: PromotionStatus,
        decided_by: str,
        decided_at: datetime,
        reason: str | None,
        event: AuditEvent,
        *,
        actor: Actor,
    ) -> PromotionRequest:
        """Registra decisão humana e auditoria no mesmo commit."""
        self._require(actor, Capability.DECIDE_REAL_PROMOTION)
        if status not in {PromotionStatus.APPROVED, PromotionStatus.REJECTED}:
            raise PromotionRequestError("decisão deve ser APPROVED ou REJECTED")
        try:
            with self._transaction() as connection:
                cursor = connection.execute(
                    """
                    UPDATE promotion_requests
                    SET status = ?, decided_at = ?, decided_by = ?, reason = ?
                    WHERE request_id = ? AND status = ?
                    """,
                    (
                        status.value,
                        decided_at.isoformat(),
                        decided_by,
                        reason,
                        request_id,
                        PromotionStatus.PENDING.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise PromotionRequestError(
                        "solicitação inexistente ou já decidida"
                    )
                _insert_audit_event(connection, event)
                row = connection.execute(
                    """
                    SELECT request_id, strategy_id, status, created_at,
                           decided_at, decided_by, reason
                    FROM promotion_requests WHERE request_id = ?
                    """,
                    (request_id,),
                ).fetchone()
                if row is None:
                    raise PromotionRequestError("solicitação não encontrada")
                return _promotion_from_row(row)
        except sqlite3.DatabaseError as error:
            raise PersistenceError("falha ao decidir solicitação de promoção") from error

    def load_experiment_parameters(
        self, dataset_prefix: str | None = None
    ) -> tuple[dict[str, object], ...]:
        """Devolve os parâmetros de todos os experimentos já registrados.

        Permite reconstruir quais combinações de regra já foram testadas depois
        de um restart, evitando que uma campanha longa recomece do zero.
        """
        query = "SELECT parameters_json, dataset_id FROM experiments"
        params: tuple[object, ...] = ()
        if dataset_prefix:
            query += " WHERE dataset_id LIKE ?"
            params = (f"{dataset_prefix}%",)
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()

        parameters: list[dict[str, object]] = []
        for row in rows:
            try:
                decoded = json.loads(row["parameters_json"])
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(decoded, dict):
                parameters.append(decoded)
        return tuple(parameters)

    def latest_strategy_sequence(self) -> int:
        """Maior sequência de strategy_id já persistida, ou 0 se não houver.

        Permite retomar a numeração após restart sem colidir com IDs existentes.
        """
        return self._max_sequence(
            "SELECT MAX(CAST(SUBSTR(strategy_id, 5) AS INTEGER)) AS seq "
            "FROM strategy_state WHERE strategy_id LIKE 'HYP-%'"
        )

    def latest_experiment_sequence(self) -> int:
        """Maior sequência de experiment_id já persistida, ou 0 se não houver."""
        return self._max_sequence(
            "SELECT MAX(CAST(SUBSTR(experiment_id, 5) AS INTEGER)) AS seq "
            "FROM experiments WHERE experiment_id LIKE 'EXP-%'"
        )

    def _max_sequence(self, query: str) -> int:
        with self._lock:
            row = self._connection.execute(query).fetchone()
        if row is None or row["seq"] is None:
            return 0
        return int(row["seq"])

    def has_approved_promotion(self, strategy_id: str) -> bool:
        """Verifica aprovação humana persistida para uma estratégia."""
        with self._lock:
            row = self._connection.execute(
                """
                SELECT 1 FROM promotion_requests
                WHERE strategy_id = ? AND status = ? LIMIT 1
                """,
                (strategy_id, PromotionStatus.APPROVED.value),
            ).fetchone()
        return row is not None

    def append_audit_event(self, event: AuditEvent) -> int:
        """Insere evento imutável e sanitizado na trilha de auditoria."""
        try:
            with self._transaction() as connection:
                return _insert_audit_event(connection, event)
        except sqlite3.DatabaseError as error:
            raise PersistenceError("falha ao registrar auditoria") from error

    def list_audit_events(self) -> tuple[sqlite3.Row, ...]:
        """Lista eventos somente para inspeção/auditoria."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM audit_events ORDER BY event_id"
            ).fetchall()
        return tuple(rows)

    def append_experiment(self, experiment: Experiment) -> None:
        """Insere experimento uma única vez; histórico não é sobrescrito."""
        try:
            with self._transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO experiments(
                        experiment_id, strategy_id, dataset_id, software_version,
                        agent_version, created_at, parameters_json, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        experiment.experiment_id,
                        experiment.strategy_id,
                        experiment.dataset_id,
                        experiment.software_version,
                        experiment.agent_version,
                        experiment.created_at.isoformat(),
                        json.dumps(experiment.parameters, sort_keys=True, default=str),
                        experiment.status,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise PersistenceError(
                "experiment_id já existe e não pode ser sobrescrito"
            ) from error

    def _require(self, actor: Actor, capability: Capability) -> None:
        try:
            self._authorization.require(actor, capability)
        except PermissionDeniedError:
            self.append_audit_event(
                AuditEvent(
                    event_type="permission_denied",
                    actor=actor.actor_id,
                    payload={
                        "actor_role": actor.role.value,
                        "capability": capability.value,
                    },
                )
            )
            raise

    def _initialize_schema(self) -> None:
        with self._transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS system_state (
                    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    reason TEXT
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    experiment_id TEXT
                );
                CREATE TABLE IF NOT EXISTS strategy_state (
                    strategy_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    reason TEXT
                );
                CREATE TABLE IF NOT EXISTS promotion_requests (
                    request_id TEXT PRIMARY KEY,
                    strategy_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    decided_at TEXT,
                    decided_by TEXT,
                    reason TEXT,
                    FOREIGN KEY(strategy_id) REFERENCES strategy_state(strategy_id)
                );
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    strategy_id TEXT NOT NULL,
                    dataset_id TEXT NOT NULL,
                    software_version TEXT NOT NULL,
                    agent_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            # Triggers são regras derivadas do código, não dados do usuário.
            # São recriados a cada inicialização para que um banco antigo nunca
            # continue rodando com uma versão desatualizada das barreiras.
            connection.executescript(_GUARD_TRIGGERS)
            connection.execute(
                """
                INSERT INTO schema_meta(key, value) VALUES ('guard_schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (GUARD_SCHEMA_VERSION,),
            )

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


def _insert_audit_event(connection: sqlite3.Connection, event: AuditEvent) -> int:
    safe_payload = sanitize(event.payload)
    cursor = connection.execute(
        """
        INSERT INTO audit_events(event_type, actor, payload, timestamp, experiment_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            str(sanitize(event.event_type)),
            str(sanitize(event.actor)),
            json.dumps(safe_payload, sort_keys=True, default=str),
            event.timestamp.isoformat(),
            sanitize(event.experiment_id),
        ),
    )
    return int(cursor.lastrowid)


def _system_state_from_row(row: sqlite3.Row) -> SystemStateSnapshot:
    return SystemStateSnapshot(
        status=SystemStatus(row["status"]),
        updated_at=_parse_timestamp(row["updated_at"]),
        reason=row["reason"],
    )


def _strategy_state_from_row(row: sqlite3.Row) -> StrategyStateSnapshot:
    return StrategyStateSnapshot(
        strategy_id=row["strategy_id"],
        status=StrategyStatus(row["status"]),
        updated_at=_parse_timestamp(row["updated_at"]),
        reason=row["reason"],
    )


def _promotion_from_row(row: sqlite3.Row) -> PromotionRequest:
    return PromotionRequest(
        request_id=row["request_id"],
        strategy_id=row["strategy_id"],
        status=PromotionStatus(row["status"]),
        created_at=_parse_timestamp(row["created_at"]),
        decided_at=(
            _parse_timestamp(row["decided_at"]) if row["decided_at"] else None
        ),
        decided_by=row["decided_by"],
        reason=row["reason"],
    )


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)
