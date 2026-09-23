"""Métricas determinísticas de performance e risco (Fase 3).

Todo cálculo aqui é código puro e testado. Nenhum LLM participa da produção
destes números (MASTER_SPEC seção 2.2). O payout nunca é hardcoded — é sempre
recebido como parâmetro, vindo do dataset/corretora (seção 29).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True, slots=True)
class EquityCurve:
    """Curva de capital e métricas derivadas dela."""

    values: tuple[float, ...]
    max_drawdown: float
    max_drawdown_absolute: float
    ruined: bool


def win_rate(wins: int, total: int) -> float:
    """Proporção de acertos. Retorna 0.0 quando não há amostra."""
    if total <= 0:
        return 0.0
    return wins / total


def expectancy(rate_of_wins: float, payout: float) -> float:
    """Expectancy líquido de payout por unidade apostada.

    expectancy = (win_rate × payout) - (loss_rate × 1)

    `payout` é o retorno líquido de uma operação vencedora (ex: 0.87 para 87%).
    """
    if not 0.0 <= rate_of_wins <= 1.0:
        raise ValueError("win_rate deve estar entre 0 e 1")
    if payout <= 0:
        raise ValueError("payout deve ser positivo")
    return (rate_of_wins * payout) - ((1.0 - rate_of_wins) * 1.0)


def max_loss_streak(outcomes: Sequence[bool]) -> int:
    """Maior sequência consecutiva de perdas. `True` = vitória."""
    longest = 0
    current = 0
    for won in outcomes:
        if won:
            current = 0
            continue
        current += 1
        longest = max(longest, current)
    return longest


def max_win_streak(outcomes: Sequence[bool]) -> int:
    """Maior sequência consecutiva de vitórias."""
    longest = 0
    current = 0
    for won in outcomes:
        if not won:
            current = 0
            continue
        current += 1
        longest = max(longest, current)
    return longest


def build_equity_curve(
    outcomes: Sequence[bool],
    initial_capital: float,
    payout: float,
    risk_per_trade: float,
) -> EquityCurve:
    """Constrói a curva de capital com aposta fracionária sobre o capital atual.

    Para em ruína (capital insuficiente para a próxima aposta) e marca
    `ruined=True`. Não permite capital negativo.
    """
    if initial_capital <= 0:
        raise ValueError("initial_capital deve ser positivo")
    if not 0.0 < risk_per_trade <= 1.0:
        raise ValueError("risk_per_trade deve estar entre 0 e 1")
    if payout <= 0:
        raise ValueError("payout deve ser positivo")

    equity = initial_capital
    values = [equity]
    peak = equity
    worst_relative = 0.0
    worst_absolute = 0.0
    ruined = False

    for won in outcomes:
        stake = equity * risk_per_trade
        if stake <= 0 or stake > equity:
            ruined = True
            break
        equity = equity + stake * payout if won else equity - stake
        if equity <= 0:
            equity = 0.0
            values.append(equity)
            ruined = True
            break
        values.append(equity)
        peak = max(peak, equity)
        drop_absolute = peak - equity
        if drop_absolute > worst_absolute:
            worst_absolute = drop_absolute
        if peak > 0:
            worst_relative = max(worst_relative, drop_absolute / peak)

    return EquityCurve(
        values=tuple(values),
        max_drawdown=worst_relative,
        max_drawdown_absolute=worst_absolute,
        ruined=ruined,
    )


def profit(curve: EquityCurve, initial_capital: float) -> float:
    """Lucro absoluto ao final da curva."""
    if not curve.values:
        return 0.0
    return curve.values[-1] - initial_capital


def profit_pct(curve: EquityCurve, initial_capital: float) -> float:
    """Lucro relativo ao capital inicial."""
    if initial_capital <= 0:
        raise ValueError("initial_capital deve ser positivo")
    return profit(curve, initial_capital) / initial_capital
