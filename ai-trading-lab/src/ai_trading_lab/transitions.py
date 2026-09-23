"""Invariantes compartilhadas das máquinas de estado."""

from __future__ import annotations

from .errors import InvalidStateTransition
from .models import StrategyStatus, SystemStatus

SYSTEM_TRANSITIONS: dict[SystemStatus, frozenset[SystemStatus]] = {
    SystemStatus.IDLE: frozenset({SystemStatus.RUNNING, SystemStatus.STOPPED}),
    SystemStatus.RUNNING: frozenset(
        {SystemStatus.PAUSED, SystemStatus.ERROR, SystemStatus.STOPPED}
    ),
    SystemStatus.PAUSED: frozenset({SystemStatus.RUNNING, SystemStatus.STOPPED}),
    SystemStatus.ERROR: frozenset({SystemStatus.RUNNING, SystemStatus.STOPPED}),
    SystemStatus.STOPPED: frozenset({SystemStatus.IDLE}),
    SystemStatus.EMERGENCY_STOPPED: frozenset(),
}

_STRATEGY_SEQUENCE = (
    StrategyStatus.IDEA,
    StrategyStatus.BACKTEST,
    StrategyStatus.VALIDATION,
    StrategyStatus.OUT_OF_SAMPLE,
    StrategyStatus.MONTE_CARLO,
    StrategyStatus.DEMO_CANDIDATE,
    StrategyStatus.DEMO,
    StrategyStatus.HUMAN_REVIEW,
    StrategyStatus.REAL,
)
STRATEGY_TRANSITIONS: dict[StrategyStatus, frozenset[StrategyStatus]] = {
    status: frozenset(
        {
            _STRATEGY_SEQUENCE[index + 1],
            StrategyStatus.REJECTED,
            StrategyStatus.NEEDS_RESEARCH,
        }
    )
    for index, status in enumerate(_STRATEGY_SEQUENCE[:-1])
}
STRATEGY_TRANSITIONS.update(
    {
        StrategyStatus.REAL: frozenset(),
        StrategyStatus.REJECTED: frozenset(),
        StrategyStatus.NEEDS_RESEARCH: frozenset(),
    }
)


def validate_system_transition(current: SystemStatus, target: SystemStatus) -> None:
    """Rejeita transições globais fora da allowlist."""
    if target not in SYSTEM_TRANSITIONS[current]:
        raise InvalidStateTransition(f"{current} não pode transicionar para {target}")


def validate_strategy_transition(
    current: StrategyStatus, target: StrategyStatus
) -> None:
    """Rejeita salto de etapa ou saída de estado terminal."""
    if target not in STRATEGY_TRANSITIONS[current]:
        raise InvalidStateTransition(f"{current} não pode transicionar para {target}")
