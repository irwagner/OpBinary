"""Fixtures determinísticas para testes.

ATENÇÃO: as séries construídas aqui são artefatos sintéticos de teste, usados
exclusivamente para verificar a mecânica do motor (contabilidade, ordenação,
barreiras temporais). Não representam dados de mercado, não vêm de corretora
alguma e nunca devem ser usadas para avaliar mérito de estratégia.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from random import Random

from ai_trading_lab.data_models import ValidatedPricePoint

BROKER = "TestBroker"
ASSET = "TESTPAIR"
TIMEFRAME = "M1"


def series_from_prices(
    prices: tuple[float, ...],
    *,
    start: datetime | None = None,
    step_seconds: int = 60,
) -> tuple[ValidatedPricePoint, ...]:
    """Constrói uma série validada a partir de uma lista explícita de preços."""
    origin = start or datetime(2026, 1, 1, tzinfo=UTC)
    return tuple(
        ValidatedPricePoint(
            broker=BROKER,
            asset=ASSET,
            timeframe=TIMEFRAME,
            timestamp=origin + timedelta(seconds=step_seconds * index),
            price=price,
            source="test_fixture",
        )
        for index, price in enumerate(prices)
    )


def monotonic_series(count: int, *, step: float = 0.01) -> tuple[ValidatedPricePoint, ...]:
    """Série estritamente crescente — usada para validar mecânica, não mérito."""
    return series_from_prices(tuple(1.0 + step * index for index in range(count)))


def mixed_walk_series(count: int, *, seed: int = 7) -> tuple[ValidatedPricePoint, ...]:
    """Caminhada determinística com passos suficientes para disparar sinais.

    Produz vitórias e derrotas misturadas, permitindo exercitar contabilidade,
    sequências de perdas e drawdown. É sintética e semeada — reprodutível, mas
    sem qualquer relação com preços reais de mercado.
    """
    generator = Random(seed)
    price = 1.0
    prices = [price]
    for _ in range(max(count - 1, 0)):
        step = generator.choice((-0.004, -0.002, 0.002, 0.004))
        price = round(price * (1.0 + step), 8)
        prices.append(price)
    return series_from_prices(tuple(prices))


def past_start(minutes_ago: int) -> datetime:
    """Instante no passado, para não colidir com a barreira de dados futuros."""
    return datetime.now(UTC) - timedelta(minutes=minutes_ago)
