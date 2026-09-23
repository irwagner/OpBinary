"""Walk-forward: avalia estabilidade da estratégia ao longo do tempo (Fase 3).

Divide a série em janelas contíguas e sequenciais (nunca aleatórias) e executa
o backtest em cada uma. O objetivo é observar se o resultado se mantém ao longo
do tempo (MASTER_SPEC seção 26) e alimentar o critério do ADR-004:
100% dos folds precisam ter expectancy > 0 por padrão.
"""

from __future__ import annotations

from dataclasses import dataclass

from .backtest_engine import BacktestResult, run_backtest
from .data_models import ValidatedPricePoint
from .errors import DataQualityError
from .strategy import StrategyRule


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    """Resultado de um fold individual."""

    fold_index: int
    sample_size: int
    trades: int
    expectancy: float
    win_rate: float
    max_drawdown: float
    passed: bool


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    """Agregado dos folds, com a razão de aprovação exigida pelo Validator."""

    folds: tuple[WalkForwardFold, ...]
    fold_pass_ratio: float
    mean_expectancy: float
    min_expectancy: float
    max_expectancy: float
    expectancy_spread: float

    @property
    def all_folds_positive(self) -> bool:
        return bool(self.folds) and all(fold.passed for fold in self.folds)


def run_walk_forward(
    points: tuple[ValidatedPricePoint, ...],
    rule: StrategyRule,
    *,
    folds: int,
    payout: float,
    capital_scenarios: tuple[int, ...],
    risk_per_trade: float,
) -> WalkForwardResult:
    """Executa o backtest em `folds` janelas contíguas e sequenciais."""
    if folds < 2:
        raise ValueError("walk-forward exige ao menos 2 folds")

    minimum_window = rule.lookback + rule.expiry_periods + 2
    if len(points) < folds * minimum_window:
        raise DataQualityError(
            f"amostra insuficiente para {folds} folds "
            f"(mínimo aproximado: {folds * minimum_window} pontos)"
        )

    window = len(points) // folds
    results: list[WalkForwardFold] = []

    for fold_index in range(folds):
        start = fold_index * window
        end = len(points) if fold_index == folds - 1 else start + window
        segment = points[start:end]
        backtest: BacktestResult = run_backtest(
            segment,
            rule,
            payout=payout,
            capital_scenarios=capital_scenarios,
            risk_per_trade=risk_per_trade,
        )
        results.append(
            WalkForwardFold(
                fold_index=fold_index,
                sample_size=backtest.sample_size,
                trades=backtest.trades,
                expectancy=backtest.expectancy,
                win_rate=backtest.win_rate,
                max_drawdown=backtest.worst_drawdown,
                passed=backtest.trades > 0 and backtest.expectancy > 0,
            )
        )

    folds_tuple = tuple(results)
    expectancies = [fold.expectancy for fold in folds_tuple]
    passed_count = sum(1 for fold in folds_tuple if fold.passed)

    return WalkForwardResult(
        folds=folds_tuple,
        fold_pass_ratio=passed_count / len(folds_tuple),
        mean_expectancy=sum(expectancies) / len(expectancies),
        min_expectancy=min(expectancies),
        max_expectancy=max(expectancies),
        expectancy_spread=max(expectancies) - min(expectancies),
    )
