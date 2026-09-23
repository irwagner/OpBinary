"""Modelos imutáveis de domínio da Fase 1."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Mapping


class SystemStatus(StrEnum):
    """Estados globais permitidos pelo MASTER_SPEC."""

    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    ERROR = "ERROR"
    STOPPED = "STOPPED"
    EMERGENCY_STOPPED = "EMERGENCY_STOPPED"


class SystemMode(StrEnum):
    """Modos de operação previstos pela especificação."""

    RESEARCH = "RESEARCH"
    DEMO = "DEMO"
    REAL = "REAL"


class ActorRole(StrEnum):
    """Papéis confiáveis aceitos pelas fronteiras de autorização."""

    SYSTEM = "SYSTEM"
    SUPERVISOR = "SUPERVISOR"
    VALIDATOR = "VALIDATOR"
    HUMAN = "HUMAN"


class StrategyStatus(StrEnum):
    """Estados sequenciais de uma estratégia."""

    IDEA = "IDEA"
    BACKTEST = "BACKTEST"
    VALIDATION = "VALIDATION"
    OUT_OF_SAMPLE = "OUT_OF_SAMPLE"
    MONTE_CARLO = "MONTE_CARLO"
    DEMO_CANDIDATE = "DEMO_CANDIDATE"
    DEMO = "DEMO"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    REAL = "REAL"
    REJECTED = "REJECTED"
    NEEDS_RESEARCH = "NEEDS_RESEARCH"


class PromotionStatus(StrEnum):
    """Estados possíveis de uma solicitação de promoção."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


def utc_now() -> datetime:
    """Retorna timestamp UTC consciente de timezone."""
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Actor:
    """Identidade autenticada fornecida à camada de autorização."""

    actor_id: str
    role: ActorRole

    def __post_init__(self) -> None:
        if not self.actor_id.strip():
            raise ValueError("actor_id não pode ser vazio")


@dataclass(frozen=True, slots=True)
class SystemStateSnapshot:
    """Estado global persistível do sistema."""

    status: SystemStatus
    updated_at: datetime = field(default_factory=utc_now)
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class StrategyStateSnapshot:
    """Estado persistível de uma estratégia individual."""

    strategy_id: str
    status: StrategyStatus
    updated_at: datetime = field(default_factory=utc_now)
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PromotionRequest:
    """Solicitação persistida que depende de decisão humana explícita."""

    request_id: str
    strategy_id: str
    status: PromotionStatus = PromotionStatus.PENDING
    created_at: datetime = field(default_factory=utc_now)
    decided_at: datetime | None = None
    decided_by: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class Experiment:
    """Registro imutável mínimo de um experimento."""

    experiment_id: str
    strategy_id: str
    dataset_id: str
    software_version: str
    agent_version: str
    created_at: datetime = field(default_factory=utc_now)
    parameters: Mapping[str, object] = field(default_factory=dict)
    status: str = "CREATED"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Evento append-only usado para reconstruir decisões."""

    event_type: str
    actor: str
    payload: Mapping[str, object]
    timestamp: datetime = field(default_factory=utc_now)
    experiment_id: str | None = None
