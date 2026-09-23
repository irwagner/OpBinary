"""Dashboard somente leitura (MASTER_SPEC seções 37, 38, 39).

Não possui nenhuma ação de escrita: não transiciona estado, não aprova
promoção e não altera configuração. Apenas lê e formata.
"""

from __future__ import annotations

from dataclasses import dataclass

from .configuration import SystemConfig
from .data_persistence import DatasetStore
from .health import HealthReport
from .models import StrategyStatus
from .persistence import SQLiteStore

AGENT_NAMES = (
    "Supervisor",
    "Researcher",
    "Quant",
    "Data",
    "Backtester",
    "Statistician",
    "Adversarial",
    "Risk",
    "Broker Risk",
    "Validator",
    "Reporter",
)


@dataclass(frozen=True, slots=True)
class StrategyCounters:
    """Contadores de estratégias por situação."""

    total: int
    candidates: int
    validated: int
    rejected: int
    needs_research: int


def count_strategies(store: SQLiteStore) -> StrategyCounters:
    """Conta estratégias por estado, lendo diretamente o estado persistido."""
    rows = store._connection.execute(  # noqa: SLF001 - leitura de dashboard
        "SELECT status, COUNT(*) AS total FROM strategy_state GROUP BY status"
    ).fetchall()
    by_status = {row["status"]: int(row["total"]) for row in rows}
    return StrategyCounters(
        total=sum(by_status.values()),
        candidates=by_status.get(StrategyStatus.DEMO_CANDIDATE.value, 0),
        validated=by_status.get(StrategyStatus.DEMO.value, 0)
        + by_status.get(StrategyStatus.HUMAN_REVIEW.value, 0),
        rejected=by_status.get(StrategyStatus.REJECTED.value, 0),
        needs_research=by_status.get(StrategyStatus.NEEDS_RESEARCH.value, 0),
    )


def render_main_screen(
    config: SystemConfig,
    health: HealthReport,
    counters: StrategyCounters,
) -> str:
    """Tela principal do dashboard."""
    return "\n".join(
        (
            "AI TRADING LAB",
            "",
            f"Mode:              {config.mode.value}",
            f"System:            {health.system_status.value}",
            f"Readiness:         {health.readiness.value}",
            f"Execution:         {'ENABLED' if health.execution_allowed else 'DISABLED'}",
            f"REAL:              {'BLOCKED' if health.real_blocked else 'NOT BLOCKED'}",
            f"Datasets:          {health.dataset_count}",
            "",
            f"Strategies total:  {counters.total}",
            f"Candidates:        {counters.candidates}",
            f"Validated:         {counters.validated}",
            f"Rejected:          {counters.rejected}",
            f"Needs research:    {counters.needs_research}",
        )
    )


def render_agent_screen() -> str:
    """Tela de agentes registrados."""
    lines = ["AGENTS", ""]
    lines.extend(f"{name:<16} ONLINE" for name in AGENT_NAMES)
    return "\n".join(lines)


def render_health_screen(health: HealthReport) -> str:
    """Detalhe das verificações do health check."""
    lines = ["HEALTH CHECK", "", f"Readiness: {health.readiness.value}", ""]
    lines.extend(
        f"[{verdict.value:<4}] {name}: {detail}" for name, verdict, detail in health.checks
    )
    return "\n".join(lines)


def render_dataset_screen(dataset_store: DatasetStore, dataset_ids: tuple[str, ...]) -> str:
    """Versões de dataset conhecidas, com hash e cobertura."""
    lines = ["DATASETS", ""]
    if not dataset_ids:
        lines.append("nenhum dataset registrado")
        return "\n".join(lines)
    for dataset_id in dataset_ids:
        versions = dataset_store.list_versions(dataset_id)
        if not versions:
            lines.append(f"{dataset_id}: nenhuma versão registrada")
            continue
        for version in versions:
            lines.append(
                f"{version.dataset_id} v{version.version} [{version.stage.value}] "
                f"{version.point_count} pts "
                f"{version.coverage_start.isoformat()} -> {version.coverage_end.isoformat()} "
                f"hash={version.content_hash[:12]}"
            )
    return "\n".join(lines)
