"""Backtester Agent: executa o motor determinístico (Fase 4).

O agente não calcula nada por conta própria — delega ao Backtest Engine
(`backtest_engine.run_backtest`), que é independente de LLM e reproduzível.
"""

from __future__ import annotations

from ..backtest_engine import BacktestResult, run_backtest
from ..contracts import DatasetReference, FormalStrategy
from ..data_models import ValidatedPricePoint
from ..errors import DataQualityError
from .base import AuditSink, BaseAgent


class BacktesterAgent(BaseAgent):
    """Adapta o motor de backtest ao contrato de agente."""

    name = "backtester"
    version = "v0.1.0"

    def __init__(
        self,
        software_version: str = "v0.1.0",
        audit_sink: AuditSink | None = None,
    ) -> None:
        super().__init__(software_version=software_version, audit_sink=audit_sink)

    def run(
        self,
        strategy: FormalStrategy,
        points: tuple[ValidatedPricePoint, ...],
        dataset: DatasetReference,
        *,
        experiment_id: str,
        capital_scenarios: tuple[int, ...],
        risk_per_trade: float,
    ) -> BacktestResult:
        """Executa o backtest de uma estratégia formalizada."""
        if not strategy.reproducible or strategy.rule is None:
            raise DataQualityError(
                "estratégia não reproduzível não pode ser backtestada"
            )
        if dataset.payout <= 0:
            raise DataQualityError("payout do dataset deve ser positivo")

        result = run_backtest(
            points,
            strategy.rule,
            payout=dataset.payout,
            capital_scenarios=capital_scenarios,
            risk_per_trade=risk_per_trade,
        )

        self.record(
            "backtest_executed",
            {
                "strategy_id": strategy.strategy_id,
                "dataset_id": dataset.dataset_id,
                "dataset_version": dataset.version,
                "dataset_hash": dataset.content_hash,
                "payout": dataset.payout,
                "trades": result.trades,
                "wins": result.wins,
                "losses": result.losses,
                "expectancy": result.expectancy,
                "worst_drawdown": result.worst_drawdown,
                "max_loss_streak": result.max_loss_streak,
            },
            experiment_id=experiment_id,
        )
        return result
