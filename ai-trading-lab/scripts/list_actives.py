"""Lista ativos, active_id e payout real da plataforma (somente leitura).

O payout nunca deve ser chutado nem hardcoded: ele define o limiar de acerto
necessário para uma estratégia ser viável. Este script lê o valor da própria
plataforma.

No protocolo, `option.profit.commission` é a parte retida pela corretora, então:

    payout = (100 - commission) / 100

USO
    $env:PYTHONPATH = "src"
    $env:BROKER_SSID = "<ssid>"
    python scripts/list_actives.py --filter EUR
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from typing import Any, Iterator

from ai_trading_lab.collectors.quadcode import (
    DEFAULT_ENDPOINT,
    CollectorConfig,
    CollectorSession,
)
from ai_trading_lab.errors import TradingLabError


@dataclass(frozen=True, slots=True)
class ActiveInfo:
    """Instrumento disponível, com payout derivado da comissão."""

    active_id: int
    name: str
    group: str
    commission: float | None
    enabled: bool
    expiration_times: tuple[int, ...]

    @property
    def payout(self) -> float | None:
        """Retorno líquido de uma operação vencedora, entre 0 e 1."""
        if self.commission is None:
            return None
        return (100.0 - self.commission) / 100.0

    @property
    def breakeven_win_rate(self) -> float | None:
        """Acerto mínimo para empatar, dado o payout."""
        payout = self.payout
        if payout is None or payout <= 0:
            return None
        return 1.0 / (1.0 + payout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--filter", default=None, help="filtra pelo nome do ativo")
    parser.add_argument("--only-enabled", action="store_true")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    config = CollectorConfig(active_id=1, timeframe_seconds=60, endpoint=args.endpoint)

    try:
        payload = _fetch_initialization_data(config, args.timeout)
    except TradingLabError as error:
        print(f"ERRO: {type(error).__name__}: {error}")
        return 1

    actives = sorted(
        _parse_actives(payload), key=lambda item: (item.group, item.name)
    )
    if args.filter:
        termo = args.filter.upper()
        actives = [item for item in actives if termo in item.name.upper()]
    if args.only_enabled:
        actives = [item for item in actives if item.enabled]

    if not actives:
        print("nenhum ativo encontrado com esse filtro")
        return 1

    header = (
        f"{'active_id':>9}  {'ativo':<22} {'grupo':<10} "
        f"{'payout':>7} {'empate':>8} {'exp(s)':>10}  ativo?"
    )
    print(header)
    print("-" * len(header))
    for item in actives:
        payout = f"{item.payout:.0%}" if item.payout is not None else "?"
        breakeven = (
            f"{item.breakeven_win_rate:.2%}"
            if item.breakeven_win_rate is not None
            else "?"
        )
        expirations = ",".join(str(value) for value in item.expiration_times[:3]) or "-"
        print(
            f"{item.active_id:>9}  {item.name:<22} {item.group:<10} "
            f"{payout:>7} {breakeven:>8} {expirations:>10}  "
            f"{'sim' if item.enabled else 'nao'}"
        )

    print()
    print(f"{len(actives)} ativo(s) listado(s)")
    print("empate = taxa de acerto mínima para não perder dinheiro nesse payout")
    return 0


def _fetch_initialization_data(
    config: CollectorConfig, timeout: float
) -> dict[str, Any]:
    with CollectorSession(config) as session:
        session._send(  # noqa: SLF001 - leitura de metadados
            "sendMessage",
            {"name": "get-initialization-data", "version": "4.0", "body": {}},
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = session._receive()  # noqa: SLF001
            if message is None:
                continue
            if str(message.get("name", "")) == "initialization-data":
                payload = message.get("msg")
                if isinstance(payload, dict):
                    return payload
        raise TradingLabError("plataforma não retornou initialization-data")


def _parse_actives(payload: dict[str, Any]) -> Iterator[ActiveInfo]:
    """Percorre os grupos de instrumentos e extrai id, nome, comissão e expiração."""
    for group_name, group in payload.items():
        if not isinstance(group, dict):
            continue
        actives = group.get("actives")
        if not isinstance(actives, dict):
            continue
        for raw_id, active in actives.items():
            if not isinstance(active, dict):
                continue
            try:
                active_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            yield ActiveInfo(
                active_id=active_id,
                name=str(active.get("ticker") or active.get("name") or f"id{active_id}"),
                group=str(group_name),
                commission=_commission_of(active),
                enabled=bool(active.get("enabled", False)),
                expiration_times=_expirations_of(active),
            )


def _commission_of(active: dict[str, Any]) -> float | None:
    option = active.get("option")
    if not isinstance(option, dict):
        return None
    profit = option.get("profit")
    if not isinstance(profit, dict):
        return None
    commission = profit.get("commission")
    if isinstance(commission, bool) or not isinstance(commission, (int, float)):
        return None
    return float(commission)


def _expirations_of(active: dict[str, Any]) -> tuple[int, ...]:
    option = active.get("option")
    if not isinstance(option, dict):
        return ()
    times = option.get("expiration_times")
    if not isinstance(times, list):
        return ()
    return tuple(value for value in times if isinstance(value, int))


if __name__ == "__main__":
    raise SystemExit(main())
