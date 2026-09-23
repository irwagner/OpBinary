"""Research Agent: gera hipóteses formalizadas (Fase 4).

A geração é determinística — uma varredura ordenada de uma grade de
parâmetros. Não há LLM produzindo números aqui (MASTER_SPEC seção 2.2).
Combinações já rejeitadas são excluídas, evitando os loops inúteis descritos
na seção 58.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

from ..contracts import Hypothesis
from ..identifiers import StrategyIdGenerator
from ..strategy import RuleMode
from .base import AuditSink, BaseAgent

_LOOKBACKS = (2, 3, 5, 8, 13)
_THRESHOLDS = (0.0005, 0.001, 0.002)
_EXPIRIES = (1, 3, 5)
_MODES = (RuleMode.FOLLOW, RuleMode.REVERT)


@dataclass(frozen=True, slots=True)
class RuleSignature:
    """Assinatura de uma combinação de parâmetros já experimentada."""

    lookback: int
    threshold: float
    expiry_periods: int
    mode: str


class ResearcherAgent(BaseAgent):
    """Enumera hipóteses candidatas de forma reproduzível."""

    name = "researcher"
    version = "v0.1.0"

    def __init__(
        self,
        software_version: str = "v0.1.0",
        audit_sink: AuditSink | None = None,
        id_generator: StrategyIdGenerator | None = None,
    ) -> None:
        super().__init__(software_version=software_version, audit_sink=audit_sink)
        self._ids = id_generator or StrategyIdGenerator()

    def generate(
        self,
        asset: str,
        timeframe: str,
        *,
        limit: int,
        exclude: frozenset[RuleSignature] = frozenset(),
    ) -> tuple[Hypothesis, ...]:
        """Produz até `limit` hipóteses inéditas para o ativo/timeframe."""
        if limit < 1:
            raise ValueError("limit deve ser >= 1")

        hypotheses: list[Hypothesis] = []
        for lookback, threshold, expiry, mode in product(
            _LOOKBACKS, _THRESHOLDS, _EXPIRIES, _MODES
        ):
            if len(hypotheses) >= limit:
                break
            signature = RuleSignature(lookback, threshold, expiry, mode.value)
            if signature in exclude:
                continue
            hypotheses.append(self._build(asset, timeframe, lookback, threshold, expiry, mode))

        self.record(
            "hypotheses_generated",
            {
                "asset": asset,
                "timeframe": timeframe,
                "generated": len(hypotheses),
                "excluded": len(exclude),
            },
        )
        return tuple(hypotheses)

    def _build(
        self,
        asset: str,
        timeframe: str,
        lookback: int,
        threshold: float,
        expiry: int,
        mode: RuleMode,
    ) -> Hypothesis:
        strategy_id = self._ids.next_id()
        return Hypothesis(
            strategy_id=strategy_id,
            asset=asset,
            timeframe=timeframe,
            entry_conditions=(
                f"momentum_abs_over_{lookback}_periods >= {threshold}",
                f"direction_mode == {mode.value}",
            ),
            exit_rule=f"expira_em_{expiry}_periodos",
            filters=("serie_validada", "sem_gaps_relevantes"),
            parameters={
                "lookback": lookback,
                "threshold": threshold,
                "expiry_periods": expiry,
                "mode": mode.value,
            },
            envelope=self.envelope(input_ref=f"{asset}/{timeframe}"),
        )


def signature_of(parameters: dict[str, object]) -> RuleSignature:
    """Extrai a assinatura de parâmetros de uma hipótese já avaliada."""
    return RuleSignature(
        lookback=int(parameters["lookback"]),
        threshold=float(parameters["threshold"]),
        expiry_periods=int(parameters["expiry_periods"]),
        mode=str(parameters["mode"]),
    )
