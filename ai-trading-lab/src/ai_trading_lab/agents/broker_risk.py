"""Broker Risk Agent: risco de contraparte (Fase 5, ADR-006).

`FAIL` bloqueia entrada em DEMO, independente do resultado da estratégia
(MASTER_SPEC seção 16.1).

Este é o único agente que depende de informação externa. A coleta é feita por
uma `BrokerIntelligenceSource` injetada — o agente em si não embute nenhum
cliente HTTP, endpoint de corretora ou credencial.

Falha fechada: sem fonte configurada, o resultado é `FAIL`, nunca `PASS`.
Todo achado exige fonte citada, senão é descartado como evidência inválida.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from ..contracts import BrokerRiskReport, Finding, Verdict
from ..models import utc_now
from .base import AuditSink, BaseAgent

_REVIEW_INTERVAL_DAYS = {Verdict.PASS: 30, Verdict.WARN: 7, Verdict.FAIL: 7}

REQUIRED_CATEGORIES = (
    "regulatory",
    "complaints",
    "withdrawal_pattern",
    "pricing_transparency",
    "demo_availability",
    "historical_data_availability",
)


@dataclass(frozen=True, slots=True)
class IntelligenceItem:
    """Evidência sobre uma corretora, sempre com fonte rastreável."""

    category: str
    detail: str
    source_url: str
    severity: Verdict

    def is_valid_evidence(self) -> bool:
        """Evidência sem fonte ou categoria não é aceita (ADR-006)."""
        return bool(self.source_url.strip()) and self.category in REQUIRED_CATEGORIES


class BrokerIntelligenceSource(Protocol):
    """Porta de coleta de evidências sobre uma corretora."""

    def gather(self, broker_name: str) -> tuple[IntelligenceItem, ...]: ...


class NullIntelligenceSource:
    """Fonte padrão: nenhuma evidência disponível.

    Mantém o sistema seguro por omissão — sem fonte configurada, o Broker Risk
    Agent reprova a corretora e o DEMO permanece bloqueado.
    """

    def gather(self, broker_name: str) -> tuple[IntelligenceItem, ...]:
        return ()


class BrokerRiskAgent(BaseAgent):
    """Avalia idoneidade da corretora antes de qualquer uso de DEMO."""

    name = "broker_risk"
    version = "v0.1.0"

    def __init__(
        self,
        software_version: str = "v0.1.0",
        audit_sink: AuditSink | None = None,
        source: BrokerIntelligenceSource | None = None,
    ) -> None:
        super().__init__(software_version=software_version, audit_sink=audit_sink)
        self._source = source or NullIntelligenceSource()

    def evaluate(
        self,
        broker_name: str,
        *,
        previous_status: Verdict | None = None,
    ) -> BrokerRiskReport:
        """Coleta evidências e emite PASS, WARN ou FAIL."""
        items = self._source.gather(broker_name)
        valid = tuple(item for item in items if item.is_valid_evidence())
        discarded = len(items) - len(valid)

        findings: list[Finding] = [
            Finding(
                category=item.category,
                severity=item.severity,
                description=f"{item.detail} (fonte: {item.source_url})",
            )
            for item in valid
        ]

        if discarded:
            findings.append(
                Finding(
                    category="pricing_transparency",
                    severity=Verdict.WARN,
                    description=f"{discarded} evidência(s) descartada(s) por falta de fonte válida",
                )
            )

        missing = tuple(
            category
            for category in REQUIRED_CATEGORIES
            if not any(item.category == category for item in valid)
        )
        if missing:
            findings.append(
                Finding(
                    category="regulatory",
                    severity=Verdict.FAIL,
                    description=(
                        "avaliação incompleta; categorias sem evidência: "
                        f"{sorted(missing)}"
                    ),
                )
            )

        status = _aggregate(findings)
        evaluated_at = utc_now()
        report = BrokerRiskReport(
            broker_name=broker_name,
            status=status,
            basis_risk=True,
            findings=tuple(findings),
            sources=tuple(item.source_url for item in valid),
            evaluated_at=evaluated_at,
            next_review_due=evaluated_at
            + timedelta(days=_REVIEW_INTERVAL_DAYS[status]),
            previous_status=previous_status,
            envelope=self.envelope(decision=status.value),
        )

        self.record(
            "broker_risk_evaluated",
            {
                "broker": broker_name,
                "status": status.value,
                "previous_status": previous_status.value if previous_status else None,
                "evidence_count": len(valid),
                "discarded_evidence": discarded,
                "missing_categories": sorted(missing),
            },
        )
        return report

    def detect_regression(
        self, report: BrokerRiskReport
    ) -> bool:
        """Indica regressão PASS → FAIL, que suspende DEMO em uso (ADR-003)."""
        regressed = (
            report.previous_status is Verdict.PASS and report.status is Verdict.FAIL
        )
        if regressed:
            self.record(
                "broker_risk_regression",
                {
                    "broker": report.broker_name,
                    "previous_status": Verdict.PASS.value,
                    "status": Verdict.FAIL.value,
                    "action": "suspend_demo_and_require_human_review",
                },
            )
        return regressed


def _aggregate(findings: list[Finding]) -> Verdict:
    if not findings:
        return Verdict.FAIL
    if any(finding.severity is Verdict.FAIL for finding in findings):
        return Verdict.FAIL
    if any(finding.severity is Verdict.WARN for finding in findings):
        return Verdict.WARN
    return Verdict.PASS
