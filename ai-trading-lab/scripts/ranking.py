"""Ranqueia os backtests registrados na auditoria, do melhor para o pior.

Leitura apenas: não altera estado, não decide nada. Serve para inspecionar o
que a campanha de busca encontrou, incluindo os resultados negativos.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

MIN_TRADES_DEFAULT = 30


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-db", type=Path, default=Path("logs/state.db"))
    parser.add_argument("--min-trades", type=int, default=MIN_TRADES_DEFAULT)
    parser.add_argument("--payout", type=float, default=0.87)
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    connection = sqlite3.connect(args.state_db)
    connection.row_factory = sqlite3.Row
    try:
        rows = [
            json.loads(row["payload"])
            for row in connection.execute(
                "SELECT payload FROM audit_events WHERE event_type = 'backtest_executed'"
            )
        ]
    finally:
        connection.close()

    eligible = [row for row in rows if row.get("trades", 0) >= args.min_trades]
    eligible.sort(key=lambda row: row["expectancy"], reverse=True)

    breakeven = 1.0 / (1.0 + args.payout)
    print(f"Backtests registrados:        {len(rows)}")
    print(f"Com pelo menos {args.min_trades} operações: {len(eligible)}")
    print(f"Acerto necessário p/ empate:  {breakeven:.2%} (payout {args.payout})")
    print()

    if not eligible:
        print("Nenhum backtest com amostra suficiente.")
        return 0

    header = (
        f"{'estratégia':<14} {'ops':>5} {'acerto':>8} "
        f"{'expectancy':>11} {'drawdown':>9}"
    )
    print(header)
    print("-" * len(header))
    for row in eligible[: args.top]:
        rate = row["wins"] / row["trades"]
        print(
            f"{row['strategy_id']:<14} {row['trades']:>5} {rate:>7.2%} "
            f"{row['expectancy']:>+11.4f} {row['worst_drawdown']:>8.1%}"
        )

    positives = [row for row in eligible if row["expectancy"] > 0]
    print()
    print(f"Com expectancy positivo: {len(positives)} de {len(eligible)}")
    if not positives:
        print("Nenhuma regra superou o payout. Em dado sem edge, esse é o esperado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
