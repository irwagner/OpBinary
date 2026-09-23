"""Reporter Agent: formata relatórios legíveis (Fase 5).

Somente leitura e formatação. Não decide, não transiciona estado e não pode
omitir resultado negativo (MASTER_SPEC seções 18, 34, 56, 62).
"""

from __future__ import annotations

from ..contracts import (
    AdversarialVerdict,
    BrokerRiskReport,
    RiskReport,
    StatisticalReport,
    ValidationDecision,
)
from .base import AuditSink, BaseAgent


class ReporterAgent(BaseAgent):
    """Produz relatórios de estratégia e de ciclo em texto."""

    name = "reporter"
    version = "v0.1.0"

    def __init__(
        self,
        software_version: str = "v0.1.0",
        audit_sink: AuditSink | None = None,
    ) -> None:
        super().__init__(software_version=software_version, audit_sink=audit_sink)

    def strategy_report(
        self,
        statistics: StatisticalReport,
        adversarial: AdversarialVerdict,
        risk: RiskReport,
        broker_risk: BrokerRiskReport,
        decision: ValidationDecision,
    ) -> str:
        """Relatório completo de uma estratégia, incluindo motivos de reprovação."""
        lines = [
            "STRATEGY REPORT",
            "",
            f"ID:          {statistics.strategy_id}",
            f"Experiment:  {statistics.experiment_id}",
            "",
            f"Sample:      {statistics.sample_size} pontos / {statistics.trades} operações",
            f"Win rate:    {statistics.win_rate:.2%}",
            f"Expectancy:  {statistics.expectancy:+.4f}",
            f"In-sample:   {statistics.in_sample_expectancy:+.4f}",
            f"Out-sample:  {statistics.oos_expectancy:+.4f}",
            f"Degradação:  {statistics.degradation:+.4f}",
            "",
            f"Walk-forward: {statistics.fold_pass_ratio:.0%} dos folds com expectancy > 0",
        ]
        for fold in statistics.folds:
            status = "PASS" if fold.passed else "FAIL"
            lines.append(
                f"  fold {fold.fold_index}: expectancy {fold.expectancy:+.4f} "
                f"({fold.trades} ops) {status}"
            )

        lines.extend(
            [
                "",
                f"Monte Carlo: ruína {statistics.monte_carlo_ruin_probability:.2%}, "
                f"pior drawdown {statistics.monte_carlo_worst_drawdown:.2%}, "
                f"pior sequência de perdas {statistics.monte_carlo_worst_loss_streak}",
                "",
                f"Risk:        {risk.verdict.value} "
                f"(drawdown {risk.worst_drawdown:.2%}, ruína {risk.worst_risk_of_ruin:.2%})",
            ]
        )
        for scenario in risk.scenarios:
            lines.append(
                f"  ${scenario.capital_scenario}: final ${scenario.final_capital:,.2f}, "
                f"drawdown {scenario.max_drawdown:.2%}, ruína {scenario.risk_of_ruin:.2%}"
            )

        lines.extend(["", f"Adversarial: {adversarial.verdict.value}"])
        for finding in adversarial.findings:
            lines.append(f"  [{finding.severity.value}] {finding.category}: {finding.description}")

        lines.extend(
            [
                "",
                f"Broker Risk: {broker_risk.status.value} "
                f"(basis_risk={broker_risk.basis_risk})",
            ]
        )
        for finding in broker_risk.findings:
            lines.append(f"  [{finding.severity.value}] {finding.category}: {finding.description}")

        failed = decision.checklist.failed_items()
        lines.extend(
            [
                "",
                f"Decision:    {decision.previous_state} -> {decision.new_state}",
                f"Reason:      {decision.reason}",
                f"Checklist:   {'completo' if not failed else 'reprovado em ' + ', '.join(failed)}",
                "",
                "Aviso: resultados históricos ou de DEMO não garantem resultados futuros.",
            ]
        )

        self.record(
            "strategy_report_built",
            {"strategy_id": statistics.strategy_id, "new_state": decision.new_state},
            experiment_id=statistics.experiment_id,
        )
        return "\n".join(lines)

    def cycle_report(
        self,
        *,
        cycle_index: int,
        evaluated: int,
        advanced: int,
        rejected: int,
        needs_research: int,
        errors: tuple[str, ...],
    ) -> str:
        """Resumo de um ciclo de pesquisa, preservando erros e rejeições."""
        lines = [
            "AI TRADING LAB — CYCLE REPORT",
            "",
            f"Cycle:           {cycle_index}",
            f"Evaluated:       {evaluated}",
            f"Advanced:        {advanced}",
            f"Rejected:        {rejected}",
            f"Needs research:  {needs_research}",
            f"Errors:          {len(errors)}",
        ]
        lines.extend(f"  - {error}" for error in errors)
        self.record(
            "cycle_report_built",
            {
                "cycle_index": cycle_index,
                "evaluated": evaluated,
                "advanced": advanced,
                "rejected": rejected,
                "needs_research": needs_research,
                "errors": len(errors),
            },
        )
        return "\n".join(lines)
