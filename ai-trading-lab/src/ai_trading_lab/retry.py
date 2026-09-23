"""Política de tentativas limitada, explícita e testável."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import sleep
from typing import ParamSpec, TypeVar

from .errors import RetryExhaustedError

P = ParamSpec("P")
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Configuração de retry com backoff linear e máximo finito."""

    max_attempts: int = 3
    delay_seconds: float = 0.0
    backoff_multiplier: float = 1.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts deve ser ao menos 1")
        if self.delay_seconds < 0:
            raise ValueError("delay_seconds não pode ser negativo")
        if self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier deve ser >= 1")


def run_with_retry(
    operation: Callable[P, T],
    *args: P.args,
    policy: RetryPolicy = RetryPolicy(),
    retry_on: tuple[type[Exception], ...] = (Exception,),
    sleep_fn: Callable[[float], None] = sleep,
    **kwargs: P.kwargs,
) -> T:
    """Executa uma operação até sucesso ou limite, preservando a causa final."""
    delay = policy.delay_seconds
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return operation(*args, **kwargs)
        except retry_on as error:
            if attempt == policy.max_attempts:
                raise RetryExhaustedError(f"operação falhou após {attempt} tentativas") from error
            if delay:
                sleep_fn(delay)
            delay *= policy.backoff_multiplier
    raise AssertionError("fluxo de retry inalcançável")
