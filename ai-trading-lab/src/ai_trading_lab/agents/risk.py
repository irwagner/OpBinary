"""Risk Agent: risco de mercado por cenário de capital (Fase 5).

Este agente nunca é otimizado para aumentar lucro (MASTER_SPEC seção 16).
Reporta risco cru e reprova quando os limites configurados são excedidos,
mesmo que o retorno médio seja atraente.
"""

from __future__ import annotations

from ..backtest_engine import BacktestResult
from ..configuration import RiskConfig
from ..contracts import CapitalRisk, Finding, RiskReport, Verdict
from ..errors import DataQualityError
from ..monte_carlo import run_monte_carlo
from .base import AuditSink, BaseAgent


class RiskAgent(BaseAgent):
    """Mede drawdown, sequência de perdas e risco de ruína por cenário."""

    name = "risk"
    version = "v0.1.0"

    def __init__(
        self,
        software_version: str = "v0.1.0",
        audit_sink: AuditSink | None = None,
    ) -> None:
        super().__init__(software_version=software_version, audit_sink=audit_sink)

    def assess(
        self,
        backtest: BacktestResult,
        risk_config: RiskConfig,
        *,
        experiment_id: str,
        strategy_id: str,
        monte_carlo_runs: int,
    ) -> RiskReport:
        """Avalia cada cenário de capital contra os limites configurados."""
        if not backtest.outcomes:
            raise DataQualityError("sem operações simuladas não há risco a medir")

        scenarios: list[CapitalRisk] = []
        findings: list[Finding] = []

        for scenario in backtest.scenarios:
            monte = run_monte_carlo(
                backtest.outcomes,
                runs=monte_carlo_runs,
                initial_capital=scenario.initial_capital,
                payout=backtest.payout,
                risk_per_trade=scenario.risk_per_trade,
            )
            scenarios.append(
                CapitalRisk(
                    capital_scenario=int(scenario.initial_capital),
                    max_drawdown=scenario.max_drawdown,
                    max_consecutive_losses=backtest.max_loss_streak,
                    risk_of_ruin=monte.ruin_probability,
                    final_capital=scenario.final_capital,
                    ruined=scenario.ruined,
                )
            )

        worst_drawdown = max(item.max_drawdown for item in scenarios)
        worst_ruin = max(item.risk_of_ruin for item in scenarios)

        if worst_drawdown > risk_config.max_drawdown_limit:
            findings.append(
                Finding(
                    category="drawdown_limit_exceeded",
                    severity=Verdict.FAIL,
                    description=(
                        f"drawdown {worst_drawdown:.2%} acima do limite "
                        f"{risk_config.max_drawdown_limit:.2%}"
                    ),
                )
            )
        if worst_ruin > risk_config.max_risk_of_ruin:
            findings.append(
                Finding(
                    category="risk_of_ruin_exceeded",
                    severity=Verdict.FAIL,
                    description=(
                        f"risco de ruína {worst_ruin:.2%} acima do limite "
                        f"{risk_config.max_risk_of_ruin:.2%}"
                    ),
                )
            )
        if any(item.ruined for item in scenarios):
            findings.append(
                Finding(
                    category="capital_depletion",
                    severity=Verdict.FAIL,
                    description="ao menos um cenário de capital terminou em ruína",
                )
            )

        # Uma sequência de perdas é aceitável apenas se sobreviver a ela deixar
        # o capital acima do limite de drawdown configurado.
        survival_factor = (1.0 - risk_config.risk_per_trade) ** backtest.max_loss_streak
        loss_streak_within_limit = survival_factor >= (1.0 - risk_config.max_drawdown_limit)
        if not loss_streak_within_limit:
            findings.append(
                Finding(
                    category="loss_streak_too_deep",
                    severity=Verdict.FAIL,
                    description=(
                        f"{backtest.max_loss_streak} perdas consecutivas reduzem o capital a "
                        f"{survival_factor:.2%}, abaixo do piso "
                        f"{1.0 - risk_config.max_drawdown_limit:.2%}"
                    ),
                )
            )

        verdict = Verdict.FAIL if findings else Verdict.PASS
        report = RiskReport(
            strategy_id=strategy_id,
            experiment_id=experiment_id,
            verdict=verdict,
            scenarios=tuple(scenarios),
            worst_drawdown=worst_drawdown,
            worst_risk_of_ruin=worst_ruin,
            max_consecutive_losses=backtest.max_loss_streak,
            loss_streak_within_limit=loss_streak_within_limit,
            findings=tuple(findings),
            envelope=self.envelope(experiment_id=experiment_id, decision=verdict.value),
        )

        self.record(
            "risk_assessed",
            {
                "strategy_id": strategy_id,
                "verdict": verdict.value,
                "worst_drawdown": worst_drawdown,
                "worst_risk_of_ruin": worst_ruin,
                "max_consecutive_losses": backtest.max_loss_streak,
            },
            experiment_id=experiment_id,
        )
        return report
