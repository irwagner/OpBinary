"""Adversarial Agent: tenta quebrar a estratégia (Fase 5).

Não é um agente de confirmação. Procura ativamente look-ahead bias, data
leakage, overfitting, instabilidade e degradação fora da amostra
(MASTER_SPEC seções 15, 24, 25, 28).

A verificação de look-ahead é estrutural, não heurística: cada sinal é
reavaliado sobre a série truncada no instante da decisão e o resultado deve
ser idêntico.
"""

from __future__ import annotations

from ..contracts import AdversarialVerdict, Finding, FormalStrategy, StatisticalReport, Verdict
from ..data_models import ValidatedPricePoint
from ..errors import DataQualityError
from ..strategy import StrategyRule, evaluate_at, generate_signals
from .base import AuditSink, BaseAgent

_MIN_TRADES_PER_PARAMETER = 30
_MAX_ACCEPTABLE_DEGRADATION = 0.10
_MAX_ACCEPTABLE_SPREAD = 0.60


def verify_no_look_ahead(
    points: tuple[ValidatedPricePoint, ...], rule: StrategyRule
) -> bool:
    """Confirma que cada sinal depende apenas de dados até o instante da decisão."""
    signals = generate_signals(points, rule)
    for signal in signals:
        truncated = points[: signal.index + 1]
        replayed = evaluate_at(truncated, len(truncated) - 1, rule)
        if replayed is not signal.direction:
            return False
    return True


def find_duplicate_timestamps(points: tuple[ValidatedPricePoint, ...]) -> int:
    """Conta timestamps repetidos, indício de leakage entre registros."""
    seen: set[object] = set()
    duplicates = 0
    for point in points:
        if point.timestamp in seen:
            duplicates += 1
        seen.add(point.timestamp)
    return duplicates


class AdversarialAgent(BaseAgent):
    """Emite PASS, WARN ou FAIL com base em achados objetivos."""

    name = "adversarial"
    version = "v0.1.0"

    def __init__(
        self,
        software_version: str = "v0.1.0",
        audit_sink: AuditSink | None = None,
    ) -> None:
        super().__init__(software_version=software_version, audit_sink=audit_sink)

    def challenge(
        self,
        strategy: FormalStrategy,
        points: tuple[ValidatedPricePoint, ...],
        report: StatisticalReport,
        *,
        experiment_id: str,
    ) -> AdversarialVerdict:
        """Executa a bateria de contestação e devolve o veredicto."""
        if strategy.rule is None:
            raise DataQualityError("estratégia sem regra não pode ser contestada")

        findings: list[Finding] = []

        if not verify_no_look_ahead(points, strategy.rule):
            findings.append(
                Finding(
                    category="look_ahead_bias",
                    severity=Verdict.FAIL,
                    description="sinal muda quando a série é truncada no instante da decisão",
                )
            )

        duplicates = find_duplicate_timestamps(points)
        if duplicates:
            findings.append(
                Finding(
                    category="data_leakage",
                    severity=Verdict.FAIL,
                    description=f"{duplicates} timestamps duplicados na série usada",
                )
            )

        required_trades = strategy.rule.parameter_count * _MIN_TRADES_PER_PARAMETER
        if report.trades < required_trades:
            findings.append(
                Finding(
                    category="overfitting",
                    severity=Verdict.FAIL if report.trades == 0 else Verdict.WARN,
                    description=(
                        f"{report.trades} operações para {strategy.rule.parameter_count} "
                        f"parâmetros (mínimo sugerido: {required_trades})"
                    ),
                )
            )

        if report.degradation > _MAX_ACCEPTABLE_DEGRADATION:
            findings.append(
                Finding(
                    category="out_of_sample_degradation",
                    severity=Verdict.FAIL,
                    description=(
                        f"expectancy cai {report.degradation:.4f} de in-sample para OOS"
                    ),
                )
            )

        if report.expectancy_spread > _MAX_ACCEPTABLE_SPREAD:
            findings.append(
                Finding(
                    category="parameter_sensitivity",
                    severity=Verdict.WARN,
                    description=(
                        f"dispersão de expectancy entre folds: {report.expectancy_spread:.4f}"
                    ),
                )
            )

        failing_folds = tuple(fold for fold in report.folds if not fold.passed)
        if failing_folds and len(failing_folds) < len(report.folds):
            findings.append(
                Finding(
                    category="bad_period",
                    severity=Verdict.WARN,
                    description=(
                        f"{len(failing_folds)} de {len(report.folds)} folds com expectancy <= 0"
                    ),
                )
            )

        verdict = _aggregate(findings)
        result = AdversarialVerdict(
            strategy_id=strategy.strategy_id,
            experiment_id=experiment_id,
            verdict=verdict,
            findings=tuple(findings),
            envelope=self.envelope(
                experiment_id=experiment_id,
                decision=verdict.value,
                reason=f"{len(findings)} achado(s)",
            ),
        )

        self.record(
            "adversarial_completed",
            {
                "strategy_id": strategy.strategy_id,
                "verdict": verdict.value,
                "findings": [finding.category for finding in findings],
            },
            experiment_id=experiment_id,
        )
        return result


def _aggregate(findings: list[Finding]) -> Verdict:
    if any(finding.severity is Verdict.FAIL for finding in findings):
        return Verdict.FAIL
    if any(finding.severity is Verdict.WARN for finding in findings):
        return Verdict.WARN
    return Verdict.PASS
