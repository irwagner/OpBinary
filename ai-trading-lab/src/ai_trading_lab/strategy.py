"""Regras de estratégia computáveis e geração de sinais (Fase 3).

Toda regra é objetiva e mensurável — nunca textual e nunca vaga (MASTER_SPEC
seção 11). A decisão em um instante `i` usa exclusivamente dados até `i`,
tornando look-ahead bias estruturalmente impossível (seções 24, 25).

Famílias de sinal disponíveis:

- MOMENTUM     variação percentual sobre uma janela excede um limiar
- STREAK       N velas consecutivas da mesma cor
- ALTERNATION  as últimas N velas alternam de cor estritamente
- BODY_RATIO   corpo da vela grande em relação ao range (exige OHLC)

Cada família pode ser combinada com um filtro de horário (janela de horas UTC),
permitindo estudar se um horário específico se comporta de forma diferente.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .data_models import ValidatedPricePoint
from .errors import DataQualityError


class RuleMode(StrEnum):
    """Direção da regra em relação ao padrão observado."""

    FOLLOW = "FOLLOW"
    REVERT = "REVERT"


class SignalSource(StrEnum):
    """Família de padrão que origina o sinal."""

    MOMENTUM = "MOMENTUM"
    STREAK = "STREAK"
    ALTERNATION = "ALTERNATION"
    BODY_RATIO = "BODY_RATIO"


class SignalDirection(StrEnum):
    """Direção da operação binária."""

    CALL = "CALL"
    PUT = "PUT"


class CandleColor(StrEnum):
    """Cor da vela. DOJI é tratado como indefinido, nunca como alta ou baixa."""

    UP = "UP"
    DOWN = "DOWN"
    DOJI = "DOJI"


@dataclass(frozen=True, slots=True)
class StrategyRule:
    """Regra determinística e reproduzível de entrada e expiração."""

    lookback: int
    threshold: float
    expiry_periods: int
    mode: RuleMode = RuleMode.FOLLOW
    signal_source: SignalSource = SignalSource.MOMENTUM
    streak_length: int = 3
    hour_window: tuple[int, int] | None = None

    def __post_init__(self) -> None:
        if self.lookback < 1:
            raise ValueError("lookback deve ser >= 1")
        if self.expiry_periods < 1:
            raise ValueError("expiry_periods deve ser >= 1")
        if self.threshold < 0:
            raise ValueError("threshold não pode ser negativo")
        if self.streak_length < 1:
            raise ValueError("streak_length deve ser >= 1")
        if self.signal_source is SignalSource.ALTERNATION and self.lookback < 2:
            raise ValueError("ALTERNATION exige lookback >= 2")
        if self.hour_window is not None:
            start, end = self.hour_window
            if not (0 <= start <= 23 and 0 <= end <= 23):
                raise ValueError("hour_window deve usar horas entre 0 e 23")

    @property
    def parameter_count(self) -> int:
        """Parâmetros livres em uso — alimenta o controle de overfitting.

        Só conta o que a família de sinal realmente usa, para não penalizar uma
        regra por parâmetros que ela ignora.
        """
        count = 2  # expiry_periods e mode estão sempre em jogo
        if self.signal_source is SignalSource.MOMENTUM:
            count += 2  # lookback e threshold
        elif self.signal_source is SignalSource.STREAK:
            count += 1  # streak_length
        elif self.signal_source is SignalSource.ALTERNATION:
            count += 1  # lookback
        elif self.signal_source is SignalSource.BODY_RATIO:
            count += 1  # threshold
        if self.hour_window is not None:
            count += 1
        return count

    @property
    def minimum_history(self) -> int:
        """Quantidade mínima de velas anteriores necessária para decidir."""
        if self.signal_source is SignalSource.MOMENTUM:
            return self.lookback + 1
        if self.signal_source is SignalSource.STREAK:
            return self.streak_length + 1
        if self.signal_source is SignalSource.ALTERNATION:
            return self.lookback + 1
        return 1

    def as_dict(self) -> dict[str, object]:
        """Representação serializável da regra."""
        return {
            "lookback": self.lookback,
            "threshold": self.threshold,
            "expiry_periods": self.expiry_periods,
            "mode": self.mode.value,
            "signal_source": self.signal_source.value,
            "streak_length": self.streak_length,
            "hour_window": list(self.hour_window) if self.hour_window else None,
        }

    def describe(self) -> str:
        """Descrição legível da regra, para relatório."""
        window = (
            f", horário UTC {self.hour_window[0]:02d}h-{self.hour_window[1]:02d}h"
            if self.hour_window
            else ""
        )
        if self.signal_source is SignalSource.MOMENTUM:
            core = f"momentum de {self.lookback} velas >= {self.threshold:.4%}"
        elif self.signal_source is SignalSource.STREAK:
            core = f"{self.streak_length} velas consecutivas da mesma cor"
        elif self.signal_source is SignalSource.ALTERNATION:
            core = f"{self.lookback} velas alternando de cor"
        else:
            core = f"corpo da vela >= {self.threshold:.0%} do range"
        return f"{core}, {self.mode.value}, expira em {self.expiry_periods}{window}"


@dataclass(frozen=True, slots=True)
class Signal:
    """Sinal gerado em um instante específico da série."""

    index: int
    timestamp: datetime
    direction: SignalDirection


def candle_color(
    points: tuple[ValidatedPricePoint, ...], index: int
) -> CandleColor:
    """Cor da vela em `index`, usando OHLC quando disponível.

    Com abertura registrada, a cor é exata (fechamento versus abertura). Sem
    OHLC, é derivada do fechamento anterior — que é a melhor definição possível
    com o dado existente, e nunca uma suposição sobre valores ausentes.
    """
    if index < 0 or index >= len(points):
        raise IndexError("index fora da série")

    point = points[index]
    if point.open is not None:
        reference = point.open
    elif index == 0:
        return CandleColor.DOJI
    else:
        reference = points[index - 1].price

    if point.price > reference:
        return CandleColor.UP
    if point.price < reference:
        return CandleColor.DOWN
    return CandleColor.DOJI


def _direction_from_color(color: CandleColor, mode: RuleMode) -> SignalDirection | None:
    if color is CandleColor.DOJI:
        return None
    rising = color is CandleColor.UP
    if mode is RuleMode.REVERT:
        rising = not rising
    return SignalDirection.CALL if rising else SignalDirection.PUT


def _within_hour_window(moment: datetime, window: tuple[int, int] | None) -> bool:
    if window is None:
        return True
    start, end = window
    hour = moment.hour
    if start <= end:
        return start <= hour <= end
    # Janela que atravessa a meia-noite, ex: 22h-03h.
    return hour >= start or hour <= end


def _evaluate_momentum(
    points: tuple[ValidatedPricePoint, ...], index: int, rule: StrategyRule
) -> SignalDirection | None:
    current_price = points[index].price
    past_price = points[index - rule.lookback].price
    if past_price <= 0:
        raise DataQualityError("preço histórico não positivo impede avaliar a regra")

    momentum = (current_price - past_price) / past_price
    if abs(momentum) < rule.threshold:
        return None
    color = CandleColor.UP if momentum > 0 else CandleColor.DOWN
    return _direction_from_color(color, rule.mode)


def _evaluate_streak(
    points: tuple[ValidatedPricePoint, ...], index: int, rule: StrategyRule
) -> SignalDirection | None:
    last_color = candle_color(points, index)
    if last_color is CandleColor.DOJI:
        return None

    run = 0
    # Percorre para trás apenas o necessário: uma vela além da sequência
    # exigida já é suficiente para decidir.
    for offset in range(index, max(index - rule.streak_length, -1), -1):
        if candle_color(points, offset) is not last_color:
            break
        run += 1

    if run < rule.streak_length:
        return None
    return _direction_from_color(last_color, rule.mode)


def _evaluate_alternation(
    points: tuple[ValidatedPricePoint, ...], index: int, rule: StrategyRule
) -> SignalDirection | None:
    start = index - rule.lookback + 1
    if start < 0:
        return None

    previous: CandleColor | None = None
    last = CandleColor.DOJI
    for offset in range(start, index + 1):
        color = candle_color(points, offset)
        if color is CandleColor.DOJI:
            return None
        if previous is not None and previous is color:
            return None
        previous = color
        last = color

    # Em alternância estrita, a continuação do padrão inverte a última cor.
    expected = CandleColor.DOWN if last is CandleColor.UP else CandleColor.UP
    return _direction_from_color(expected, rule.mode)


def _evaluate_body_ratio(
    points: tuple[ValidatedPricePoint, ...], index: int, rule: StrategyRule
) -> SignalDirection | None:
    point = points[index]
    if point.open is None or point.high is None or point.low is None:
        return None
    candle_range = point.high - point.low
    if candle_range <= 0:
        return None
    body = abs(point.price - point.open)
    if body / candle_range < rule.threshold:
        return None
    return _direction_from_color(candle_color(points, index), rule.mode)


_EVALUATORS = {
    SignalSource.MOMENTUM: _evaluate_momentum,
    SignalSource.STREAK: _evaluate_streak,
    SignalSource.ALTERNATION: _evaluate_alternation,
    SignalSource.BODY_RATIO: _evaluate_body_ratio,
}


def evaluate_at(
    points: tuple[ValidatedPricePoint, ...],
    index: int,
    rule: StrategyRule,
) -> SignalDirection | None:
    """Avalia a regra no instante `index` usando somente dados até `index`.

    Os avaliadores acessam exclusivamente deslocamentos negativos a partir de
    `index` — nunca `index + k`. Essa propriedade é verificada de duas formas:

    - por teste unitário, comparando com a série truncada no ponto de decisão;
    - em tempo de execução, pelo Adversarial Agent, que reexecuta cada sinal
      sobre a série truncada e reprova a estratégia se houver divergência.

    A versão anterior garantia isso fatiando a série a cada índice, o que
    custava uma cópia O(n) por decisão e tornava o backtest O(n²).
    """
    if index < 0 or index >= len(points):
        raise IndexError("index fora da série")

    if index + 1 < rule.minimum_history:
        return None
    if not _within_hour_window(points[index].timestamp, rule.hour_window):
        return None

    return _EVALUATORS[rule.signal_source](points, index, rule)


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
