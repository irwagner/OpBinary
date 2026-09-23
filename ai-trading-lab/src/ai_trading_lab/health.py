"""Health check e data check do ciclo autônomo (MASTER_SPEC seção 40).

O sistema pode estar operacional e ainda assim não ter dados para pesquisar.
Esse caso é reportado explicitamente como `NO_DATA`, não como falha nem como
sucesso silencioso.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .configuration import SystemConfig
from .contracts import Verdict
from .data_persistence import DatasetStore
from .models import SystemMode, SystemStatus
from .persistence import SQLiteStore


class ReadinessState(StrEnum):
    """Prontidão do sistema para executar um ciclo de pesquisa."""

    READY = "READY"
    NO_DATA = "NO_DATA"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class HealthReport:
    """Resultado consolidado do health check."""

    readiness: ReadinessState
    system_status: SystemStatus
    mode: SystemMode
    execution_allowed: bool
    real_blocked: bool
    dataset_count: int
    checks: tuple[tuple[str, Verdict, str], ...]

    @property
    def can_run_cycle(self) -> bool:
        return self.readiness is ReadinessState.READY


def run_health_check(
    config: SystemConfig,
    store: SQLiteStore,
    dataset_store: DatasetStore,
    *,
    dataset_ids: tuple[str, ...] = (),
) -> HealthReport:
    """Verifica configuração, estado global, barreiras de segurança e dados."""
    checks: list[tuple[str, Verdict, str]] = []

    state = store.load_system_state()
    system_status = state.status if state else SystemStatus.IDLE
    checks.append(("state_loaded", Verdict.PASS, f"estado global: {system_status.value}"))

    real_blocked = not config.real_allowed and not config.real.enabled
    checks.append(
        (
            "real_blocked",
            Verdict.PASS if real_blocked else Verdict.FAIL,
            "REAL bloqueado por configuração" if real_blocked else "REAL não está bloqueado",
        )
    )

    kill_switch_ok = config.security.kill_switch_enabled
    checks.append(
        (
            "kill_switch",
            Verdict.PASS if kill_switch_ok else Verdict.FAIL,
            "kill switch habilitado" if kill_switch_ok else "kill switch desabilitado",
        )
    )

    if config.mode is SystemMode.RESEARCH and config.execution.enabled:
        checks.append(("execution_barrier", Verdict.FAIL, "RESEARCH com execução habilitada"))
    else:
        checks.append(
            (
                "execution_barrier",
                Verdict.PASS,
                f"execução {'habilitada' if config.execution_allowed else 'desabilitada'}",
            )
        )

    available = tuple(
        dataset_id for dataset_id in dataset_ids if dataset_store.latest_version_number(dataset_id)
    )
    checks.append(
        (
            "datasets_available",
            Verdict.PASS if available else Verdict.WARN,
            f"{len(available)} dataset(s) com versão registrada",
        )
    )

    if system_status is SystemStatus.EMERGENCY_STOPPED:
        readiness = ReadinessState.BLOCKED
    elif any(verdict is Verdict.FAIL for _, verdict, _ in checks):
        readiness = ReadinessState.BLOCKED
    elif not available:
        readiness = ReadinessState.NO_DATA
    else:
        readiness = ReadinessState.READY

    return HealthReport(
        readiness=readiness,
        system_status=system_status,
        mode=config.mode,
        execution_allowed=config.execution_allowed,
        real_blocked=real_blocked,
        dataset_count=len(available),
        checks=tuple(checks),
    )
