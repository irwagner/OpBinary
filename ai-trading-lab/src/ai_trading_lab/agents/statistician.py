"""Statistician Agent: robustez estatística (Fase 5).

Consome o motor determinístico (`walk_forward`, `monte_carlo`) e interpreta
os números — nunca os inventa. Não decide promoção: apenas produz o relatório
que o Validator vai consumir (MASTER_SPEC seção 14).
"""

from __future__ import annotations

from ..backtest_engine import BacktestResult, run_backtest
from ..contracts import DatasetReference, FoldSummary, FormalStrategy, StatisticalReport
from ..data_models import ValidatedPricePoint
from ..errors import DataQualityError
from ..monte_carlo import run_monte_carlo
from ..walk_forward import run_walk_forward
from .base import AuditSink, BaseAgent

_OUT_OF_SAMPLE_FRACTION = 0.3


class StatisticianAgent(BaseAgent):
    """Produz o relatório estatístico consolidado de um experimento."""

    name = "statistician"
    version = "v0.1.0"

    def __init__(
        self,
        software_version: str = "v0.1.0",
        audit_sink: AuditSink | None = None,
    ) -> None:
        super().__init__(software_version=software_version, audit_sink=audit_sink)

    def analyze(
        self,
        strategy: FormalStrategy,
        points: tuple[ValidatedPricePoint, ...],
        dataset: DatasetReference,
        backtest: BacktestResult,
        *,
        experiment_id: str,
        walk_forward_folds: int,
        monte_carlo_runs: int,
        capital_scenarios: tuple[int, ...],
        risk_per_trade: float,
    ) -> StatisticalReport:
        """Executa walk-forward, OOS e Monte Carlo, e consolida o relatório."""
        if strategy.rule is None:
            raise DataQualityError("estratégia sem regra não pode ser analisada")

        walk = run_walk_forward(
            points,
            strategy.rule,
            folds=walk_forward_folds,
            payout=dataset.payout,
            capital_scenarios=capital_scenarios,
            risk_per_trade=risk_per_trade,
        )

        in_sample_expectancy, oos_expectancy = self._in_sample_vs_oos(
            points,
            strategy,
            dataset,
            capital_scenarios=capital_scenarios,
            risk_per_trade=risk_per_trade,
        )

        monte = run_monte_carlo(
            backtest.outcomes,
            runs=monte_carlo_runs,
            initial_capital=float(min(capital_scenarios)),
            payout=dataset.payout,
            risk_per_trade=risk_per_trade,
        )

        report = StatisticalReport(
            strategy_id=strategy.strategy_id,
            experiment_id=experiment_id,
            sample_size=backtest.sample_size,
            trades=backtest.trades,
            win_rate=backtest.win_rate,
            expectancy=backtest.expectancy,
            oos_expectancy=oos_expectancy,
            in_sample_expectancy=in_sample_expectancy,
            degradation=in_sample_expectancy - oos_expectancy,
            fold_pass_ratio=walk.fold_pass_ratio,
            expectancy_spread=walk.expectancy_spread,
            folds=tuple(
                FoldSummary(
                    fold_index=fold.fold_index,
                    expectancy=fold.expectancy,
                    trades=fold.trades,
                    passed=fold.passed,
                )
                for fold in walk.folds
            ),
            monte_carlo_ruin_probability=monte.ruin_probability,
            monte_carlo_worst_drawdown=monte.worst_max_drawdown,
            monte_carlo_worst_loss_streak=monte.worst_loss_streak,
            envelope=self.envelope(
                experiment_id=experiment_id, input_ref=dataset.content_hash
            ),
        )

        self.record(
            "statistics_computed",
            {
                "strategy_id": strategy.strategy_id,
                "trades": report.trades,
                "expectancy": report.expectancy,
                "fold_pass_ratio": report.fold_pass_ratio,
                "degradation": report.degradation,
                "ruin_probability": report.monte_carlo_ruin_probability,
            },
            experiment_id=experiment_id,
        )
        return report

    def _in_sample_vs_oos(
        self,
        points: tuple[ValidatedPricePoint, ...],
        strategy: FormalStrategy,
        dataset: DatasetReference,
        *,
        capital_scenarios: tuple[int, ...],
        risk_per_trade: float,
    ) -> tuple[float, float]:
        assert strategy.rule is not None
        split_index = int(len(points) * (1.0 - _OUT_OF_SAMPLE_FRACTION))
        in_sample = points[:split_index]
        out_of_sample = points[split_index:]

        minimum = strategy.rule.lookback + strategy.rule.expiry_periods + 2
        if len(in_sample) < minimum or len(out_of_sample) < minimum:
            raise DataQualityError(
                "amostra insuficiente para separar in-sample e out-of-sample"
            )

        in_sample_result = run_backtest(
            in_sample,
            strategy.rule,
            payout=dataset.payout,
            capital_scenarios=capital_scenarios,
            risk_per_trade=risk_per_trade,
        )
        oos_result = run_backtest(
            out_of_sample,
            strategy.rule,
            payout=dataset.payout,
            capital_scenarios=capital_scenarios,
            risk_per_trade=risk_per_trade,
        )
        return in_sample_result.expectancy, oos_result.expectancy
