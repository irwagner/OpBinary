"""Validator Agent: única autoridade de transição de estado (Fase 5).

Monta o checklist obrigatório (MASTER_SPEC seções 29, 63) e decide a
transição. Nunca promove para REAL por conta própria: a transição para REAL
exige aprovação humana persistida, verificada pela camada de estado
(`StrategyStateManager`).
"""

from __future__ import annotations

from ..configuration import RiskConfig, ValidationConfig
from ..contracts import (
    AdversarialVerdict,
    BrokerRiskReport,
    RiskReport,
    StatisticalReport,
    ValidationChecklist,
    ValidationDecision,
    Verdict,
)
from ..errors import InvalidStateTransition
from ..models import Actor, StrategyStatus
from ..state import StrategyStateManager
from .base import AuditSink, BaseAgent

_NEXT_STATE = {
    StrategyStatus.IDEA: StrategyStatus.BACKTEST,
    StrategyStatus.BACKTEST: StrategyStatus.VALIDATION,
    StrategyStatus.VALIDATION: StrategyStatus.OUT_OF_SAMPLE,
    StrategyStatus.OUT_OF_SAMPLE: StrategyStatus.MONTE_CARLO,
    StrategyStatus.MONTE_CARLO: StrategyStatus.DEMO_CANDIDATE,
}

_STRUCTURAL_FAILURES = frozenset(
    {"no_data_leakage", "no_look_ahead_bias", "adversarial_passed", "risk_reviewed"}
)


class ValidatorAgent(BaseAgent):
    """Aplica o checklist e move a máquina de estados da estratégia."""

    name = "validator"
    version = "v0.1.0"

    def __init__(
        self,
        state_manager: StrategyStateManager,
        software_version: str = "v0.1.0",
        audit_sink: AuditSink | None = None,
    ) -> None:
        super().__init__(software_version=software_version, audit_sink=audit_sink)
        self._states = state_manager

    def build_checklist(
        self,
        statistics: StatisticalReport,
        adversarial: AdversarialVerdict,
        risk: RiskReport,
        broker_risk: BrokerRiskReport,
        validation_config: ValidationConfig,
        risk_config: RiskConfig,
        expectancy_margin: float = 0.0,
    ) -> ValidationChecklist:
        """Constrói o checklist a partir de relatórios já calculados.

        `expectancy_margin` é a exigência extra imposta pelo tamanho do espaço
        de busca varrido: quanto mais hipóteses testadas, maior a margem que a
        estratégia precisa superar para não ser um vencedor por acaso.
        """
        leakage_findings = {
            finding.category
            for finding in adversarial.findings
            if finding.severity is Verdict.FAIL
        }
        return ValidationChecklist(
            sufficient_sample=statistics.sample_size >= validation_config.min_sample_size
            and statistics.trades > 0,
            no_data_leakage="data_leakage" not in leakage_findings,
            no_look_ahead_bias="look_ahead_bias" not in leakage_findings,
            oos_passed=statistics.oos_expectancy > expectancy_margin,
            walk_forward_passed=statistics.fold_pass_ratio
            >= validation_config.min_fold_pass_ratio,
            monte_carlo_passed=statistics.monte_carlo_ruin_probability
            <= risk_config.max_risk_of_ruin,
            temporal_stability=statistics.degradation <= 0.10,
            drawdown_reviewed=risk.worst_drawdown <= risk_config.max_drawdown_limit,
            loss_streak_reviewed=risk.loss_streak_within_limit,
            adversarial_passed=adversarial.verdict is not Verdict.FAIL,
            expectancy_positive_net_payout=statistics.expectancy > expectancy_margin,
            risk_reviewed=risk.verdict is not Verdict.FAIL,
            broker_risk_passed=broker_risk.status is Verdict.PASS,
            documentation_complete=bool(statistics.envelope and adversarial.envelope),
        )

    def decide(
        self,
        strategy_id: str,
        experiment_id: str,
        checklist: ValidationChecklist,
        *,
        actor: Actor,
        require_broker_risk: bool,
    ) -> ValidationDecision:
        """Aplica a decisão e persiste a transição correspondente."""
        current = self._states.load(strategy_id)
        if current is None:
            raise InvalidStateTransition("estratégia não inicializada")

        failed = list(checklist.failed_items())
        if not require_broker_risk and "broker_risk_passed" in failed:
            failed.remove("broker_risk_passed")

        if failed:
            target = (
                StrategyStatus.REJECTED
                if any(item in _STRUCTURAL_FAILURES for item in failed)
                else StrategyStatus.NEEDS_RESEARCH
            )
            reason = f"checklist reprovado: {sorted(failed)}"
        else:
            target = _NEXT_STATE.get(current.status)
            if target is None:
                raise InvalidStateTransition(
                    f"{current.status.value} não avança automaticamente; "
                    "estados além de DEMO_CANDIDATE exigem etapas externas"
                )
            reason = "checklist completo aprovado"

        self._states.transition(strategy_id, target, actor=actor, reason=reason)

        decision = ValidationDecision(
            strategy_id=strategy_id,
            experiment_id=experiment_id,
            previous_state=current.status.value,
            new_state=target.value,
            reason=reason,
            checklist=checklist,
            envelope=self.envelope(
                experiment_id=experiment_id, decision=target.value, reason=reason
            ),
        )

        self.record(
            "validation_decided",
            {
                "strategy_id": strategy_id,
                "previous_state": decision.previous_state,
                "new_state": decision.new_state,
                "reason": reason,
                "failed_items": sorted(failed),
            },
            experiment_id=experiment_id,
        )
        return decision
