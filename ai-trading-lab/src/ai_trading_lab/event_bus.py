"""Event bus interno, síncrono e thread-safe para a Fase 1."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock
from typing import TypeAlias

from .models import utc_now

EventHandler: TypeAlias = Callable[["Event"], None]


@dataclass(frozen=True, slots=True)
class Event:
    """Mensagem imutável publicada entre componentes internos."""

    name: str
    payload: Mapping[str, object]
    timestamp: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class PublishResult:
    """Resultado observável da entrega de um evento."""

    delivered: int
    failures: tuple[str, ...]


class EventBus:
    """Pub/sub em memória; não executa integrações externas."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._lock = RLock()

    def subscribe(self, event_name: str, handler: EventHandler) -> Callable[[], None]:
        """Assina um handler e devolve função para cancelar a assinatura."""
        with self._lock:
            self._handlers[event_name].append(handler)
        return lambda: self.unsubscribe(event_name, handler)

    def unsubscribe(self, event_name: str, handler: EventHandler) -> None:
        """Remove uma assinatura caso ainda esteja ativa."""
        with self._lock:
            handlers = self._handlers.get(event_name, [])
            if handler in handlers:
                handlers.remove(handler)

    def publish(self, event: Event) -> PublishResult:
        """Entrega o evento a todos os handlers sem deixar uma falha parar os demais."""
        with self._lock:
            handlers = tuple(self._handlers.get(event.name, ()))
        failures: list[str] = []
        delivered = 0
        for handler in handlers:
            try:
                handler(event)
                delivered += 1
            except Exception as error:  # isolamos listeners sem ocultar a falha
                failures.append(f"{handler.__name__}: {type(error).__name__}")
        return PublishResult(delivered=delivered, failures=tuple(failures))
