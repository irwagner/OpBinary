"""Classe base de agente e allowlist de tarefas por agente.

A allowlist é fechada: um agente que solicite uma tarefa fora do seu conjunto
é negado pelo Supervisor e o evento fica registrado em auditoria
(SECURITY_MODEL seção 1).
"""

from __future__ import annotations

from typing import Mapping, Protocol

from ..contracts import AgentEnvelope, TaskType
from ..models import AuditEvent

AGENT_TASKS: Mapping[str, frozenset[TaskType]] = {
    "researcher": frozenset({TaskType.GENERATE_HYPOTHESIS}),
    "quant": frozenset({TaskType.FORMALIZE_STRATEGY}),
    "data": frozenset({TaskType.COLLECT_DATA}),
    "backtester": frozenset({TaskType.RUN_BACKTEST}),
    "statistician": frozenset({TaskType.RUN_STATISTICS}),
    "adversarial": frozenset({TaskType.RUN_ADVERSARIAL}),
    "risk": frozenset({TaskType.RUN_RISK}),
    "broker_risk": frozenset({TaskType.RUN_BROKER_RISK}),
    "validator": frozenset({TaskType.DECIDE_VALIDATION}),
    "reporter": frozenset({TaskType.BUILD_REPORT}),
}


class AuditSink(Protocol):
    """Porta mínima de auditoria usada pelos agentes."""

    def append_audit_event(self, event: AuditEvent) -> int: ...


class BaseAgent:
    """Base comum: identidade, versão e registro auditável de execução."""

    name: str = "base"
    version: str = "v0.1.0"

    def __init__(
        self,
        software_version: str = "v0.1.0",
        audit_sink: AuditSink | None = None,
    ) -> None:
        self.software_version = software_version
        self._audit_sink = audit_sink

    @property
    def allowed_tasks(self) -> frozenset[TaskType]:
        """Tarefas que este agente pode solicitar."""
        return AGENT_TASKS.get(self.name, frozenset())

    def envelope(
        self,
        *,
        experiment_id: str | None = None,
        input_ref: str | None = None,
        decision: str | None = None,
        reason: str | None = None,
    ) -> AgentEnvelope:
        """Monta o envelope de auditoria padrão do output."""
        return AgentEnvelope(
            agent_name=self.name,
            agent_version=self.version,
            software_version=self.software_version,
            experiment_id=experiment_id,
            input_ref=input_ref,
            decision=decision,
            reason=reason,
        )

    def record(
        self,
        event_type: str,
        payload: Mapping[str, object],
        experiment_id: str | None = None,
    ) -> None:
        """Registra a execução em auditoria, quando houver sink configurado."""
        if self._audit_sink is None:
            return
        self._audit_sink.append_audit_event(
            AuditEvent(
                event_type=event_type,
                actor=self.name,
                payload={
                    "agent_version": self.version,
                    "software_version": self.software_version,
                    **payload,
                },
                experiment_id=experiment_id,
            )
        )
