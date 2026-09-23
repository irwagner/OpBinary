"""Runtime do ciclo autônomo de pesquisa (MASTER_SPEC seção 40).

Sequência executada, sem pular etapas:

    Health Check → Data Check → Load State → Research → Quantification →
    Backtest → Statistics → Adversarial → Risk → Broker Risk → Validation →
    Report → Save State

Nenhuma etapa envia operação. Em RESEARCH, execução está desabilitada por
configuração e o runtime não possui caminho para uma corretora.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .agents.adversarial import AdversarialAgent
from .agents.backtester import BacktesterAgent
from .agents.broker_risk import BrokerIntelligenceSource, BrokerRiskAgent
from .agents.quant import QuantAgent
from .agents.reporter import ReporterAgent
from .agents.researcher import ResearcherAgent, signature_of
from .agents.risk import RiskAgent
from .agents.statistician import StatisticianAgent
from .agents.supervisor import SupervisorAgent
from .agents.validator import ValidatorAgent
from .configuration import SystemConfig
from .contracts import (
    DatasetReference,
    PermissionRequest,
    TaskType,
    Verdict,
)
from .data_persistence import DatasetStore
from .errors import TradingLabError
from .health import HealthReport, ReadinessState, run_health_check
from .agents.researcher import RuleSignature
from .identifiers import ExperimentIdGenerator, StrategyIdGenerator
from .models import Actor, ActorRole, StrategyStatus, SystemStatus
from .persistence import SQLiteStore
from .state import StateManager, StrategyStateManager


@dataclass(slots=True)
class CycleOutcome:
    """Resultado agregado de um ciclo de pesquisa."""

    cycle_index: int
    readiness: ReadinessState
    evaluated: int = 0
    advanced: int = 0
    rejected: int = 0
    needs_research: int = 0
    errors: tuple[str, ...] = ()
    reports: tuple[str, ...] = field(default=(), repr=False)


class ResearchRuntime:
    """Orquestra um ciclo completo de pesquisa sobre um dataset já coletado."""

    def __init__(
        self,
        config: SystemConfig,
        store: SQLiteStore,
        dataset_store: DatasetStore,
        *,
        software_version: str = "v0.1.0",
        broker_intelligence: BrokerIntelligenceSource | None = None,
        strategy_ids: StrategyIdGenerator | None = None,
        experiment_ids: ExperimentIdGenerator | None = None,
    ) -> None:
        self._config = config
        self._store = store
        self._datasets = dataset_store
        self._system_state = StateManager(store)
        self._strategy_states = StrategyStateManager(store)

        self._supervisor = SupervisorAgent(software_version, store)
        self._researcher = ResearcherAgent(software_version, store, strategy_ids)
        self._quant = QuantAgent(software_version, store)
        self._backtester = BacktesterAgent(software_version, store)
        self._statistician = StatisticianAgent(software_version, store)
        self._adversarial = AdversarialAgent(software_version, store)
        self._risk = RiskAgent(software_version, store)
        self._broker_risk = BrokerRiskAgent(software_version, store, broker_intelligence)
        self._validator = ValidatorAgent(self._strategy_states, software_version, store)
        self._reporter = ReporterAgent(software_version, store)

        self._experiment_ids = experiment_ids or ExperimentIdGenerator()
        self._supervisor_actor = Actor("supervisor-runtime", ActorRole.SUPERVISOR)
        self._validator_actor = Actor("validator-runtime", ActorRole.VALIDATOR)
        self._tried_signatures: set[RuleSignature] = set()

    @property
    def system_status(self) -> SystemStatus:
        return self._system_state.snapshot.status

    def health(self, dataset_ids: tuple[str, ...]) -> HealthReport:
        """Executa o health check do ciclo."""
        return run_health_check(
            self._config, self._store, self._datasets, dataset_ids=dataset_ids
        )

    def run_cycle(
        self,
        dataset_id: str,
        *,
        payout: float,
        cycle_index: int = 1,
        require_broker_risk: bool = False,
    ) -> CycleOutcome:
        """Executa um ciclo completo sobre a última versão de um dataset."""
        health = self.health((dataset_id,))
        if health.readiness is not ReadinessState.READY:
            return CycleOutcome(
                cycle_index=cycle_index,
                readiness=health.readiness,
                errors=(f"ciclo não executado: readiness={health.readiness.value}",),
            )

        if self.system_status is SystemStatus.IDLE:
            self._system_state.transition(
                SystemStatus.RUNNING, "research cycle started", actor=self._supervisor_actor
            )

        version = self._datasets.latest_version_number(dataset_id)
        metadata = self._datasets.load_dataset_version(dataset_id, version)
        points = self._datasets.load_points(dataset_id, version)
        if metadata is None or not points:
            return CycleOutcome(
                cycle_index=cycle_index,
                readiness=ReadinessState.NO_DATA,
                errors=("dataset sem pontos utilizáveis",),
            )

        dataset = DatasetReference(
            dataset_id=metadata.dataset_id,
            version=metadata.version,
            content_hash=metadata.content_hash,
            broker=metadata.broker,
            asset=metadata.asset,
            timeframe=metadata.timeframe,
            point_count=metadata.point_count,
            payout=payout,
        )

        outcome = CycleOutcome(cycle_index=cycle_index, readiness=ReadinessState.READY)
        errors: list[str] = []
        reports: list[str] = []

        hypotheses = self._researcher.generate(
            dataset.asset,
            dataset.timeframe,
            limit=self._config.research.max_experiments_per_cycle,
            exclude=frozenset(self._tried_signatures),
        )

        broker_report = self._broker_risk.evaluate(dataset.broker)

        for hypothesis in hypotheses:
            try:
                self._evaluate_hypothesis(
                    hypothesis,
                    dataset,
                    points,
                    broker_report,
                    outcome,
                    reports,
                    errors,
                    require_broker_risk=require_broker_risk,
                )
            except TradingLabError as error:
                errors.append(f"{hypothesis.strategy_id}: {type(error).__name__}: {error}")

        outcome.errors = tuple(errors)
        reports.append(
            self._reporter.cycle_report(
                cycle_index=cycle_index,
                evaluated=outcome.evaluated,
                advanced=outcome.advanced,
                rejected=outcome.rejected,
                needs_research=outcome.needs_research,
                errors=outcome.errors,
            )
        )
        outcome.reports = tuple(reports)
        return outcome

    def _evaluate_hypothesis(
        self,
        hypothesis,
        dataset: DatasetReference,
        points,
        broker_report,
        outcome: CycleOutcome,
        reports: list[str],
        errors: list[str],
        *,
        require_broker_risk: bool,
    ) -> None:
        self._tried_signatures.add(signature_of(dict(hypothesis.parameters)))
        experiment_id = self._experiment_ids.next_id()

        self._strategy_states.initialize(
            hypothesis.strategy_id, actor=self._supervisor_actor, reason="hipótese registrada"
        )

        permission = self._supervisor.request_permission(
            PermissionRequest(
                agent_name="quant",
                task_type=TaskType.FORMALIZE_STRATEGY,
                strategy_id=hypothesis.strategy_id,
                experiment_id=experiment_id,
            ),
            system_status=self.system_status,
            strategy_status=StrategyStatus.IDEA,
        )
        if not permission.granted:
            errors.append(f"{hypothesis.strategy_id}: {permission.reason}")
            return

        strategy = self._quant.formalize(hypothesis)
        if not strategy.reproducible or strategy.rule is None:
            self._strategy_states.transition(
                hypothesis.strategy_id,
                StrategyStatus.REJECTED,
                actor=self._validator_actor,
                reason=strategy.rejection_reason or "estratégia não reproduzível",
            )
            outcome.rejected += 1
            return

        permission = self._supervisor.request_permission(
            PermissionRequest(
                agent_name="backtester",
                task_type=TaskType.RUN_BACKTEST,
                strategy_id=hypothesis.strategy_id,
                experiment_id=experiment_id,
            ),
            system_status=self.system_status,
            strategy_status=StrategyStatus.IDEA,
        )
        if not permission.granted:
            errors.append(f"{hypothesis.strategy_id}: {permission.reason}")
            return

        backtest = self._backtester.run(
            strategy,
            points,
            dataset,
            experiment_id=experiment_id,
            capital_scenarios=self._config.capital_scenarios,
            risk_per_trade=self._config.risk.risk_per_trade,
        )
        outcome.evaluated += 1

        if backtest.trades == 0:
            self._strategy_states.transition(
                hypothesis.strategy_id,
                StrategyStatus.NEEDS_RESEARCH,
                actor=self._validator_actor,
                reason="nenhuma operação gerada pela regra",
            )
            outcome.needs_research += 1
            return

        statistics = self._statistician.analyze(
            strategy,
            points,
            dataset,
            backtest,
            experiment_id=experiment_id,
            walk_forward_folds=self._config.validation.walk_forward_folds,
            monte_carlo_runs=self._config.validation.monte_carlo_runs,
            capital_scenarios=self._config.capital_scenarios,
            risk_per_trade=self._config.risk.risk_per_trade,
        )
        adversarial = self._adversarial.challenge(
            strategy, points, statistics, experiment_id=experiment_id
        )
        risk_report = self._risk.assess(
            backtest,
            self._config.risk,
            experiment_id=experiment_id,
            strategy_id=hypothesis.strategy_id,
            monte_carlo_runs=self._config.validation.monte_carlo_runs,
        )

        checklist = self._validator.build_checklist(
            statistics,
            adversarial,
            risk_report,
            broker_report,
            self._config.validation,
            self._config.risk,
        )
        decision = self._validator.decide(
            hypothesis.strategy_id,
            experiment_id,
            checklist,
            actor=self._validator_actor,
            require_broker_risk=require_broker_risk,
        )

        if decision.new_state == StrategyStatus.REJECTED.value:
            outcome.rejected += 1
        elif decision.new_state == StrategyStatus.NEEDS_RESEARCH.value:
            outcome.needs_research += 1
        else:
            outcome.advanced += 1

        reports.append(
            self._reporter.strategy_report(
                statistics, adversarial, risk_report, broker_report, decision
            )
        )

    def pause(self, reason: str) -> None:
        """Pausa o sistema de forma auditável."""
        self._system_state.transition(
            SystemStatus.PAUSED, reason, actor=self._supervisor_actor
        )

    def stop(self, reason: str) -> None:
        """Encerra o ciclo de forma auditável."""
        if self.system_status is SystemStatus.RUNNING:
            self._system_state.transition(
                SystemStatus.STOPPED, reason, actor=self._supervisor_actor
            )


def broker_risk_blocks_demo(status: Verdict) -> bool:
    """Broker Risk diferente de PASS impede qualquer uso de DEMO (seção 16.1)."""
    return status is not Verdict.PASS
