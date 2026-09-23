"""Supervisor Agent: roteia tarefas e verifica pré-condições (ADR-001).

O Supervisor não produz resultado de domínio e não calcula métricas. Ele
autoriza ou nega o início de uma tarefa, verifica pré-condições e registra
a decisão em auditoria. Nunca promove DEMO → REAL.
"""

from __future__ import annotations

from ..contracts import PermissionDecision, PermissionRequest, TaskType, Verdict
from ..models import StrategyStatus, SystemStatus
from .base import AGENT_TASKS, AuditSink, BaseAgent


class SupervisorAgent(BaseAgent):
    """Gate central de autorização de tarefas dos agentes."""

    name = "supervisor"
    version = "v0.1.0"

    def __init__(
        self,
        software_version: str = "v0.1.0",
        audit_sink: AuditSink | None = None,
    ) -> None:
        super().__init__(software_version=software_version, audit_sink=audit_sink)

    def request_permission(
        self,
        request: PermissionRequest,
        *,
        system_status: SystemStatus,
        strategy_status: StrategyStatus | None = None,
    ) -> PermissionDecision:
        """Concede ou nega o início de uma tarefa, sempre registrando a decisão."""
        checked: list[str] = []

        allowed = AGENT_TASKS.get(request.agent_name, frozenset())
        checked.append("agent_task_allowlist")
        if request.task_type not in allowed:
            return self._deny(
                request,
                f"{request.agent_name} não pode executar {request.task_type.value}",
                tuple(checked),
            )

        checked.append("system_not_emergency_stopped")
        if system_status is SystemStatus.EMERGENCY_STOPPED:
            return self._deny(
                request,
                "sistema em EMERGENCY_STOPPED: nenhuma tarefa é autorizada",
                tuple(checked),
            )

        checked.append("system_status_allows_work")
        if system_status not in {SystemStatus.IDLE, SystemStatus.RUNNING}:
            return self._deny(
                request,
                f"status {system_status.value} não permite iniciar tarefas",
                tuple(checked),
            )

        checked.append("strategy_precondition")
        precondition_error = _check_strategy_precondition(request.task_type, strategy_status)
        if precondition_error is not None:
            return self._deny(request, precondition_error, tuple(checked))

        decision = PermissionDecision(
            status=Verdict.PASS,
            reason="pré-condições satisfeitas",
            checked_preconditions=tuple(checked),
        )
        self.record(
            "permission_granted",
            {
                "requesting_agent": request.agent_name,
                "task_type": request.task_type.value,
                "strategy_id": request.strategy_id,
                "checked": list(decision.checked_preconditions),
            },
            experiment_id=request.experiment_id,
        )
        return decision

    def _deny(
        self,
        request: PermissionRequest,
        reason: str,
        checked: tuple[str, ...],
    ) -> PermissionDecision:
        self.record(
            "permission_denied",
            {
                "requesting_agent": request.agent_name,
                "task_type": request.task_type.value,
                "strategy_id": request.strategy_id,
                "reason": reason,
                "checked": list(checked),
            },
            experiment_id=request.experiment_id,
        )
        return PermissionDecision(
            status=Verdict.FAIL, reason=reason, checked_preconditions=checked
        )


_REQUIRED_STRATEGY_STATE: dict[TaskType, frozenset[StrategyStatus]] = {
    TaskType.FORMALIZE_STRATEGY: frozenset({StrategyStatus.IDEA}),
    TaskType.RUN_BACKTEST: frozenset({StrategyStatus.IDEA, StrategyStatus.BACKTEST}),
    TaskType.RUN_STATISTICS: frozenset({StrategyStatus.BACKTEST, StrategyStatus.VALIDATION}),
    TaskType.RUN_ADVERSARIAL: frozenset(
        {StrategyStatus.BACKTEST, StrategyStatus.VALIDATION, StrategyStatus.OUT_OF_SAMPLE}
    ),
    TaskType.RUN_RISK: frozenset(
        {StrategyStatus.BACKTEST, StrategyStatus.VALIDATION, StrategyStatus.OUT_OF_SAMPLE}
    ),
}


def _check_strategy_precondition(
    task_type: TaskType, strategy_status: StrategyStatus | None
) -> str | None:
    required = _REQUIRED_STRATEGY_STATE.get(task_type)
    if required is None:
        return None
    if strategy_status is None:
        return f"{task_type.value} exige uma estratégia com estado conhecido"
    if strategy_status in {StrategyStatus.REJECTED, StrategyStatus.NEEDS_RESEARCH}:
        return f"estratégia em {strategy_status.value} não avança sem nova pesquisa"
    if strategy_status not in required:
        return (
            f"{task_type.value} exige estado em "
            f"{sorted(status.value for status in required)}, "
            f"mas estratégia está em {strategy_status.value}"
        )
    return None
