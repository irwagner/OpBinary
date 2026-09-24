"""Coleta velas da plataforma e ingere no Data Engine (somente leitura).

Pagina para trás no tempo, valida tudo pelo pipeline existente (timezone,
ordem, duplicatas, gaps) e grava uma nova versão imutável de dataset.

USO
    $env:PYTHONPATH = "src"
    $env:BROKER_SSID = "<ssid>"
    python scripts/collect_candles.py --active-id 1 --asset EURUSD `
        --timeframe 60 --points 5000 --dataset-id DATA-EURUSD-M1

Nenhuma ordem é enviada. O script só lê histórico.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ai_trading_lab.collectors.quadcode import (
    DEFAULT_ENDPOINT,
    CollectorConfig,
    CollectorSession,
)
from ai_trading_lab.data_ingestion import ingest_raw_batch
from ai_trading_lab.data_models import DataOrigin
from ai_trading_lab.data_persistence import DatasetStore
from ai_trading_lab.errors import TradingLabError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-id", type=int, required=True)
    parser.add_argument("--asset", required=True, help="rótulo do ativo, ex: EURUSD")
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--timeframe", type=int, default=60, help="segundos por vela")
    parser.add_argument("--timeframe-label", default=None, help="ex: M1")
    parser.add_argument("--points", type=int, default=5000)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--broker", default="Polarium")
    parser.add_argument(
        "--origin",
        default="BROKER_OTC",
        choices=("BROKER_OTC", "MARKET_PROXY"),
        help="origem declarada; OTC marca basis_risk alto",
    )
    parser.add_argument(
        "--dataset-db", type=Path, default=Path("data/datasets/datasets.db")
    )
    args = parser.parse_args()

    label = args.timeframe_label or _label_for(args.timeframe)
    config = CollectorConfig(
        active_id=args.active_id,
        timeframe_seconds=args.timeframe,
        endpoint=args.endpoint,
        broker=args.broker,
        asset=args.asset,
        timeframe_label=label,
        origin=DataOrigin(args.origin),
    )

    print(f"ativo {args.asset} (active_id {args.active_id}) | vela {label}")
    print(f"meta: {args.points} pontos")
    print()

    try:
        with CollectorSession(config) as session:
            points = session.collect_backwards(
                target_points=args.points,
                on_progress=lambda total: print(f"  coletadas {total}...", end="\r"),
            )
    except TradingLabError as error:
        print(f"ERRO na coleta: {type(error).__name__}: {error}")
        return 1

    print(f"\ncoletadas {len(points)} velas brutas")
    if not points:
        print("nada para ingerir")
        return 1

    args.dataset_db.parent.mkdir(parents=True, exist_ok=True)
    store = DatasetStore(args.dataset_db)
    try:
        result = ingest_raw_batch(
            store,
            args.dataset_id,
            points,
            expected_interval_seconds=float(args.timeframe),
        )
    except TradingLabError as error:
        print(f"ERRO na ingestão: {type(error).__name__}: {error}")
        return 1
    finally:
        store.close()

    version = result.dataset_version
    report = result.report
    print()
    print(f"dataset {version.dataset_id} v{version.version} [{version.stage.value}]")
    print(f"  origem:      {version.origin.value} (basis_risk_alto={version.basis_risk_high})")
    print(f"  pontos:      {version.point_count}")
    print(f"  cobertura:   {version.coverage_start.isoformat()}")
    print(f"               -> {version.coverage_end.isoformat()}")
    print(f"  hash:        {version.content_hash}")
    print()
    print(f"  aceitos:     {report.total_accepted}")
    print(f"  rejeitados:  {report.total_rejected}")
    print(f"  duplicatas:  {report.duplicates_removed}")
    print(f"  gaps:        {len(report.gaps)}")
    for gap in report.gaps[:5]:
        print(
            f"    {gap.previous_timestamp.isoformat()} -> "
            f"{gap.next_timestamp.isoformat()} ({gap.actual_gap_seconds:.0f}s)"
        )
    if len(report.gaps) > 5:
        print(f"    ... e {len(report.gaps) - 5} outro(s)")
    return 0


def _label_for(seconds: int) -> str:
    conhecidos = {
        60: "M1",
        300: "M5",
        900: "M15",
        1800: "M30",
        3600: "H1",
        14400: "H4",
        86400: "D1",
    }
    return conhecidos.get(seconds, f"S{seconds}")


if __name__ == "__main__":
    raise SystemExit(main())
