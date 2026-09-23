"""Identificadores e versionamento determinísticos."""

from __future__ import annotations

import re
from dataclasses import dataclass
from threading import Lock

from .errors import ExperimentIdentifierError

_EXPERIMENT_PATTERN = re.compile(r"^EXP-\d{6,}$")
_STRATEGY_PATTERN = re.compile(r"^HYP-\d{6,}(?:-v\d+)?$")
_VERSION_PATTERN = re.compile(r"^v\d+\.\d+\.\d+$")


@dataclass(frozen=True, slots=True)
class SoftwareVersion:
    """Versão semântica da aplicação, no formato vX.Y.Z."""

    value: str

    def __post_init__(self) -> None:
        if not _VERSION_PATTERN.fullmatch(self.value):
            raise ValueError("software_version deve usar o formato vX.Y.Z")


class ExperimentIdGenerator:
    """Gera IDs sequenciais thread-safe no formato EXP-000001."""

    def __init__(self, last_sequence: int = 0) -> None:
        if last_sequence < 0:
            raise ExperimentIdentifierError("last_sequence não pode ser negativo")
        self._sequence = last_sequence
        self._lock = Lock()

    def next_id(self) -> str:
        """Reserva e retorna o próximo ID único da sequência local."""
        with self._lock:
            self._sequence += 1
            return f"EXP-{self._sequence:06d}"

    @staticmethod
    def validate(value: str) -> str:
        """Valida e devolve um identificador de experimento."""
        if not _EXPERIMENT_PATTERN.fullmatch(value):
            raise ExperimentIdentifierError("ID deve usar o formato EXP-000001")
        return value


class StrategyIdGenerator:
    """Gera IDs sequenciais thread-safe no formato HYP-000001."""

    def __init__(self, last_sequence: int = 0) -> None:
        if last_sequence < 0:
            raise ExperimentIdentifierError("last_sequence não pode ser negativo")
        self._sequence = last_sequence
        self._lock = Lock()

    def next_id(self) -> str:
        """Reserva e retorna o próximo ID único de estratégia."""
        with self._lock:
            self._sequence += 1
            return f"HYP-{self._sequence:06d}"

    @staticmethod
    def validate(value: str) -> str:
        """Valida HYP-000001 e versões derivadas como HYP-000001-v2."""
        if not _STRATEGY_PATTERN.fullmatch(value):
            raise ExperimentIdentifierError("ID deve usar o formato HYP-000001")
        return value

    @staticmethod
    def next_version(strategy_id: str) -> str:
        """Deriva a próxima versão de uma estratégia sem apagar o histórico."""
        StrategyIdGenerator.validate(strategy_id)
        if "-v" not in strategy_id:
            return f"{strategy_id}-v2"
        base, _, current = strategy_id.rpartition("-v")
        return f"{base}-v{int(current) + 1}"
