"""Campanha longa de pesquisa — varre o espaço de busca em lotes, com retomada.

Desenhado para execução autônoma e prolongada. Características:

- **Retomável**: combinações já testadas são reconstruídas do banco, então
  interromper e reiniciar continua de onde parou em vez de repetir.
- **Respeita o kill switch**: para imediatamente se o sistema entrar em
  EMERGENCY_STOPPED, e não retoma sozinho.
- **Tolerante a falha**: erro em um lote é registrado e a campanha segue.
- **Orçamentada**: limites de tempo e de hipóteses evitam execução ilimitada.
- **Preserva resultado negativo**: tudo fica em auditoria, nada é descartado.

USO
    $env:PYTHONPATH = "src"
    python scripts/run_campaign.py --dataset-id DATA-EURUSD-OTC-M1 --payout 0.89 `
        --max-hours 3 --batch 12

Nenhuma ordem é enviada. Modo RESEARCH mantém execução desabilitada.
"""

from __future__ import annotations

import argparse
import dataclasses
import time
from datetime import UTC, datetime
from pathlib import Path

from ai_trading_lab.configuration import load_config_file
from ai_trading_lab.data_persistence import DatasetStore
from ai_trading_lab.errors import TradingLabError
from ai_trading_lab.health import ReadinessState
from ai_trading_lab.models import SystemStatus
from ai_trading_lab.persistence import SQLiteStore
from ai_trading_lab.runtime import ResearchRuntime


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument(
        "--payout",
        type=float,
        required=True,
        help="payout real do ativo; use scripts/list_actives.py para descobrir",
    )
    parser.add_argument("--config", type=Path, default=Path("configs/research.yaml"))
    parser.add_argument("--state-db", type=Path, default=Path("logs/state.db"))
    parser.add_argument(
        "--dataset-db", type=Path, default=Path("data/datasets/datasets.db")
    )
    parser.add_argument(
        "--batch", type=int, default=12, help="hipóteses por lote"
    )
    parser.add_argument(
        "--max-hours", type=float, default=3.0, help="orçamento de tempo total"
    )
    parser.add_argument(
        "--max-hypotheses",
        type=int,
        default=0,
        help="limite total de hipóteses; 0 = varrer o espaço inteiro",
    )
    parser.add_argument(
        "--monte-carlo-runs",
        type=int,
        default=200,
        help="iterações de Monte Carlo por hipótese na varredura",
    )
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument(
        "--report-every", type=int, default=1, help="lotes entre relatórios"
    )
    args = parser.parse_args()

    try:
        config = load_config_file(args.config)
    except TradingLabError as error:
        print(f"ERRO de configuração: {error}")
        return 2

    config = dataclasses.replace(
        config,
        research=dataclasses.replace(
            config.research, max_experiments_per_cycle=args.batch
        ),
        validation=dataclasses.replace(
            config.validation,
            monte_carlo_runs=args.monte_carlo_runs,
            walk_forward_folds=args.folds,
        ),
    )

    store = SQLiteStore(args.state_db)
    datasets = DatasetStore(args.dataset_db)
    try:
        return _run(args, config, store, datasets)
    finally:
        store.close()
        datasets.close()


def _run(args, config, store: SQLiteStore, datasets: DatasetStore) -> int:
    runtime = ResearchRuntime(config, store, datasets)

    health = runtime.health((args.dataset_id,))
    if health.readiness is not ReadinessState.READY:
        print(f"campanha não iniciada: readiness={health.readiness.value}")
        if health.readiness is ReadinessState.NO_DATA:
            print("colete dados primeiro: scripts/collect_candles.py")
        return 1

    espaco = runtime.search_space_size
    ja_testadas = runtime.tried_count
    limite = args.max_hypotheses or espaco

    print("=" * 62)
    print("CAMPANHA DE PESQUISA")
    print("=" * 62)
    print(f"dataset:          {args.dataset_id}")
    print(f"payout:           {args.payout}  (empate em {1/(1+args.payout):.2%})")
    print(f"espaço de busca:  {espaco} regras")
    print(f"já testadas:      {ja_testadas}")
    print(f"orçamento:        {args.max_hours}h, até {limite} hipóteses")
    print(f"lote:             {args.batch} | folds: {args.folds} | MC: {args.monte_carlo_runs}")
    print(f"início:           {datetime.now(UTC).isoformat(timespec='seconds')}")
    print("=" * 62)
    print()

    deadline = time.monotonic() + args.max_hours * 3600.0
    inicio = time.monotonic()
    ciclo = 0
    totais = {"avaliadas": 0, "avancaram": 0, "rejeitadas": 0, "needs": 0, "erros": 0}

    while True:
        if time.monotonic() >= deadline:
            print("\norçamento de tempo esgotado")
            break
        if runtime.tried_count - ja_testadas >= limite:
            print("\nlimite de hipóteses alcançado")
            break
        if runtime.tried_count >= espaco:
            print("\nespaço de busca varrido por completo")
            break

        estado = runtime.system_status
        if estado is SystemStatus.EMERGENCY_STOPPED:
            print("\nEMERGENCY_STOPPED: campanha interrompida e não retoma sozinha")
            return 3

        ciclo += 1
        try:
            resultado = runtime.run_cycle(
                args.dataset_id, payout=args.payout, cycle_index=ciclo
            )
        except TradingLabError as error:
            totais["erros"] += 1
            print(f"lote {ciclo}: ERRO {type(error).__name__}: {error}")
            if totais["erros"] >= config.research.max_retries_per_agent:
                print("erros consecutivos demais: campanha pausada para revisão")
                runtime.pause("erros repetidos na campanha")
                return 4
            continue

        if resultado.evaluated == 0 and not resultado.reports:
            print(f"lote {ciclo}: nada avaliado; encerrando")
            break

        totais["avaliadas"] += resultado.evaluated
        totais["avancaram"] += resultado.advanced
        totais["rejeitadas"] += resultado.rejected
        totais["needs"] += resultado.needs_research
        totais["erros"] += len(resultado.errors)

        if ciclo % args.report_every == 0:
            decorrido = time.monotonic() - inicio
            progresso = runtime.tried_count / espaco if espaco else 0.0
            ritmo = totais["avaliadas"] / decorrido if decorrido > 0 else 0.0
            restantes = espaco - runtime.tried_count
            eta = restantes / ritmo / 60 if ritmo > 0 else 0.0
            print(
                f"lote {ciclo:>4} | "
                f"testadas {runtime.tried_count:>5}/{espaco} ({progresso:.1%}) | "
                f"avançaram {totais['avancaram']:>3} | "
                f"rejeitadas {totais['rejeitadas']:>5} | "
                f"pesquisa {totais['needs']:>4} | "
                f"{decorrido/60:.0f}min | ETA {eta:.0f}min"
            )
        for erro in resultado.errors[:2]:
            print(f"        {erro}")

    _resumo_final(runtime, totais, inicio, espaco, args)
    return 0


def _resumo_final(runtime, totais, inicio, espaco, args) -> None:
    decorrido = time.monotonic() - inicio
    print()
    print("=" * 62)
    print("CAMPANHA ENCERRADA")
    print("=" * 62)
    print(f"duração:       {decorrido/60:.1f} min")
    print(f"testadas:      {runtime.tried_count} de {espaco}")
    print(f"avaliadas:     {totais['avaliadas']}")
    print(f"avançaram:     {totais['avancaram']}")
    print(f"rejeitadas:    {totais['rejeitadas']}")
    print(f"mais pesquisa: {totais['needs']}")
    print(f"erros:         {totais['erros']}")
    print(f"estado final:  {runtime.system_status.value}")
    print()
    print("Para ver o ranking, incluindo os resultados negativos:")
    print(
        f"  python scripts/ranking.py --dataset-id {args.dataset_id} "
        f"--payout {args.payout} --top 20"
    )
    if totais["avancaram"] == 0:
        print()
        print(
            "Nenhuma estratégia avançou. Em dado sem vantagem real, esse é o\n"
            "resultado esperado — uma validação que aprova qualquer coisa está\n"
            "quebrada, não generosa."
        )


if __name__ == "__main__":
    raise SystemExit(main())
