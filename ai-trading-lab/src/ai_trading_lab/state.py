"""Máquinas de estado persistidas e protegidas por autorização."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .authorization import AuthorizationPolicy, Capability
from .errors import (
    ConcurrentStateUpdate,
    InvalidStateTransition,
    PermissionDeniedError,
    PromotionApprovalRequired,
    PromotionRequestError,
)
from .models import (
    Actor,
    AuditEvent,
    PromotionRequest,
    PromotionStatus,
    StrategyStateSnapshot,
    StrategyStatus,
    SystemStateSnapshot,
    SystemStatus,
    utc_now,
)
from .transitions import validate_strategy_transition, validate_system_transition


class StateRepository(Protocol):
    """Porta mínima para estado, promoção e auditoria."""

    def load_system_state(self) -> SystemStateSnapshot | None: ...

    def initialize_system_state(
        self, snapshot: SystemStateSnapshot, event: AuditEvent
    ) -> SystemStateSnapshot: ...

    def transition_system_state(
        self,
        expected_status: SystemStatus,
        snapshot: SystemStateSnapshot,
        event: AuditEvent,
        *,
        actor: Actor,
    ) -> None: ...

    def emergency_stop_system(
        self,
        snapshot: SystemStateSnapshot,
        event: AuditEvent,
        *,
        actor: Actor,
    ) -> SystemStateSnapshot: ...

    def clear_emergency_stop(
        self,
        snapshot: SystemStateSnapshot,
        event: AuditEvent,
        *,
        actor: Actor,
    ) -> SystemStateSnapshot: ...

    def load_strategy_state(self, strategy_id: str) -> StrategyStateSnapshot | None: ...

    def initialize_strategy_state(
        self,
        snapshot: StrategyStateSnapshot,
        event: AuditEvent,
        *,
        actor: Actor,
    ) -> None: ...

    def transition_strategy_state(
        self,
        expected_status: StrategyStatus,
        snapshot: StrategyStateSnapshot,
        event: AuditEvent,
        *,
        actor: Actor,
    ) -> None: ...

    def append_promotion_request(
        self,
        request: PromotionRequest,
        event: AuditEvent,
        *,
        actor: Actor,
    ) -> None: ...

    def load_promotion_request(self, request_id: str) -> PromotionRequest | None: ...

    def decide_promotion_request(
        self,
        request_id: str,
        status: PromotionStatus,
        decided_by: str,
        decided_at: datetime,
        reason: str | None,
        event: AuditEvent,
        *,
        actor: Actor,
    ) -> PromotionRequest: ...

    def has_approved_promotion(self, strategy_id: str) -> bool: ...

    def append_audit_event(self, event: AuditEvent) -> int: ...


class StateManager:
    """Controla o estado global com compare-and-swap e auditoria atômica."""

    def __init__(
        self,
        repository: StateRepository,
        policy: AuthorizationPolicy | None = None,
    ) -> None:
        self._repository = repository
        self._policy = policy or AuthorizationPolicy()
        loaded = repository.load_system_state()
        if loaded is None:
            initial = SystemStateSnapshot(SystemStatus.IDLE)
            loaded = repository.initialize_system_state(
                initial,
                AuditEvent(
                    event_type="system_initialized",
                    actor="system",
                    payload={"status": SystemStatus.IDLE.value},
                ),
            )
        self._snapshot = loaded

    @property
    def snapshot(self) -> SystemStateSnapshot:
        """Expõe snapshot imutável do estado atual."""
        return self._snapshot

    def transition(
        self,
        target: SystemStatus,
        reason: str | None = None,
        *,
        actor: Actor,
    ) -> SystemStateSnapshot:
        """Aplica uma transição autorizada, validada e atômica."""
        if target is SystemStatus.EMERGENCY_STOPPED:
            return self.emergency_stop(
                reason or "emergency stop requested", actor=actor
            )
        _require_permission(
            self._repository,
            self._policy,
            actor,
            Capability.MANAGE_SYSTEM_STATE,
        )
        current = self._repository.load_system_state()
        if current is None:
            raise InvalidStateTransition("estado global não inicializado")
        self._snapshot = current
        validate_system_transition(current.status, target)
        candidate = SystemStateSnapshot(status=target, reason=reason)
        event = AuditEvent(
            event_type="system_state_changed",
            actor=actor.actor_id,
            payload={
                "actor_role": actor.role.value,
                "previous_status": current.status.value,
                "status": target.value,
                "reason": reason,
            },
        )
        try:
            self._repository.transition_system_state(
                current.status,
                candidate,
                event,
                actor=actor,
            )
        except ConcurrentStateUpdate:
            self._refresh()
            raise
        self._snapshot = candidate
        return candidate

    def emergency_stop(self, reason: str, *, actor: Actor) -> SystemStateSnapshot:
        """Interrompe o sistema sem permitir que escritores obsoletos o revertam."""
        _require_permission(
            self._repository,
            self._policy,
            actor,
            Capability.EMERGENCY_STOP,
        )
        latest = self._repository.load_system_state()
        if latest is None:
            raise InvalidStateTransition("estado global não inicializado")
        self._snapshot = latest
        if latest.status is SystemStatus.EMERGENCY_STOPPED:
            raise InvalidStateTransition("sistema já está em EMERGENCY_STOPPED")
        candidate = SystemStateSnapshot(
            status=SystemStatus.EMERGENCY_STOPPED,
            reason=reason,
        )
        event = AuditEvent(
            event_type="emergency_stop",
            actor=actor.actor_id,
            payload={
                "actor_role": actor.role.value,
                "status": SystemStatus.EMERGENCY_STOPPED.value,
                "reason": reason,
            },
        )
        persisted = self._repository.emergency_stop_system(
            candidate,
            event,
            actor=actor,
        )
        self._snapshot = persisted
        return persisted

    def clear_emergency_stop(self, reason: str, *, actor: Actor) -> SystemStateSnapshot:
        """Sai de EMERGENCY_STOPPED para STOPPED por ação humana explícita.

        Não retoma a operação: o sistema fica em STOPPED e voltar a RUNNING
        exige uma segunda decisão deliberada.
        """
        latest = self._repository.load_system_state()
        if latest is None:
            raise InvalidStateTransition("estado global não inicializado")
        self._snapshot = latest
        if latest.status is not SystemStatus.EMERGENCY_STOPPED:
            raise InvalidStateTransition("sistema não está em EMERGENCY_STOPPED")

        candidate = SystemStateSnapshot(status=SystemStatus.STOPPED, reason=reason)
        event = AuditEvent(
            event_type="emergency_stop_cleared",
            actor=actor.actor_id,
            payload={
                "actor_role": actor.role.value,
                "previous_status": SystemStatus.EMERGENCY_STOPPED.value,
                "status": SystemStatus.STOPPED.value,
                "reason": reason,
            },
        )
        persisted = self._repository.clear_emergency_stop(candidate, event, actor=actor)
        self._snapshot = persisted
        return persisted

    def _refresh(self) -> None:
        current = self._repository.load_system_state()
        if current is not None:
            self._snapshot = current


class StrategyStateManager:
    """Impede salto de etapas e restringe transições ao Validator."""

    def __init__(
        self,
        repository: StateRepository,
        policy: AuthorizationPolicy | None = None,
    ) -> None:
        self._repository = repository
        self._policy = policy or AuthorizationPolicy()

    def initialize(
        self,
        strategy_id: str,
        *,
        actor: Actor,
        reason: str | None = None,
    ) -> StrategyStateSnapshot:
        """Inicializa uma estratégia em IDEA por autorização do Supervisor."""
        _require_permission(
            self._repository,
            self._policy,
            actor,
            Capability.INITIALIZE_STRATEGY,
        )
        snapshot = StrategyStateSnapshot(
            strategy_id=strategy_id,
            status=StrategyStatus.IDEA,
            reason=reason,
        )
        self._repository.initialize_strategy_state(
            snapshot,
            AuditEvent(
                event_type="strategy_initialized",
                actor=actor.actor_id,
                payload={
                    "actor_role": actor.role.value,
                    "strategy_id": strategy_id,
                    "status": StrategyStatus.IDEA.value,
                    "reason": reason,
                },
            ),
            actor=actor,
        )
        return snapshot

    def load(self, strategy_id: str) -> StrategyStateSnapshot | None:
        """Lê o estado atual de uma estratégia (leitura não exige capacidade)."""
        return self._repository.load_strategy_state(strategy_id)

    def transition(
        self,
        strategy_id: str,
        target: StrategyStatus,
        *,
        actor: Actor,
        reason: str | None = None,
    ) -> StrategyStateSnapshot:
        """Transiciona sequencialmente e exige aprovação persistida para REAL."""
        _require_permission(
            self._repository,
            self._policy,
            actor,
            Capability.TRANSITION_STRATEGY,
        )
        current = self._repository.load_strategy_state(strategy_id)
        if current is None:
            raise InvalidStateTransition("estratégia não inicializada")
        validate_strategy_transition(current.status, target)
        if target is StrategyStatus.REAL and not self._repository.has_approved_promotion(
            strategy_id
        ):
            self._repository.append_audit_event(
                AuditEvent(
                    event_type="strategy_transition_blocked",
                    actor=actor.actor_id,
                    payload={
                        "actor_role": actor.role.value,
                        "strategy_id": strategy_id,
                        "target": target.value,
                        "reason": "human approval required",
                    },
                )
            )
            raise PromotionApprovalRequired(
                "REAL exige aprovação humana persistida"
            )
        candidate = StrategyStateSnapshot(
            strategy_id=strategy_id,
            status=target,
            reason=reason,
        )
        self._repository.transition_strategy_state(
            current.status,
            candidate,
            AuditEvent(
                event_type="strategy_state_changed",
                actor=actor.actor_id,
                payload={
                    "actor_role": actor.role.value,
                    "strategy_id": strategy_id,
                    "previous_status": current.status.value,
                    "status": target.value,
                    "reason": reason,
                },
            ),
            actor=actor,
        )
        return candidate


class PromotionManager:
    """Registra pedidos e decisões humanas sem habilitar execução REAL."""

    def __init__(
        self,
        repository: StateRepository,
        policy: AuthorizationPolicy | None = None,
    ) -> None:
        self._repository = repository
        self._policy = policy or AuthorizationPolicy()

    def request(
        self,
        request_id: str,
        strategy_id: str,
        *,
        actor: Actor,
        reason: str | None = None,
    ) -> PromotionRequest:
        """Cria solicitação somente para estratégia em HUMAN_REVIEW."""
        _require_permission(
            self._repository,
            self._policy,
            actor,
            Capability.REQUEST_REAL_PROMOTION,
        )
        strategy = self._repository.load_strategy_state(strategy_id)
        if strategy is None or strategy.status is not StrategyStatus.HUMAN_REVIEW:
            raise PromotionRequestError(
                "promoção só pode ser solicitada em HUMAN_REVIEW"
            )
        request = PromotionRequest(
            request_id=request_id,
            strategy_id=strategy_id,
            reason=reason,
        )
        self._repository.append_promotion_request(
            request,
            AuditEvent(
                event_type="promotion_requested",
                actor=actor.actor_id,
                payload={
                    "actor_role": actor.role.value,
                    "request_id": request_id,
                    "strategy_id": strategy_id,
                    "status": PromotionStatus.PENDING.value,
                    "reason": reason,
                },
            ),
            actor=actor,
        )
        return request

    def decide(
        self,
        request_id: str,
        decision: PromotionStatus,
        *,
        actor: Actor,
        reason: str | None = None,
    ) -> PromotionRequest:
        """Aceita somente aprovação ou rejeição por ator humano."""
        _require_permission(
            self._repository,
            self._policy,
            actor,
            Capability.DECIDE_REAL_PROMOTION,
        )
        if decision not in {PromotionStatus.APPROVED, PromotionStatus.REJECTED}:
            raise PromotionRequestError("decisão deve ser APPROVED ou REJECTED")
        decided_at = utc_now()
        return self._repository.decide_promotion_request(
            request_id=request_id,
            status=decision,
            decided_by=actor.actor_id,
            decided_at=decided_at,
            reason=reason,
            event=AuditEvent(
                event_type="promotion_decided",
                actor=actor.actor_id,
                payload={
                    "actor_role": actor.role.value,
                    "request_id": request_id,
                    "status": decision.value,
                    "reason": reason,
                },
            ),
            actor=actor,
        )


def _require_permission(
    repository: StateRepository,
    policy: AuthorizationPolicy,
    actor: Actor,
    capability: Capability,
) -> None:
    try:
        policy.require(actor, capability)
    except PermissionDeniedError:
        repository.append_audit_event(
            AuditEvent(
                event_type="permission_denied",
                actor=actor.actor_id,
                payload={
                    "actor_role": actor.role.value,
                    "capability": capability.value,
                },
            )
        )
        raise
