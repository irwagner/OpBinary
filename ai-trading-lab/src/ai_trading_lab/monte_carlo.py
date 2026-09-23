"""Simulação Monte Carlo sobre os resultados do backtest (Fase 3).

Reamostra a sequência de resultados para estudar a distribuição possível,
drawdowns, sequências de perdas e risco de ruína (MASTER_SPEC seção 27).

Determinismo: a simulação usa um gerador semeado explicitamente. O mesmo
`seed` sempre produz o mesmo resultado, mantendo o experimento reproduzível.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from statistics import mean, median, pstdev

from .errors import DataQualityError
from .metrics import build_equity_curve, max_loss_streak


@dataclass(frozen=True, slots=True)
class MonteCarloResult:
    """Distribuição agregada das simulações."""

    runs: int
    seed: int
    initial_capital: float
    payout: float
    risk_per_trade: float
    mean_final_capital: float
    median_final_capital: float
    stdev_final_capital: float
    p05_final_capital: float
    p95_final_capital: float
    worst_final_capital: float
    best_final_capital: float
    mean_max_drawdown: float
    worst_max_drawdown: float
    worst_loss_streak: int
    ruin_probability: float
    loss_probability: float


def run_monte_carlo(
    outcomes: tuple[bool, ...],
    *,
    runs: int,
    initial_capital: float,
    payout: float,
    risk_per_trade: float,
    seed: int = 20260101,
) -> MonteCarloResult:
    """Reamostra os resultados com reposição e agrega a distribuição."""
    if not outcomes:
        raise DataQualityError("Monte Carlo exige ao menos um resultado de operação")
    if runs < 1:
        raise ValueError("runs deve ser >= 1")

    generator = random.Random(seed)
    final_capitals: list[float] = []
    drawdowns: list[float] = []
    loss_streaks: list[int] = []
    ruins = 0

    for _ in range(runs):
        resampled = tuple(generator.choice(outcomes) for _ in range(len(outcomes)))
        curve = build_equity_curve(resampled, initial_capital, payout, risk_per_trade)
        final_capitals.append(curve.values[-1] if curve.values else initial_capital)
        drawdowns.append(curve.max_drawdown)
        loss_streaks.append(max_loss_streak(resampled))
        if curve.ruined:
            ruins += 1

    ordered = sorted(final_capitals)
    losses = sum(1 for capital in final_capitals if capital < initial_capital)

    return MonteCarloResult(
        runs=runs,
        seed=seed,
        initial_capital=initial_capital,
        payout=payout,
        risk_per_trade=risk_per_trade,
        mean_final_capital=mean(final_capitals),
        median_final_capital=median(final_capitals),
        stdev_final_capital=pstdev(final_capitals) if len(final_capitals) > 1 else 0.0,
        p05_final_capital=_percentile(ordered, 0.05),
        p95_final_capital=_percentile(ordered, 0.95),
        worst_final_capital=ordered[0],
        best_final_capital=ordered[-1],
        mean_max_drawdown=mean(drawdowns),
        worst_max_drawdown=max(drawdowns),
        worst_loss_streak=max(loss_streaks),
        ruin_probability=ruins / runs,
        loss_probability=losses / runs,
    )


def _percentile(ordered_values: list[float], fraction: float) -> float:
    if not ordered_values:
        raise ValueError("lista vazia não possui percentil")
    if len(ordered_values) == 1:
        return ordered_values[0]
    position = fraction * (len(ordered_values) - 1)
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered_values) - 1)
    weight = position - lower_index
    lower = ordered_values[lower_index]
    upper = ordered_values[upper_index]
    return lower + (upper - lower) * weight
