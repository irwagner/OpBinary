"""Mostra por que uma estratégia específica foi reprovada.

Reconstrói a cadeia de decisão a partir da auditoria, como exige a seção 35 da
MASTER_SPEC. Leitura apenas.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def _events(connection: sqlite3.Connection, event_type: str) -> list[dict]:
    return [
        json.loads(row["payload"])
        for row in connection.execute(
            "SELECT payload FROM audit_events WHERE event_type = ?", (event_type,)
        )
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("strategy_id")
    parser.add_argument("--state-db", type=Path, default=Path("logs/state.db"))
    args = parser.parse_args()

    connection = sqlite3.connect(args.state_db)
    connection.row_factory = sqlite3.Row
    try:
        backtests = _events(connection, "backtest_executed")
        statistics = _events(connection, "statistics_computed")
        decisions = _events(connection, "validation_decided")
        risks = _events(connection, "risk_assessed")
    finally:
        connection.close()

    target = args.strategy_id
    print(f"CADEIA DE DECISÃO — {target}")
    print()

    for event in backtests:
        if event.get("strategy_id") == target:
            rate = event["wins"] / event["trades"] if event["trades"] else 0.0
            print("Backtest")
            print(f"  operações:   {event['trades']}")
            print(f"  acerto:      {rate:.2%}")
            print(f"  expectancy:  {event['expectancy']:+.4f}")
            print(f"  drawdown:    {event['worst_drawdown']:.1%}")
            print(f"  seq. perdas: {event['max_loss_streak']}")

    for event in statistics:
        if event.get("strategy_id") == target:
            print("Estatística")
            print(f"  folds positivos: {event['fold_pass_ratio']:.0%}")
            print(f"  degradação OOS:  {event['degradation']:+.4f}")
            print(f"  prob. de ruína:  {event['ruin_probability']:.2%}")

    for event in risks:
        if event.get("strategy_id") == target:
            print("Risco")
            print(f"  veredicto:   {event['verdict']}")
            print(f"  drawdown:    {event['worst_drawdown']:.1%}")
            print(f"  ruína:       {event['worst_risk_of_ruin']:.2%}")

    for event in decisions:
        if event.get("strategy_id") == target:
            print("Decisão")
            print(f"  {event['previous_state']} -> {event['new_state']}")
            print(f"  reprovou em: {event['failed_items']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
