"""Entrypoint de linha de comando do laboratório.

Comandos disponíveis:

    status    — mostra dashboard, health check e datasets
    agents    — lista os agentes registrados
    cycle     — executa um ciclo de pesquisa em modo RESEARCH
    stop      — encerra o ciclo de forma auditável

Nenhum comando envia operação. `--mode real` é aceito apenas para inspeção:
a configuração de REAL reprova execução por construção.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .configuration import SystemConfig, load_config_file
from .dashboard import (
    count_strategies,
    render_agent_screen,
    render_dataset_screen,
    render_health_screen,
    render_main_screen,
)
from .data_persistence import DatasetStore
from .errors import TradingLabError
from .logging import configure_structured_logger, log_event
from .models import Actor, ActorRole, SystemStatus
from .persistence import SQLiteStore
from .runtime import ResearchRuntime
from .state import StateManager

DEFAULT_CONFIG_DIR = Path("configs")
DEFAULT_STATE_DB = Path("logs/state.db")
DEFAULT_DATASET_DB = Path("data/datasets/datasets.db")


def build_parser() -> argparse.ArgumentParser:
    """Monta o parser de argumentos da CLI."""
    parser = argparse.ArgumentParser(prog="ai-trading-lab", description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "status",
            "agents",
            "cycle",
            "stop",
            "reset",
            "emergency-stop",
            "clear-emergency",
        ),
        help="ação a executar",
    )
    parser.add_argument(
        "--operator",
        default=None,
        help="identificação do humano responsável (obrigatório no kill switch)",
    )
    parser.add_argument("--reason", default=None, help="motivo registrado em auditoria")
    parser.add_argument(
        "--mode",
        default="research",
        choices=("research", "demo", "real"),
        help="arquivo de configuração a carregar (default: research)",
    )
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument("--state-db", type=Path, default=DEFAULT_STATE_DB)
    parser.add_argument("--dataset-db", type=Path, default=DEFAULT_DATASET_DB)
    parser.add_argument("--dataset-id", default=None, help="dataset alvo do ciclo")
    parser.add_argument(
        "--payout",
        type=float,
        default=None,
        help="payout real do ativo/corretora; obrigatório em 'cycle'",
    )
    parser.add_argument("--cycle-index", type=int, default=1)
    return parser


def main(argv: tuple[str, ...] | None = None) -> int:
    """Executa a CLI e devolve o código de saída."""
    args = build_parser().parse_args(argv)
    logger = configure_structured_logger("ai_trading_lab.cli", sys.stdout)

    try:
        config = load_config_file(args.config_dir / f"{args.mode}.yaml")
    except TradingLabError as error:
        print(f"ERRO de configuração: {error}", file=sys.stderr)
        return 2

    _ensure_parent(args.state_db)
    _ensure_parent(args.dataset_db)
    store = SQLiteStore(args.state_db)
    dataset_store = DatasetStore(args.dataset_db)

    try:
        return _dispatch(args, config, store, dataset_store, logger)
    except TradingLabError as error:
        print(f"ERRO: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    finally:
        store.close()
        dataset_store.close()


def _dispatch(args, config: SystemConfig, store, dataset_store, logger) -> int:
    dataset_ids = (args.dataset_id,) if args.dataset_id else ()
    runtime = ResearchRuntime(config, store, dataset_store)

    if args.command == "agents":
        print(render_agent_screen())
        return 0

    if args.command == "status":
        health = runtime.health(dataset_ids)
        print(render_main_screen(config, health, count_strategies(store)))
        print()
        print(render_health_screen(health))
        print()
        print(render_dataset_screen(dataset_store, dataset_ids))
        return 0

    if args.command == "stop":
        runtime.stop("stop solicitado via CLI")
        print(f"Sistema em {runtime.system_status.value}")
        return 0

    if args.command == "reset":
        if not args.operator:
            print(
                "ERRO: reset exige --operator com a identificação do responsável",
                file=sys.stderr,
            )
            return 2
        snapshot = StateManager(store).transition(
            SystemStatus.IDLE,
            args.reason or "reset para IDLE via CLI",
            actor=Actor(args.operator, ActorRole.HUMAN),
        )
        print(f"Sistema em {snapshot.status.value}")
        return 0

    if args.command in {"emergency-stop", "clear-emergency"}:
        if not args.operator:
            print(
                "ERRO: kill switch exige --operator com a identificação do humano responsável",
                file=sys.stderr,
            )
            return 2
        operator = Actor(args.operator, ActorRole.HUMAN)
        state_manager = StateManager(store)
        if args.command == "emergency-stop":
            snapshot = state_manager.emergency_stop(
                args.reason or "kill switch acionado via CLI", actor=operator
            )
        else:
            snapshot = state_manager.clear_emergency_stop(
                args.reason or "emergency stop liberado via CLI", actor=operator
            )
        log_event(
            logger,
            "kill_switch_action",
            command=args.command,
            operator=args.operator,
            status=snapshot.status.value,
        )
        print(f"Sistema em {snapshot.status.value}")
        return 0

    if not args.dataset_id:
        print("ERRO: 'cycle' exige --dataset-id", file=sys.stderr)
        return 2
    if args.payout is None:
        print(
            "ERRO: 'cycle' exige --payout com o payout real do ativo/corretora "
            "(nunca um valor inventado)",
            file=sys.stderr,
        )
        return 2

    outcome = runtime.run_cycle(
        args.dataset_id, payout=args.payout, cycle_index=args.cycle_index
    )
    log_event(
        logger,
        "research_cycle_finished",
        readiness=outcome.readiness.value,
        evaluated=outcome.evaluated,
        advanced=outcome.advanced,
        rejected=outcome.rejected,
        needs_research=outcome.needs_research,
        errors=len(outcome.errors),
    )
    for report in outcome.reports:
        print(report)
        print()
    return 0 if outcome.readiness.value == "READY" else 3


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
