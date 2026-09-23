"""Regra de estratégia computável e geração de sinais (Fase 3).

A regra é objetiva e mensurável — nunca textual e nunca vaga (MASTER_SPEC
seção 11). A decisão em um instante `i` usa exclusivamente dados até `i`,
tornando look-ahead bias estruturalmente impossível (seções 24, 25).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .data_models import ValidatedPricePoint
from .errors import DataQualityError


class RuleMode(StrEnum):
    """Direção da regra em relação ao momento observado."""

    FOLLOW = "FOLLOW"
    REVERT = "REVERT"


class SignalDirection(StrEnum):
    """Direção da operação binária."""

    CALL = "CALL"
    PUT = "PUT"


@dataclass(frozen=True, slots=True)
class StrategyRule:
    """Regra determinística e reproduzível de entrada e expiração."""

    lookback: int
    threshold: float
    expiry_periods: int
    mode: RuleMode = RuleMode.FOLLOW

    def __post_init__(self) -> None:
        if self.lookback < 1:
            raise ValueError("lookback deve ser >= 1")
        if self.expiry_periods < 1:
            raise ValueError("expiry_periods deve ser >= 1")
        if self.threshold < 0:
            raise ValueError("threshold não pode ser negativo")

    @property
    def parameter_count(self) -> int:
        """Número de parâmetros livres — usado no controle de overfitting."""
        return 4

    def as_dict(self) -> dict[str, object]:
        """Representação serializável da regra."""
        return {
            "lookback": self.lookback,
            "threshold": self.threshold,
            "expiry_periods": self.expiry_periods,
            "mode": self.mode.value,
        }


@dataclass(frozen=True, slots=True)
class Signal:
    """Sinal gerado em um instante específico da série."""

    index: int
    timestamp: datetime
    direction: SignalDirection


def evaluate_at(
    points: tuple[ValidatedPricePoint, ...],
    index: int,
    rule: StrategyRule,
) -> SignalDirection | None:
    """Avalia a regra no instante `index` usando somente dados até `index`.

    A fatia é explicitamente truncada em `index + 1`: qualquer tentativa de
    ler o futuro resultaria em IndexError, não em um resultado silencioso.
    """
    if index < 0 or index >= len(points):
        raise IndexError("index fora da série")

    visible = points[: index + 1]
    if len(visible) <= rule.lookback:
        return None

    current_price = visible[-1].price
    past_price = visible[-1 - rule.lookback].price
    if past_price <= 0:
        raise DataQualityError("preço histórico não positivo impede avaliar a regra")

    momentum = (current_price - past_price) / past_price
    if abs(momentum) < rule.threshold:
        return None

    rising = momentum > 0
    if rule.mode is RuleMode.REVERT:
        rising = not rising
    return SignalDirection.CALL if rising else SignalDirection.PUT


def generate_signals(
    points: tuple[ValidatedPricePoint, ...],
    rule: StrategyRule,
) -> tuple[Signal, ...]:
    """Gera todos os sinais da série, respeitando a barreira temporal."""
    signals: list[Signal] = []
    last_resolvable = len(points) - rule.expiry_periods
    for index in range(len(points)):
        if index >= last_resolvable:
            break
        direction = evaluate_at(points, index, rule)
        if direction is not None:
            signals.append(
                Signal(index=index, timestamp=points[index].timestamp, direction=direction)
            )
    return tuple(signals)
