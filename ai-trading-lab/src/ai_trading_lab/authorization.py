"""Autorização mínima e centralizada para ações da infraestrutura."""

from __future__ import annotations

from enum import StrEnum
from typing import Mapping

from .errors import PermissionDeniedError
from .models import Actor, ActorRole


class Capability(StrEnum):
    """Capacidades protegidas disponíveis na Fase 1."""

    MANAGE_SYSTEM_STATE = "MANAGE_SYSTEM_STATE"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    INITIALIZE_STRATEGY = "INITIALIZE_STRATEGY"
    TRANSITION_STRATEGY = "TRANSITION_STRATEGY"
    REQUEST_REAL_PROMOTION = "REQUEST_REAL_PROMOTION"
    DECIDE_REAL_PROMOTION = "DECIDE_REAL_PROMOTION"


_DEFAULT_GRANTS: Mapping[Capability, frozenset[ActorRole]] = {
    Capability.MANAGE_SYSTEM_STATE: frozenset(
        {ActorRole.SYSTEM, ActorRole.SUPERVISOR, ActorRole.HUMAN}
    ),
    Capability.EMERGENCY_STOP: frozenset({ActorRole.SYSTEM, ActorRole.HUMAN}),
    Capability.INITIALIZE_STRATEGY: frozenset({ActorRole.SUPERVISOR}),
    Capability.TRANSITION_STRATEGY: frozenset({ActorRole.VALIDATOR}),
    Capability.REQUEST_REAL_PROMOTION: frozenset({ActorRole.SUPERVISOR}),
    Capability.DECIDE_REAL_PROMOTION: frozenset({ActorRole.HUMAN}),
}


class AuthorizationPolicy:
    """Aplica uma allowlist fechada de papéis por capacidade."""

    def __init__(
        self, grants: Mapping[Capability, frozenset[ActorRole]] = _DEFAULT_GRANTS
    ) -> None:
        self._grants = dict(grants)

    def require(self, actor: Actor, capability: Capability) -> None:
        """Nega a ação quando o papel não possui a capacidade solicitada."""
        if actor.role not in self._grants.get(capability, frozenset()):
            raise PermissionDeniedError(
                f"{actor.role.value} não possui {capability.value}"
            )
