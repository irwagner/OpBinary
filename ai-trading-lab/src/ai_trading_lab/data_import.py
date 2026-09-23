"""Importação de séries a partir de arquivo (ADR-007).

Sem API oficial disponível, a ingestão parte de um arquivo exportado ou
capturado pelo usuário. O importador não afrouxa nenhuma validação: quem valida
continua sendo `data_validation.validate_and_normalize`.

Nada aqui inventa dado. Linha malformada é rejeitada e registrada, nunca
corrigida por suposição. A origem do dado é sempre declarada pelo chamador —
jamais inferida do conteúdo do arquivo.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Mapping, Protocol, Sequence

from .data_models import DataOrigin, RawPricePoint
from .errors import DataIngestionError

_TIMESTAMP_ALIASES = ("timestamp", "time", "date", "datetime", "gmt time", "data")
_CLOSE_ALIASES = ("price", "close", "fechamento", "last")
_OPEN_ALIASES = ("open", "abertura")
_HIGH_ALIASES = ("high", "maxima", "máxima", "max")
_LOW_ALIASES = ("low", "minima", "mínima", "min")


def _pick(row: Mapping[str, object], aliases: Sequence[str]) -> object:
    """Encontra o primeiro alias presente, ignorando caixa e espaços."""
    normalized = {
        str(key).strip().lower(): value for key, value in row.items() if key is not None
    }
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    return None


class MarketDataSource(Protocol):
    """Porta de obtenção de séries brutas.

    Permite acoplar um coletor ao vivo no futuro sem alterar o pipeline de
    validação, versionamento e persistência.
    """

    def fetch(self) -> tuple[RawPricePoint, ...]: ...


@dataclass(frozen=True, slots=True)
class ImportRejection:
    """Linha recusada na leitura do arquivo, preservada para auditoria."""

    line_number: int
    reason: str
    raw_line: str


@dataclass(frozen=True, slots=True)
class ImportResult:
    """Resultado da leitura: pontos aceitos e linhas recusadas."""

    points: tuple[RawPricePoint, ...]
    rejections: tuple[ImportRejection, ...]
    total_lines: int

    @property
    def accepted(self) -> int:
        return len(self.points)


@dataclass(frozen=True, slots=True)
class FileMarketDataSource:
    """Fonte baseada em arquivo CSV ou JSON, com origem declarada."""

    path: Path
    broker: str
    asset: str
    timeframe: str
    origin: DataOrigin
    source_label: str = "manual_export"

    def fetch(self) -> tuple[RawPricePoint, ...]:
        """Devolve apenas os pontos aceitos; use `read` para ver as recusas."""
        return self.read().points

    def read(self) -> ImportResult:
        """Lê o arquivo e separa pontos válidos de linhas recusadas."""
        if not self.path.is_file():
            raise DataIngestionError(f"arquivo não encontrado: {self.path}")
        suffix = self.path.suffix.lower()
        if suffix == ".csv":
            return self._read_csv()
        if suffix == ".json":
            return self._read_json()
        raise DataIngestionError(
            f"extensão não suportada: {suffix or '(sem extensão)'}; use .csv ou .json"
        )

    def _read_csv(self) -> ImportResult:
        with self.path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise DataIngestionError("CSV sem cabeçalho")
            headers = {
                str(name).strip().lower() for name in reader.fieldnames if name is not None
            }
            if not headers & set(_TIMESTAMP_ALIASES):
                raise DataIngestionError(
                    f"CSV sem coluna de tempo; aceitos: {list(_TIMESTAMP_ALIASES)}"
                )
            if not headers & set(_CLOSE_ALIASES):
                raise DataIngestionError(
                    f"CSV sem coluna de preço de fechamento; aceitos: {list(_CLOSE_ALIASES)}"
                )
            return self._build(list(reader), offset=2)

    def _read_json(self) -> ImportResult:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise DataIngestionError("JSON inválido") from error
        if not isinstance(payload, list):
            raise DataIngestionError("JSON deve conter uma lista de registros")
        return self._build(payload, offset=1)

    def _build(
        self, rows: Sequence[object], *, offset: int
    ) -> ImportResult:
        points: list[RawPricePoint] = []
        rejections: list[ImportRejection] = []

        for index, row in enumerate(rows, start=offset):
            if not isinstance(row, Mapping):
                rejections.append(
                    ImportRejection(index, "registro não é um objeto", repr(row))
                )
                continue
            try:
                points.append(self._to_point(row))
            except (DataIngestionError, ValueError) as error:
                rejections.append(ImportRejection(index, str(error), repr(dict(row))))

        return ImportResult(
            points=tuple(points),
            rejections=tuple(rejections),
            total_lines=len(rows),
        )

    def _to_point(self, row: Mapping[str, object]) -> RawPricePoint:
        timestamp = _parse_timestamp(_pick(row, _TIMESTAMP_ALIASES))
        price = _parse_price(_pick(row, _CLOSE_ALIASES))
        return RawPricePoint(
            broker=self.broker,
            asset=self.asset,
            timeframe=self.timeframe,
            timestamp=timestamp,
            price=price,
            source=self.source_label,
            origin=self.origin,
            open=_parse_optional_price(_pick(row, _OPEN_ALIASES)),
            high=_parse_optional_price(_pick(row, _HIGH_ALIASES)),
            low=_parse_optional_price(_pick(row, _LOW_ALIASES)),
        )


def _parse_timestamp(value: object) -> datetime:
    """Exige timestamp explícito. Aceita ISO-8601 ou epoch em segundos."""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise DataIngestionError("timestamp ausente")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(float(value), tz=UTC)

    text = str(value).strip()
    if text.isdigit():
        return datetime.fromtimestamp(float(text), tz=UTC)

    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise DataIngestionError(f"timestamp inválido: {text!r}") from error

    if parsed.tzinfo is None:
        # Timezone é obrigatório e nunca assumido: um horário sem fuso não pode
        # ser posicionado no tempo com segurança.
        raise DataIngestionError(
            f"timestamp sem timezone: {text!r}; inclua o offset (ex: -03:00 ou Z)"
        )
    return parsed


def _parse_price(value: object) -> float:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise DataIngestionError("price ausente")
    if isinstance(value, bool):
        raise DataIngestionError("price booleano é inválido")
    try:
        price = float(str(value).strip().replace(",", "."))
    except ValueError as error:
        raise DataIngestionError(f"price inválido: {value!r}") from error
    if price != price or price in (float("inf"), float("-inf")) or price <= 0:
        raise DataIngestionError(f"price deve ser finito e positivo: {value!r}")
    return price


def _parse_optional_price(value: object) -> float | None:
    """OHLC é opcional: ausência é aceita, valor inválido é recusado."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return _parse_price(value)


def collect_from_sources(sources: Iterable[MarketDataSource]) -> tuple[RawPricePoint, ...]:
    """Concatena pontos de várias fontes preservando a ordem de leitura.

    Não mistura séries: a validação posterior rejeita pontos divergentes em
    broker/asset/timeframe/origin, então cada fonte deve alimentar seu próprio
    dataset.
    """
    collected: list[RawPricePoint] = []
    for source in sources:
        collected.extend(source.fetch())
    return tuple(collected)
