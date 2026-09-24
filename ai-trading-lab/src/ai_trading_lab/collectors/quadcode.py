"""Coletor de velas para plataformas Quadcode (família de protocolo IQ Option).

Identificação da plataforma e do protocolo está documentada em
`docs/RESEARCH-broker-automation-landscape.md`.

ESCOPO — SOMENTE LEITURA
Este módulo lê histórico de velas e nada mais. Não existe aqui nenhum método
para abrir posição, enviar ordem, alterar saldo ou mudar configuração de conta.
Isso é deliberado: automação de execução está fora de escopo até existir
estratégia validada.

CREDENCIAL
O SSID é a credencial de sessão da plataforma. Regras aplicadas:
- vem exclusivamente de variável de ambiente, nunca de argumento em linha de
  comando (que vazaria no histórico do shell) e nunca de arquivo versionado;
- nunca é gravado em log — `logging.sanitize` mascara `ssid` e `session_id`;
- não é persistido em lugar algum.

Para obter o SSID: faça login normalmente no navegador e leia o valor na
mensagem `authenticate` do WebSocket, ou no cookie de sessão. Fazer logout
invalida o SSID, então trate-o como senha temporária.
"""

from __future__ import annotations

import json
import os
import ssl
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Iterator

from ..data_models import DataOrigin, RawPricePoint
from ..errors import DataIngestionError

DEFAULT_ENDPOINT = "wss://ws.trade.polariumbroker.com/echo/websocket"
SSID_ENVIRONMENT_VARIABLE = "BROKER_SSID"
PROTOCOL_VERSION = 3

# A plataforma limita a quantidade de velas por requisição. O valor exato varia
# por tenant; 1000 é um teto conservador que costuma ser aceito, e a paginação
# cobre o resto.
MAX_CANDLES_PER_REQUEST = 1000


@dataclass(frozen=True, slots=True)
class CollectorConfig:
    """Configuração de uma coleta. Não contém credencial."""

    active_id: int
    timeframe_seconds: int
    endpoint: str = DEFAULT_ENDPOINT
    broker: str = "Polarium"
    asset: str = "UNKNOWN"
    timeframe_label: str = "M1"
    origin: DataOrigin = DataOrigin.BROKER_OTC
    receive_timeout: float = 15.0
    request_pause: float = 0.35

    def __post_init__(self) -> None:
        if self.timeframe_seconds < 1:
            raise ValueError("timeframe_seconds deve ser >= 1")
        if self.active_id < 1:
            raise ValueError("active_id deve ser >= 1")


@dataclass(slots=True)
class CollectorSession:
    """Sessão de leitura contra o WebSocket da plataforma."""

    config: CollectorConfig
    _socket: Any = field(default=None, repr=False)
    _request_counter: int = field(default=0, repr=False)
    _authenticated: bool = field(default=False, repr=False)
    raw_messages: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __enter__(self) -> CollectorSession:
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def connect(self) -> None:
        """Abre o socket e autentica com o SSID do ambiente."""
        import websocket

        ssid = read_ssid_from_environment()
        self._socket = websocket.create_connection(
            self.config.endpoint,
            timeout=self.config.receive_timeout,
            sslopt={"cert_reqs": ssl.CERT_REQUIRED},
            origin=_origin_header(self.config.endpoint),
            suppress_origin=False,
        )
        self._send(
            "authenticate",
            {
                "ssid": ssid,
                "protocol": PROTOCOL_VERSION,
                "session_id": "",
                "client_session_id": "",
            },
        )
        self._await_authentication()

    def _await_authentication(self) -> None:
        """Espera a confirmação de autenticação antes de liberar requisições.

        Requisição enviada antes da confirmação é descartada silenciosamente pela
        plataforma, o que fazia o primeiro lote sempre voltar vazio.
        """
        deadline = time.monotonic() + self.config.receive_timeout
        while time.monotonic() < deadline:
            message = self._receive()
            if message is None:
                continue
            if str(message.get("name", "")) != "authenticated":
                continue
            if message.get("msg") is False:
                raise DataIngestionError(
                    "autenticação recusada: SSID inválido ou expirado. "
                    "Faça login novamente e use um SSID novo."
                )
            self._authenticated = True
            return
        raise DataIngestionError(
            "plataforma não confirmou a autenticação dentro do tempo limite"
        )

    def close(self) -> None:
        """Fecha o socket, se aberto."""
        if self._socket is not None:
            try:
                self._socket.close()
            finally:
                self._socket = None
                self._authenticated = False

    def _next_request_id(self) -> str:
        self._request_counter += 1
        return f"lab_{int(time.time())}_{self._request_counter}"

    def _send(self, name: str, message: dict[str, Any]) -> str:
        if self._socket is None:
            raise DataIngestionError("socket não conectado")
        request_id = self._next_request_id()
        payload = {
            "name": name,
            "request_id": request_id,
            "local_time": int(time.time() * 1000) % 100000,
            "msg": message,
        }
        self._socket.send(json.dumps(payload))
        return request_id

    def _receive(self) -> dict[str, Any] | None:
        if self._socket is None:
            raise DataIngestionError("socket não conectado")
        try:
            frame = self._socket.recv()
        except Exception as error:  # timeout ou socket fechado
            raise DataIngestionError(f"falha ao receber frame: {error}") from error
        if not frame:
            return None
        if isinstance(frame, bytes):
            try:
                frame = frame.decode("utf-8")
            except UnicodeDecodeError:
                return None
        try:
            return json.loads(frame)
        except json.JSONDecodeError:
            return None

    def request_candles(
        self,
        *,
        to_timestamp: int,
        count: int,
        record_raw: bool = False,
    ) -> list[dict[str, Any]]:
        """Pede um lote de velas terminando em `to_timestamp` (epoch segundos).

        Tenta as variantes de nome conhecidas na família do protocolo, porque
        tenants diferentes expõem versões diferentes da mesma operação.
        """
        if count < 1:
            raise ValueError("count deve ser >= 1")
        capped = min(count, MAX_CANDLES_PER_REQUEST)

        request_id = self._send(
            "sendMessage",
            {
                "name": "get-candles",
                "version": "2.0",
                "body": {
                    "active_id": self.config.active_id,
                    "size": self.config.timeframe_seconds,
                    "to": to_timestamp,
                    "count": capped,
                },
            },
        )
        return self._await_candles(request_id, record_raw=record_raw)

    def _await_candles(
        self, request_id: str, *, record_raw: bool
    ) -> list[dict[str, Any]]:
        deadline = time.monotonic() + self.config.receive_timeout
        while time.monotonic() < deadline:
            message = self._receive()
            if message is None:
                continue
            if record_raw:
                self.raw_messages.append(message)

            name = str(message.get("name", ""))
            if name in {"candles", "first-candles"} or "candle" in name:
                extracted = extract_candles(message)
                if extracted:
                    return extracted
            if message.get("request_id") == request_id and name in {
                "result",
                "error",
            }:
                raise DataIngestionError(f"plataforma respondeu '{name}': {message}")
        return []

    def collect_backwards(
        self,
        *,
        target_points: int,
        end_timestamp: int | None = None,
        on_progress: Callable[[int], None] | None = None,
    ) -> tuple[RawPricePoint, ...]:
        """Pagina para trás no tempo até juntar `target_points` velas.

        Pagina porque a plataforma limita a quantidade por requisição.
        """
        cursor = end_timestamp or int(datetime.now(UTC).timestamp())
        collected: dict[int, RawPricePoint] = {}

        while len(collected) < target_points:
            batch = self.request_candles(
                to_timestamp=cursor,
                count=min(MAX_CANDLES_PER_REQUEST, target_points - len(collected)),
            )
            if not batch:
                break

            oldest = cursor
            for candle in batch:
                point = candle_to_point(candle, self.config)
                if point is None:
                    continue
                epoch = int(point.timestamp.timestamp())
                collected.setdefault(epoch, point)
                oldest = min(oldest, epoch)

            if on_progress is not None:
                on_progress(len(collected))

            if oldest >= cursor:
                break  # não avançou: evita laço infinito
            cursor = oldest - self.config.timeframe_seconds
            time.sleep(self.config.request_pause)

        return tuple(
            point for _, point in sorted(collected.items(), key=lambda item: item[0])
        )


def read_ssid_from_environment() -> str:
    """Lê o SSID do ambiente. Falha explicitamente se ausente."""
    ssid = os.environ.get(SSID_ENVIRONMENT_VARIABLE, "").strip()
    if not ssid:
        raise DataIngestionError(
            f"variável de ambiente {SSID_ENVIRONMENT_VARIABLE} não definida. "
            "Defina-a apenas na sessão atual do shell; não grave em arquivo."
        )
    return ssid


def _origin_header(endpoint: str) -> str:
    host = endpoint.split("//", 1)[-1].split("/", 1)[0]
    return f"https://{host.replace('ws.', '', 1)}"


def extract_candles(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Extrai a lista de velas de um envelope, tolerando variações de formato."""
    payload = message.get("msg", message)
    if isinstance(payload, dict):
        for key in ("candles", "data", "result"):
            nested = payload.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
        if _looks_like_candle(payload):
            return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


_TIME_KEYS = ("from", "at", "time", "timestamp", "t")
_CLOSE_KEYS = ("close", "c")
_OPEN_KEYS = ("open", "o")
_HIGH_KEYS = ("max", "high", "h")
_LOW_KEYS = ("min", "low", "l")


def _looks_like_candle(candidate: dict[str, Any]) -> bool:
    has_time = any(key in candidate for key in _TIME_KEYS)
    has_close = any(key in candidate for key in _CLOSE_KEYS)
    return has_time and has_close


def _pick(candidate: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in candidate and candidate[key] is not None:
            return candidate[key]
    return None


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")) or number <= 0:
        return None
    return number


def candle_to_point(
    candle: dict[str, Any], config: CollectorConfig
) -> RawPricePoint | None:
    """Converte uma vela do protocolo em `RawPricePoint`.

    Devolve `None` quando a vela não tem tempo ou fechamento utilizáveis —
    nunca inventa valor para preencher lacuna.
    """
    raw_time = _pick(candle, _TIME_KEYS)
    close = _to_float(_pick(candle, _CLOSE_KEYS))
    if raw_time is None or close is None:
        return None

    timestamp = _normalize_epoch(raw_time)
    if timestamp is None:
        return None

    return RawPricePoint(
        broker=config.broker,
        asset=config.asset,
        timeframe=config.timeframe_label,
        timestamp=timestamp,
        price=close,
        source="quadcode_ws",
        origin=config.origin,
        open=_to_float(_pick(candle, _OPEN_KEYS)),
        high=_to_float(_pick(candle, _HIGH_KEYS)),
        low=_to_float(_pick(candle, _LOW_KEYS)),
    )


def _normalize_epoch(value: Any) -> datetime | None:
    """Normaliza epoch em segundos, milissegundos ou microssegundos para UTC."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None

    # Heurística por magnitude. A plataforma usa segundos em `from`/`to` e
    # nanossegundos em `at`, então todas as escalas precisam ser tratadas.
    if number > 1e17:
        number /= 1_000_000_000  # nanossegundos
    elif number > 1e14:
        number /= 1_000_000  # microssegundos
    elif number > 1e11:
        number /= 1000  # milissegundos

    try:
        return datetime.fromtimestamp(number, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def iterate_candle_variants() -> Iterator[tuple[str, dict[str, Any]]]:
    """Variantes de requisição de velas conhecidas na família do protocolo.

    Usado pelo probe de descoberta para achar qual delas este tenant aceita.
    """
    yield "sendMessage/get-candles-2.0", {
        "name": "get-candles",
        "version": "2.0",
        "body": {},
    }
    yield "sendMessage/get-first-candles-1.0", {
        "name": "get-first-candles",
        "version": "1.0",
        "body": {},
    }
    yield "get-candles-legacy", {}
