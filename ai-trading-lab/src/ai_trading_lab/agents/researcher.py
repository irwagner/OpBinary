"""Research Agent: gera hipóteses formalizadas (Fase 4).

A geração é determinística — uma varredura ordenada de um espaço de busca
declarado. Não há LLM produzindo números aqui (MASTER_SPEC seção 2.2).

O espaço cobre quatro famílias de padrão (momentum, sequência de cor,
alternância e corpo de vela), com filtro opcional de horário. Combinações já
experimentadas são excluídas, evitando os loops inúteis da seção 58.

Disciplina contra falso positivo: quanto maior o espaço varrido, maior a chance
de uma regra parecer boa por acaso. O agente informa quantas hipóteses já foram
testadas contra um dataset, e `required_expectancy_margin` traduz isso em uma
exigência mais dura, aplicada pelo Validator.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import product, zip_longest

from ..contracts import Hypothesis
from ..identifiers import StrategyIdGenerator
from ..strategy import RuleMode, SignalSource, StrategyRule
from .base import AuditSink, BaseAgent

_LOOKBACKS = (2, 3, 4, 5, 8, 13)
_THRESHOLDS = (0.0003, 0.0005, 0.001, 0.002)
_EXPIRIES = (1, 2, 3, 5)
_MODES = (RuleMode.FOLLOW, RuleMode.REVERT)
_STREAKS = (2, 3, 4, 5, 6)
_BODY_RATIOS = (0.5, 0.7, 0.9)
_HOUR_WINDOWS: tuple[tuple[int, int] | None, ...] = (
    None,
    (0, 5),
    (6, 11),
    (12, 17),
    (18, 23),
)


@dataclass(frozen=True, slots=True)
class RuleSignature:
    """Assinatura de uma combinação já experimentada."""

    signal_source: str
    lookback: int
    threshold: float
    expiry_periods: int
    mode: str
    streak_length: int
    hour_window: tuple[int, int] | None


def required_expectancy_margin(hypotheses_tested: int) -> float:
    """Margem extra de expectancy exigida conforme o espaço varrido cresce.

    Testar muitas regras no mesmo dado produz vencedores por acaso. A margem
    cresce com o logaritmo da quantidade testada: varrer 10 regras exige pouco,
    varrer 10 mil exige bem mais para a mesma conclusão.
    """
    if hypotheses_tested <= 1:
        return 0.0
    return 0.01 * math.log10(hypotheses_tested)


def build_search_space() -> tuple[StrategyRule, ...]:
    """Enumera o espaço de busca completo, intercalando as famílias.

    A intercalação é essencial: as famílias têm tamanhos muito diferentes, e uma
    varredura sequencial esgotaria momentum antes de testar qualquer padrão de
    cor de vela. Intercalando, um ciclo curto já cobre todas as famílias.
    """
    families = (
        _momentum_rules(),
        _streak_rules(),
        _alternation_rules(),
        _body_ratio_rules(),
    )
    interleaved: list[StrategyRule] = []
    for group in zip_longest(*families):
        interleaved.extend(rule for rule in group if rule is not None)
    return tuple(interleaved)


def _momentum_rules() -> tuple[StrategyRule, ...]:
    rules: list[StrategyRule] = []
    for lookback, threshold, expiry, mode, window in product(
        _LOOKBACKS, _THRESHOLDS, _EXPIRIES, _MODES, _HOUR_WINDOWS
    ):
        rules.append(
            StrategyRule(
                lookback=lookback,
                threshold=threshold,
                expiry_periods=expiry,
                mode=mode,
                signal_source=SignalSource.MOMENTUM,
                hour_window=window,
            )
        )
    return tuple(rules)


def _streak_rules() -> tuple[StrategyRule, ...]:
    rules: list[StrategyRule] = []
    for streak, expiry, mode, window in product(
        _STREAKS, _EXPIRIES, _MODES, _HOUR_WINDOWS
    ):
        rules.append(
            StrategyRule(
                lookback=1,
                threshold=0.0,
                expiry_periods=expiry,
                mode=mode,
                signal_source=SignalSource.STREAK,
                streak_length=streak,
                hour_window=window,
            )
        )
    return tuple(rules)


def _alternation_rules() -> tuple[StrategyRule, ...]:
    rules: list[StrategyRule] = []
    for lookback, expiry, mode, window in product(
        (2, 3, 4, 5, 6), _EXPIRIES, _MODES, _HOUR_WINDOWS
    ):
        rules.append(
            StrategyRule(
                lookback=lookback,
                threshold=0.0,
                expiry_periods=expiry,
                mode=mode,
                signal_source=SignalSource.ALTERNATION,
                hour_window=window,
            )
        )
    return tuple(rules)


def _body_ratio_rules() -> tuple[StrategyRule, ...]:
    rules: list[StrategyRule] = []
    for ratio, expiry, mode, window in product(
        _BODY_RATIOS, _EXPIRIES, _MODES, _HOUR_WINDOWS
    ):
        rules.append(
            StrategyRule(
                lookback=1,
                threshold=ratio,
                expiry_periods=expiry,
                mode=mode,
                signal_source=SignalSource.BODY_RATIO,
                hour_window=window,
            )
        )
    return tuple(rules)


def signature_of_rule(rule: StrategyRule) -> RuleSignature:
    """Assinatura de uma regra já formalizada."""
    return RuleSignature(
        signal_source=rule.signal_source.value,
        lookback=rule.lookback,
        threshold=rule.threshold,
        expiry_periods=rule.expiry_periods,
        mode=rule.mode.value,
        streak_length=rule.streak_length,
        hour_window=rule.hour_window,
    )


def signature_of(parameters: dict[str, object]) -> RuleSignature:
    """Extrai a assinatura dos parâmetros de uma hipótese avaliada."""
    window = parameters.get("hour_window")
    return RuleSignature(
        signal_source=str(parameters.get("signal_source", SignalSource.MOMENTUM.value)),
        lookback=int(parameters["lookback"]),
        threshold=float(parameters["threshold"]),
        expiry_periods=int(parameters["expiry_periods"]),
        mode=str(parameters["mode"]),
        streak_length=int(parameters.get("streak_length", 3)),
        hour_window=tuple(window) if window else None,  # type: ignore[arg-type]
    )


class ResearcherAgent(BaseAgent):
    """Enumera hipóteses candidatas de forma reproduzível."""

    name = "researcher"
    version = "v0.2.0"

    def __init__(
        self,
        software_version: str = "v0.1.0",
        audit_sink: AuditSink | None = None,
        id_generator: StrategyIdGenerator | None = None,
    ) -> None:
        super().__init__(software_version=software_version, audit_sink=audit_sink)
        self._ids = id_generator or StrategyIdGenerator()
        self._space = build_search_space()

    @property
    def search_space_size(self) -> int:
        """Tamanho total do espaço de busca declarado."""
        return len(self._space)

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
        for rule in self._space:
            if len(hypotheses) >= limit:
                break
            if signature_of_rule(rule) in exclude:
                continue
            hypotheses.append(self._build(asset, timeframe, rule))

        self.record(
            "hypotheses_generated",
            {
                "asset": asset,
                "timeframe": timeframe,
                "generated": len(hypotheses),
                "excluded": len(exclude),
                "search_space_size": self.search_space_size,
                "required_expectancy_margin": required_expectancy_margin(
                    len(exclude) + len(hypotheses)
                ),
            },
        )
        return tuple(hypotheses)

    def _build(self, asset: str, timeframe: str, rule: StrategyRule) -> Hypothesis:
        return Hypothesis(
            strategy_id=self._ids.next_id(),
            asset=asset,
            timeframe=timeframe,
            entry_conditions=(
                f"signal_source == {rule.signal_source.value}",
                rule.describe(),
            ),
            exit_rule=f"expira_em_{rule.expiry_periods}_periodos",
            filters=(
                ("serie_validada",)
                + (("janela_horaria",) if rule.hour_window else ())
            ),
            parameters=rule.as_dict(),
            envelope=self.envelope(input_ref=f"{asset}/{timeframe}"),
        )
