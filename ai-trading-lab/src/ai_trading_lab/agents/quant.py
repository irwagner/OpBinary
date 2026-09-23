"""Quant Agent: transforma hipóteses em regras computáveis (Fase 4).

Rejeita qualquer hipótese que não seja mensurável. Frases vagas do tipo
"quando o mercado estiver forte" são reprovadas explicitamente
(MASTER_SPEC seção 11).
"""

from __future__ import annotations

from ..contracts import FormalStrategy, Hypothesis
from ..strategy import RuleMode, StrategyRule
from .base import AuditSink, BaseAgent

_REQUIRED_PARAMETERS = ("lookback", "threshold", "expiry_periods", "mode")
_VAGUE_TERMS = (
    "forte",
    "fraco",
    "tendência clara",
    "bom momento",
    "parece",
    "provavelmente",
    "geralmente",
    "strong",
    "weak",
    "maybe",
)


class QuantAgent(BaseAgent):
    """Formaliza hipóteses em `StrategyRule` reproduzível."""

    name = "quant"
    version = "v0.1.0"

    def __init__(
        self,
        software_version: str = "v0.1.0",
        audit_sink: AuditSink | None = None,
    ) -> None:
        super().__init__(software_version=software_version, audit_sink=audit_sink)

    def formalize(self, hypothesis: Hypothesis) -> FormalStrategy:
        """Devolve uma estratégia computável ou uma rejeição com motivo."""
        vague = self._find_vague_term(hypothesis)
        if vague is not None:
            return self._reject(
                hypothesis, f"condição não mensurável detectada: '{vague}'"
            )

        missing = [key for key in _REQUIRED_PARAMETERS if key not in hypothesis.parameters]
        if missing:
            return self._reject(
                hypothesis, f"parâmetros obrigatórios ausentes: {sorted(missing)}"
            )

        try:
            rule = StrategyRule(
                lookback=int(hypothesis.parameters["lookback"]),
                threshold=float(hypothesis.parameters["threshold"]),
                expiry_periods=int(hypothesis.parameters["expiry_periods"]),
                mode=RuleMode(str(hypothesis.parameters["mode"])),
            )
        except (TypeError, ValueError) as error:
            return self._reject(hypothesis, f"parâmetros inválidos: {error}")

        self.record(
            "strategy_formalized",
            {"strategy_id": hypothesis.strategy_id, "rule": rule.as_dict()},
        )
        return FormalStrategy(
            strategy_id=hypothesis.strategy_id,
            rule=rule,
            reproducible=True,
            envelope=self.envelope(
                input_ref=hypothesis.strategy_id, decision="FORMALIZED"
            ),
        )

    def _find_vague_term(self, hypothesis: Hypothesis) -> str | None:
        text = " ".join(
            (*hypothesis.entry_conditions, hypothesis.exit_rule, *hypothesis.filters)
        ).lower()
        for term in _VAGUE_TERMS:
            if term in text:
                return term
        return None

    def _reject(self, hypothesis: Hypothesis, reason: str) -> FormalStrategy:
        self.record(
            "strategy_rejected_by_quant",
            {"strategy_id": hypothesis.strategy_id, "reason": reason},
        )
        return FormalStrategy(
            strategy_id=hypothesis.strategy_id,
            rule=None,
            reproducible=False,
            rejection_reason=reason,
            envelope=self.envelope(
                input_ref=hypothesis.strategy_id, decision="REJECTED", reason=reason
            ),
        )
