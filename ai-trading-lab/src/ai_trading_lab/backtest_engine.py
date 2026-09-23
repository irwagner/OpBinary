"""Backtest Engine determinístico e independente de LLM (Fase 3).

Garantias:
- mesma entrada produz sempre a mesma saída (sem aleatoriedade);
- a decisão de entrada nunca usa dados posteriores ao instante da decisão;
- payout vem sempre do dataset/configuração, nunca hardcoded;
- empate é tratado como perda (conservador para opções binárias);
- nenhuma ordem é enviada a lugar algum — isto é simulação contábil.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from .data_models import ValidatedPricePoint
from .errors import DataQualityError
from .metrics import (
    EquityCurve,
    build_equity_curve,
    expectancy,
    max_loss_streak,
    max_win_streak,
    profit,
    profit_pct,
    win_rate,
)
from .strategy import Signal, SignalDirection, StrategyRule, generate_signals


class TradeOutcome(StrEnum):
    """Resultado de uma operação simulada."""

    WIN = "WIN"
    LOSS = "LOSS"


@dataclass(frozen=True, slots=True)
class SimulatedTrade:
    """Operação simulada, com referência temporal explícita de entrada e saída."""

    entry_index: int
    entry_timestamp: datetime
    exit_timestamp: datetime
    direction: SignalDirection
    entry_price: float
    exit_price: float
    outcome: TradeOutcome

    @property
    def won(self) -> bool:
        return self.outcome is TradeOutcome.WIN


@dataclass(frozen=True, slots=True)
class CapitalScenarioResult:
    """Resultado da simulação contábil para um cenário de capital."""

    initial_capital: float
    risk_per_trade: float
    final_capital: float
    profit: float
    profit_pct: float
    max_drawdown: float
    max_drawdown_absolute: float
    ruined: bool
    equity_curve: tuple[float, ...] = field(repr=False, default=())


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Registro completo de um backtest, conforme MASTER_SPEC seção 13."""

    asset: str
    timeframe: str
    broker: str
    period_start: datetime
    period_end: datetime
    rule: StrategyRule
    payout: float
    sample_size: int
    trades: int
    wins: int
    losses: int
    win_rate: float
    expectancy: float
    max_loss_streak: int
    max_win_streak: int
    scenarios: tuple[CapitalScenarioResult, ...]
    outcomes: tuple[bool, ...] = field(repr=False, default=())
    simulated_trades: tuple[SimulatedTrade, ...] = field(repr=False, default=())

    @property
    def worst_drawdown(self) -> float:
        """Pior drawdown relativo entre todos os cenários de capital."""
        if not self.scenarios:
            return 0.0
        return max(scenario.max_drawdown for scenario in self.scenarios)

    @property
    def any_ruin(self) -> bool:
        """Verdadeiro se algum cenário de capital terminou em ruína."""
        return any(scenario.ruined for scenario in self.scenarios)


def resolve_trade(
    points: tuple[ValidatedPricePoint, ...],
    signal: Signal,
    expiry_periods: int,
) -> SimulatedTrade:
    """Resolve o resultado de um sinal na expiração. Empate conta como perda."""
    exit_index = signal.index + expiry_periods
    if exit_index >= len(points):
        raise DataQualityError("expiração fora da série; sinal não deveria ter sido gerado")

    entry = points[signal.index]
    exit_point = points[exit_index]
    if signal.direction is SignalDirection.CALL:
        won = exit_point.price > entry.price
    else:
        won = exit_point.price < entry.price

    return SimulatedTrade(
        entry_index=signal.index,
        entry_timestamp=entry.timestamp,
        exit_timestamp=exit_point.timestamp,
        direction=signal.direction,
        entry_price=entry.price,
        exit_price=exit_point.price,
        outcome=TradeOutcome.WIN if won else TradeOutcome.LOSS,
    )


def run_backtest(
    points: tuple[ValidatedPricePoint, ...],
    rule: StrategyRule,
    *,
    payout: float,
    capital_scenarios: tuple[int, ...],
    risk_per_trade: float,
) -> BacktestResult:
    """Executa o backtest determinístico sobre uma série já validada."""
    if not points:
        raise DataQualityError("backtest exige uma série não vazia")
    if payout <= 0:
        raise ValueError("payout deve ser positivo (valor vem do dataset)")
    if not capital_scenarios:
        raise ValueError("é necessário ao menos um cenário de capital")

    for previous, current in zip(points, points[1:]):
        if current.timestamp < previous.timestamp:
            raise DataQualityError("série fora de ordem cronológica não pode ser backtestada")

    signals = generate_signals(points, rule)
    trades = tuple(resolve_trade(points, signal, rule.expiry_periods) for signal in signals)
    outcomes = tuple(trade.won for trade in trades)

    wins = sum(1 for won in outcomes if won)
    losses = len(outcomes) - wins
    rate = win_rate(wins, len(outcomes))
    expected_value = expectancy(rate, payout) if outcomes else 0.0

    scenarios = tuple(
        _simulate_scenario(outcomes, float(capital), payout, risk_per_trade)
        for capital in capital_scenarios
    )

    return BacktestResult(
        asset=points[0].asset,
        timeframe=points[0].timeframe,
        broker=points[0].broker,
        period_start=points[0].timestamp,
        period_end=points[-1].timestamp,
        rule=rule,
        payout=payout,
        sample_size=len(points),
        trades=len(outcomes),
        wins=wins,
        losses=losses,
        win_rate=rate,
        expectancy=expected_value,
        max_loss_streak=max_loss_streak(outcomes),
        max_win_streak=max_win_streak(outcomes),
        scenarios=scenarios,
        outcomes=outcomes,
        simulated_trades=trades,
    )


def _simulate_scenario(
    outcomes: tuple[bool, ...],
    initial_capital: float,
    payout: float,
    risk_per_trade: float,
) -> CapitalScenarioResult:
    curve: EquityCurve = build_equity_curve(
        outcomes, initial_capital, payout, risk_per_trade
    )
    return CapitalScenarioResult(
        initial_capital=initial_capital,
        risk_per_trade=risk_per_trade,
        final_capital=curve.values[-1] if curve.values else initial_capital,
        profit=profit(curve, initial_capital),
        profit_pct=profit_pct(curve, initial_capital),
        max_drawdown=curve.max_drawdown,
        max_drawdown_absolute=curve.max_drawdown_absolute,
        ruined=curve.ruined,
        equity_curve=curve.values,
    )
