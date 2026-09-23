"""Contratos estruturados de entrada/saída entre agentes (Fases 4 e 5).

Implementa docs/AGENT_CONTRACTS.md. Nenhum contrato transporta texto livre
onde deveria haver número: todo valor numérico é produzido por código
determinístico (`core` da Fase 3), nunca por um LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Mapping

from .models import utc_now
from .strategy import StrategyRule


class Verdict(StrEnum):
    """Veredicto de agentes de contestação/risco."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class TaskType(StrEnum):
    """Tarefas que um agente pode solicitar ao Supervisor."""

    GENERATE_HYPOTHESIS = "GENERATE_HYPOTHESIS"
    FORMALIZE_STRATEGY = "FORMALIZE_STRATEGY"
    COLLECT_DATA = "COLLECT_DATA"
    RUN_BACKTEST = "RUN_BACKTEST"
    RUN_STATISTICS = "RUN_STATISTICS"
    RUN_ADVERSARIAL = "RUN_ADVERSARIAL"
    RUN_RISK = "RUN_RISK"
    RUN_BROKER_RISK = "RUN_BROKER_RISK"
    DECIDE_VALIDATION = "DECIDE_VALIDATION"
    BUILD_REPORT = "BUILD_REPORT"


@dataclass(frozen=True, slots=True)
class AgentEnvelope:
    """Envelope de auditoria comum a todo output de agente."""

    agent_name: str
    agent_version: str
    software_version: str
    timestamp: datetime = field(default_factory=utc_now)
    experiment_id: str | None = None
    input_ref: str | None = None
    decision: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PermissionRequest:
    """Pedido de autorização de um agente ao Supervisor."""

    agent_name: str
    task_type: TaskType
    strategy_id: str | None = None
    experiment_id: str | None = None
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    """Resposta do Supervisor a um pedido de autorização."""

    status: Verdict
    reason: str
    checked_preconditions: tuple[str, ...] = ()

    @property
    def granted(self) -> bool:
        return self.status is Verdict.PASS


@dataclass(frozen=True, slots=True)
class Hypothesis:
    """Hipótese formalizada pelo Research Agent."""

    strategy_id: str
    asset: str
    timeframe: str
    entry_conditions: tuple[str, ...]
    exit_rule: str
    filters: tuple[str, ...]
    parameters: Mapping[str, object]
    envelope: AgentEnvelope | None = None


@dataclass(frozen=True, slots=True)
class FormalStrategy:
    """Estratégia computável produzida pelo Quant Agent."""

    strategy_id: str
    rule: StrategyRule | None
    reproducible: bool
    rejection_reason: str | None = None
    envelope: AgentEnvelope | None = None


@dataclass(frozen=True, slots=True)
class DatasetReference:
    """Referência imutável a uma versão de dataset já persistida."""

    dataset_id: str
    version: int
    content_hash: str
    broker: str
    asset: str
    timeframe: str
    point_count: int
    payout: float


@dataclass(frozen=True, slots=True)
class FoldSummary:
    """Resumo de um fold de walk-forward exposto ao Validator."""

    fold_index: int
    expectancy: float
    trades: int
    passed: bool


@dataclass(frozen=True, slots=True)
class StatisticalReport:
    """Relatório estatístico consolidado."""

    strategy_id: str
    experiment_id: str
    sample_size: int
    trades: int
    win_rate: float
    expectancy: float
    oos_expectancy: float
    in_sample_expectancy: float
    degradation: float
    fold_pass_ratio: float
    expectancy_spread: float
    folds: tuple[FoldSummary, ...]
    monte_carlo_ruin_probability: float
    monte_carlo_worst_drawdown: float
    monte_carlo_worst_loss_streak: int
    envelope: AgentEnvelope | None = None


@dataclass(frozen=True, slots=True)
class Finding:
    """Achado individual de um agente de contestação."""

    category: str
    severity: Verdict
    description: str


@dataclass(frozen=True, slots=True)
class AdversarialVerdict:
    """Resultado da tentativa de quebrar a estratégia."""

    strategy_id: str
    experiment_id: str
    verdict: Verdict
    findings: tuple[Finding, ...]
    envelope: AgentEnvelope | None = None


@dataclass(frozen=True, slots=True)
class CapitalRisk:
    """Risco medido para um cenário de capital específico."""

    capital_scenario: int
    max_drawdown: float
    max_consecutive_losses: int
    risk_of_ruin: float
    final_capital: float
    ruined: bool


@dataclass(frozen=True, slots=True)
class RiskReport:
    """Relatório de risco por cenário de capital."""

    strategy_id: str
    experiment_id: str
    verdict: Verdict
    scenarios: tuple[CapitalRisk, ...]
    worst_drawdown: float
    worst_risk_of_ruin: float
    max_consecutive_losses: int
    loss_streak_within_limit: bool
    findings: tuple[Finding, ...]
    envelope: AgentEnvelope | None = None


@dataclass(frozen=True, slots=True)
class BrokerRiskReport:
    """Avaliação de risco de contraparte. FAIL bloqueia DEMO."""

    broker_name: str
    status: Verdict
    basis_risk: bool
    findings: tuple[Finding, ...]
    sources: tuple[str, ...]
    evaluated_at: datetime = field(default_factory=utc_now)
    next_review_due: datetime | None = None
    previous_status: Verdict | None = None
    envelope: AgentEnvelope | None = None


@dataclass(frozen=True, slots=True)
class ValidationChecklist:
    """Checklist obrigatório da seção 29/63 da MASTER_SPEC."""

    sufficient_sample: bool
    no_data_leakage: bool
    no_look_ahead_bias: bool
    oos_passed: bool
    walk_forward_passed: bool
    monte_carlo_passed: bool
    temporal_stability: bool
    drawdown_reviewed: bool
    loss_streak_reviewed: bool
    adversarial_passed: bool
    expectancy_positive_net_payout: bool
    risk_reviewed: bool
    broker_risk_passed: bool
    documentation_complete: bool

    @property
    def all_passed(self) -> bool:
        return all(
            (
                self.sufficient_sample,
                self.no_data_leakage,
                self.no_look_ahead_bias,
                self.oos_passed,
                self.walk_forward_passed,
                self.monte_carlo_passed,
                self.temporal_stability,
                self.drawdown_reviewed,
                self.loss_streak_reviewed,
                self.adversarial_passed,
                self.expectancy_positive_net_payout,
                self.risk_reviewed,
                self.broker_risk_passed,
                self.documentation_complete,
            )
        )

    def failed_items(self) -> tuple[str, ...]:
        """Lista os itens reprovados, para registro do motivo da rejeição."""
        items = {
            "sufficient_sample": self.sufficient_sample,
            "no_data_leakage": self.no_data_leakage,
            "no_look_ahead_bias": self.no_look_ahead_bias,
            "oos_passed": self.oos_passed,
            "walk_forward_passed": self.walk_forward_passed,
            "monte_carlo_passed": self.monte_carlo_passed,
            "temporal_stability": self.temporal_stability,
            "drawdown_reviewed": self.drawdown_reviewed,
            "loss_streak_reviewed": self.loss_streak_reviewed,
            "adversarial_passed": self.adversarial_passed,
            "expectancy_positive_net_payout": self.expectancy_positive_net_payout,
            "risk_reviewed": self.risk_reviewed,
            "broker_risk_passed": self.broker_risk_passed,
            "documentation_complete": self.documentation_complete,
        }
        return tuple(name for name, passed in items.items() if not passed)


@dataclass(frozen=True, slots=True)
class ValidationDecision:
    """Decisão do Validator: única fonte de transição de estado da estratégia."""

    strategy_id: str
    experiment_id: str
    previous_state: str
    new_state: str
    reason: str
    checklist: ValidationChecklist
    envelope: AgentEnvelope | None = None
