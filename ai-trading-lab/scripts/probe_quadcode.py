"""Probe de descoberta do formato de velas (somente leitura).

Conecta, autentica com o SSID do ambiente, pede velas e imprime o que voltou.
Serve para confirmar o formato exato do payload nesta plataforma antes de
coletar volume.

NÃO envia ordem, não altera saldo, não muda configuração. Só pede histórico.

USO
    # define o SSID apenas na sessão atual do shell (PowerShell)
    $env:BROKER_SSID = "<seu_ssid>"
    $env:PYTHONPATH = "src"
    python scripts/probe_quadcode.py --active-id 76 --timeframe 60

Depois de usar, faça logout na plataforma para invalidar o SSID, e limpe a
variável:
    Remove-Item Env:BROKER_SSID
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

from ai_trading_lab.collectors.quadcode import (
    DEFAULT_ENDPOINT,
    CollectorConfig,
    CollectorSession,
    candle_to_point,
)
from ai_trading_lab.errors import TradingLabError
from ai_trading_lab.logging import sanitize


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--active-id",
        type=int,
        required=True,
        help="id numérico do ativo na plataforma",
    )
    parser.add_argument(
        "--timeframe",
        type=int,
        default=60,
        help="tamanho da vela em segundos (60 = M1)",
    )
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--asset", default="UNKNOWN")
    parser.add_argument(
        "--show-raw",
        action="store_true",
        help="imprime as mensagens brutas recebidas (já sanitizadas)",
    )
    parser.add_argument(
        "--listen",
        type=float,
        default=0.0,
        help="apenas escuta por N segundos e reporta o que a plataforma envia",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="testa variantes de requisição e reporta quais este tenant aceita",
    )
    args = parser.parse_args()

    parser_discover = args.discover if hasattr(args, "discover") else False
    if args.listen > 0:
        return _listen_mode(args)
    if parser_discover:
        return _discover_mode(args)

    config = CollectorConfig(
        active_id=args.active_id,
        timeframe_seconds=args.timeframe,
        endpoint=args.endpoint,
        asset=args.asset,
    )

    print(f"endpoint: {config.endpoint}")
    print(f"active_id: {config.active_id} | timeframe: {config.timeframe_seconds}s")
    print()

    try:
        with CollectorSession(config) as session:
            candles = session.request_candles(
                to_timestamp=int(datetime.now(UTC).timestamp()),
                count=args.count,
                record_raw=True,
            )

            if args.show_raw:
                print("--- mensagens brutas (sanitizadas) ---")
                for message in session.raw_messages[:20]:
                    print(json.dumps(sanitize(message), ensure_ascii=False)[:600])
                print()

            if not candles:
                print("Nenhuma vela retornada.")
                print()
                print("Mensagens recebidas, por nome:")
                names: dict[str, int] = {}
                for message in session.raw_messages:
                    key = str(message.get("name", "(sem name)"))
                    names[key] = names.get(key, 0) + 1
                for name, total in sorted(names.items()):
                    print(f"  {name}: {total}")
                print()
                print(
                    "Se apareceu 'authenticate' com falha, o SSID expirou — "
                    "faça login de novo e pegue um novo."
                )
                return 1

            print(f"--- {len(candles)} vela(s) recebida(s) ---")
            print("primeira vela crua (sanitizada):")
            print(json.dumps(sanitize(candles[0]), ensure_ascii=False, indent=2))
            print()
            print("chaves presentes:", sorted(candles[0].keys()))
            print()

            print("--- conversão para o modelo do laboratório ---")
            converted = 0
            for candle in candles[:5]:
                point = candle_to_point(candle, config)
                if point is None:
                    print("  (vela sem tempo ou fechamento utilizável, descartada)")
                    continue
                converted += 1
                print(
                    f"  {point.timestamp.isoformat()} close={point.price} "
                    f"open={point.open} high={point.high} low={point.low}"
                )
            print()
            print(f"convertidas com sucesso: {converted} de {min(5, len(candles))}")
            return 0
    except TradingLabError as error:
        print(f"ERRO: {type(error).__name__}: {error}")
        return 1


def _discover_mode(args) -> int:
    """Testa variantes conhecidas de requisição e reporta o que responde."""
    import time

    config = CollectorConfig(
        active_id=args.active_id,
        timeframe_seconds=args.timeframe,
        endpoint=args.endpoint,
        asset=args.asset,
    )
    agora = int(datetime.now(UTC).timestamp())

    tentativas: list[tuple[str, str, dict]] = [
        (
            "get-initialization-data 3.0",
            "sendMessage",
            {"name": "get-initialization-data", "version": "3.0", "body": {}},
        ),
        (
            "get-instruments 1.0 (binary)",
            "sendMessage",
            {"name": "get-instruments", "version": "1.0", "body": {"type": "binary"}},
        ),
        (
            "get-candles 2.0",
            "sendMessage",
            {
                "name": "get-candles",
                "version": "2.0",
                "body": {
                    "active_id": config.active_id,
                    "size": config.timeframe_seconds,
                    "to": agora,
                    "count": 10,
                },
            },
        ),
        (
            "get-first-candles 1.0",
            "sendMessage",
            {
                "name": "get-first-candles",
                "version": "1.0",
                "body": {
                    "active_id": config.active_id,
                    "size": config.timeframe_seconds,
                    "count": 10,
                },
            },
        ),
    ]

    try:
        with CollectorSession(config) as session:
            for rotulo, envelope, corpo in tentativas:
                print(f"=== {rotulo} ===")
                request_id = session._send(envelope, corpo)  # noqa: SLF001 - probe
                recebidas: list[dict] = []
                limite = time.monotonic() + 8.0
                while time.monotonic() < limite:
                    try:
                        message = session._receive()  # noqa: SLF001 - probe
                    except TradingLabError:
                        break
                    if message is None:
                        continue
                    nome = str(message.get("name", ""))
                    if nome in {"timeSync", "heartbeat"}:
                        continue
                    recebidas.append(message)
                    if message.get("request_id") == request_id or nome not in {
                        "front",
                        "authenticated",
                    }:
                        break

                if not recebidas:
                    print("  sem resposta")
                else:
                    for message in recebidas[:2]:
                        texto = json.dumps(sanitize(message), ensure_ascii=False)
                        print(f"  name={message.get('name')!r}")
                        print(f"  {texto[:900]}")
                print()
                time.sleep(0.4)
    except TradingLabError as error:
        print(f"ERRO: {type(error).__name__}: {error}")
        return 1
    return 0


def _listen_mode(args) -> int:
    """Escuta o socket sem pedir nada, para descobrir o que a plataforma envia."""
    import time

    config = CollectorConfig(
        active_id=args.active_id,
        timeframe_seconds=args.timeframe,
        endpoint=args.endpoint,
        asset=args.asset,
    )
    print(f"escutando {args.listen}s em {config.endpoint}")
    print()

    nomes: dict[str, int] = {}
    ativos: dict[int, str] = {}
    exemplos: dict[str, dict] = {}

    try:
        with CollectorSession(config) as session:
            fim = time.monotonic() + args.listen
            while time.monotonic() < fim:
                try:
                    message = session._receive()  # noqa: SLF001 - probe de descoberta
                except TradingLabError:
                    break
                if message is None:
                    continue
                nome = str(message.get("name", "(sem name)"))
                nomes[nome] = nomes.get(nome, 0) + 1
                exemplos.setdefault(nome, message)
                _coletar_ativos(message, ativos)
    except TradingLabError as error:
        print(f"ERRO: {type(error).__name__}: {error}")
        return 1

    print(f"--- {sum(nomes.values())} mensagem(ns), {len(nomes)} tipo(s) ---")
    for nome, total in sorted(nomes.items(), key=lambda item: -item[1]):
        print(f"  {total:>5}  {nome}")

    if ativos:
        print()
        print(f"--- {len(ativos)} active_id encontrado(s) ---")
        for active_id, rotulo in sorted(ativos.items())[:40]:
            print(f"  {active_id:>6}  {rotulo}")

    candidatos = [
        nome for nome in nomes if "candle" in nome.lower() or "quote" in nome.lower()
    ]
    if candidatos:
        print()
        print("--- mensagens relacionadas a vela/cotação ---")
        for nome in candidatos:
            print(f"{nome}:")
            print(json.dumps(sanitize(exemplos[nome]), ensure_ascii=False)[:700])
    return 0


def _coletar_ativos(message: dict, destino: dict[int, str]) -> None:
    """Procura pares (active_id, nome) em qualquer profundidade da mensagem."""

    def visitar(node: object) -> None:
        if isinstance(node, dict):
            identificador = node.get("active_id") or node.get("activeId") or node.get("id")
            rotulo = node.get("ticker") or node.get("name") or node.get("symbol")
            if isinstance(identificador, int) and isinstance(rotulo, str):
                destino.setdefault(identificador, rotulo)
            for valor in node.values():
                visitar(valor)
        elif isinstance(node, list):
            for item in node[:200]:
                visitar(item)

    visitar(message)


if __name__ == "__main__":
    raise SystemExit(main())
