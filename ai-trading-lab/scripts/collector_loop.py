"""Coleta periódica e acumulativa de velas (somente leitura).

A plataforma só expõe uma janela curta de histórico. Rodar este loop ao longo de
dias e semanas acumula uma amostra muito maior do que qualquer download único
consegue — e é a única forma de viabilizar estudo de horizonte longo.

Cada ciclo grava uma **nova versão** de dataset, com hash próprio. Versões
anteriores nunca são sobrescritas, então o histórico de coleta é auditável.

O SSID expira. Quando isso acontece o loop reporta e encerra com código próprio,
para que a supervisão saiba que precisa de um SSID novo — em vez de ficar
tentando em silêncio.

USO
    $env:PYTHONPATH = "src"
    $env:BROKER_SSID = "<ssid>"
    python scripts/collector_loop.py --active-id 76 --asset EURUSD-OTC `
        --dataset-id DATA-EURUSD-OTC-M1 --interval-minutes 60 --max-hours 12

Nenhuma ordem é enviada.
"""

from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime
from pathlib import Path

from ai_trading_lab.collectors.quadcode import (
    DEFAULT_ENDPOINT,
    CollectorConfig,
    CollectorSession,
)
from ai_trading_lab.data_ingestion import ingest_raw_batch
from ai_trading_lab.data_models import DataOrigin
from ai_trading_lab.data_persistence import DatasetStore
from ai_trading_lab.errors import DataIngestionError, DataQualityError, TradingLabError

EXIT_SSID_EXPIRED = 5


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-id", type=int, required=True)
    parser.add_argument("--asset", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--timeframe", type=int, default=60)
    parser.add_argument("--timeframe-label", default="M1")
    parser.add_argument("--points", type=int, default=3000)
    parser.add_argument("--broker", default="Polarium")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument(
        "--origin", default="BROKER_OTC", choices=("BROKER_OTC", "MARKET_PROXY")
    )
    parser.add_argument(
        "--dataset-db", type=Path, default=Path("data/datasets/datasets.db")
    )
    parser.add_argument("--interval-minutes", type=float, default=60.0)
    parser.add_argument("--max-hours", type=float, default=12.0)
    args = parser.parse_args()

    config = CollectorConfig(
        active_id=args.active_id,
        timeframe_seconds=args.timeframe,
        endpoint=args.endpoint,
        broker=args.broker,
        asset=args.asset,
        timeframe_label=args.timeframe_label,
        origin=DataOrigin(args.origin),
    )

    print(f"coleta periódica de {args.asset} ({args.timeframe_label})")
    print(f"intervalo: {args.interval_minutes}min | orçamento: {args.max_hours}h")
    print(f"início:    {datetime.now(UTC).isoformat(timespec='seconds')}")
    print()

    args.dataset_db.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + args.max_hours * 3600.0
    ciclo = 0
    total_versoes = 0

    while time.monotonic() < deadline:
        ciclo += 1
        marca = datetime.now(UTC).strftime("%H:%M:%S")
        try:
            versao = _coletar_uma_vez(args, config)
        except DataIngestionError as error:
            mensagem = str(error)
            if "SSID" in mensagem or "autenticação" in mensagem:
                print(f"[{marca}] SSID expirado ou inválido: {mensagem}")
                print()
                print(
                    "Faça login novamente, pegue um SSID novo e reinicie o loop.\n"
                    "As versões já coletadas estão preservadas."
                )
                return EXIT_SSID_EXPIRED
            print(f"[{marca}] ciclo {ciclo}: falha de coleta: {mensagem}")
            versao = None
        except TradingLabError as error:
            print(f"[{marca}] ciclo {ciclo}: {type(error).__name__}: {error}")
            versao = None

        if versao is not None:
            total_versoes += 1
            print(
                f"[{marca}] ciclo {ciclo}: v{versao['version']} | "
                f"{versao['points']} pontos | "
                f"{versao['coverage_start']} -> {versao['coverage_end']} | "
                f"gaps {versao['gaps']} | rejeitados {versao['rejected']}"
            )

        restante = deadline - time.monotonic()
        if restante <= 0:
            break
        espera = min(args.interval_minutes * 60.0, restante)
        time.sleep(espera)

    print()
    print(f"loop encerrado: {total_versoes} versão(ões) gravada(s) em {ciclo} ciclo(s)")
    return 0


def _coletar_uma_vez(args, config: CollectorConfig) -> dict[str, object] | None:
    with CollectorSession(config) as session:
        points = session.collect_backwards(target_points=args.points)

    if not points:
        raise DataQualityError("nenhuma vela retornada")

    store = DatasetStore(args.dataset_db)
    try:
        resultado = ingest_raw_batch(
            store,
            args.dataset_id,
            points,
            expected_interval_seconds=float(args.timeframe),
        )
    finally:
        store.close()

    versao = resultado.dataset_version
    return {
        "version": versao.version,
        "points": versao.point_count,
        "coverage_start": versao.coverage_start.strftime("%m-%d %H:%M"),
        "coverage_end": versao.coverage_end.strftime("%m-%d %H:%M"),
        "gaps": len(resultado.report.gaps),
        "rejected": resultado.report.total_rejected,
    }


if __name__ == "__main__":
    raise SystemExit(main())
