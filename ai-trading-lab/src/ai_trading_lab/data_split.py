"""Split determinístico TRAIN/VALIDATION/TEST (Fase 2).

Regra obrigatória (MASTER_SPEC seção 23, 24): os conjuntos nunca se misturam.
O split é feito por corte cronológico contíguo (não aleatório) — cada ponto
pertence a exatamente uma partição, na ordem em que ocorreu no tempo. Isso
evita vazamento de informação futura para TRAIN/VALIDATION (look-ahead bias)
e é determinístico: a mesma entrada sempre produz o mesmo split.
"""

from __future__ import annotations

from dataclasses import dataclass

from .data_models import DatasetSplitKind, DatasetSplitPlan, ValidatedPricePoint
from .errors import DatasetSplitError


@dataclass(frozen=True, slots=True)
class DatasetSplitResult:
    """Resultado imutável de um split. Cada tupla é uma partição isolada."""

    train: tuple[ValidatedPricePoint, ...]
    validation: tuple[ValidatedPricePoint, ...]
    test: tuple[ValidatedPricePoint, ...]

    def partition(self, kind: DatasetSplitKind) -> tuple[ValidatedPricePoint, ...]:
        """Acessa uma partição pelo tipo, sem permitir combiná-las."""
        return {
            DatasetSplitKind.TRAIN: self.train,
            DatasetSplitKind.VALIDATION: self.validation,
            DatasetSplitKind.TEST: self.test,
        }[kind]


def split_dataset(
    points: tuple[ValidatedPricePoint, ...],
    plan: DatasetSplitPlan,
) -> DatasetSplitResult:
    """Divide pontos já ordenados cronologicamente em TRAIN/VALIDATION/TEST.

    Exige que os pontos estejam em ordem não decrescente de timestamp —
    isso é garantido por `data_validation.validate_and_normalize`, mas é
    revalidado aqui porque o split é o ponto onde um erro de mistura teria
    o maior impacto (vazamento entre partições).
    """
    for previous, current in zip(points, points[1:]):
        if current.timestamp < previous.timestamp:
            raise DatasetSplitError(
                "pontos fora de ordem cronológica não podem ser divididos em split"
            )

    total = len(points)
    if total == 0:
        return DatasetSplitResult(train=(), validation=(), test=())

    train_end = round(total * plan.train_pct)
    validation_end = train_end + round(total * plan.validation_pct)

    train = points[:train_end]
    validation = points[train_end:validation_end]
    test = points[validation_end:]

    _assert_no_overlap(train, validation, test)
    return DatasetSplitResult(train=train, validation=validation, test=test)


def _assert_no_overlap(
    train: tuple[ValidatedPricePoint, ...],
    validation: tuple[ValidatedPricePoint, ...],
    test: tuple[ValidatedPricePoint, ...],
) -> None:
    train_ids = {id(point) for point in train}
    validation_ids = {id(point) for point in validation}
    test_ids = {id(point) for point in test}
    if train_ids & validation_ids or train_ids & test_ids or validation_ids & test_ids:
        raise DatasetSplitError("split produziu sobreposição entre partições")


class TestSetGuard:
    """Impede uso acidental de TEST durante ajuste de estratégia/parâmetros.

    Qualquer código que precise ler a partição TEST deve chamar
    `unlock_for_final_evaluation()` explicitamente e apenas uma vez por
    instância. Isso torna o uso de TEST auditável e intencional — nunca
    um acesso silencioso durante desenvolvimento/tuning.
    """

    def __init__(self, split: DatasetSplitResult) -> None:
        self._split = split
        self._unlocked = False

    def train(self) -> tuple[ValidatedPricePoint, ...]:
        """TRAIN está sempre disponível para ajuste de parâmetros."""
        return self._split.train

    def validation(self) -> tuple[ValidatedPricePoint, ...]:
        """VALIDATION está sempre disponível para seleção de modelo."""
        return self._split.validation

    def test(self) -> tuple[ValidatedPricePoint, ...]:
        """TEST só é acessível após desbloqueio explícito e único."""
        if not self._unlocked:
            raise DatasetSplitError(
                "TEST está bloqueado; chame unlock_for_final_evaluation() "
                "explicitamente antes de qualquer avaliação final"
            )
        return self._split.test

    def unlock_for_final_evaluation(self) -> None:
        """Libera TEST uma única vez. Chamadas repetidas são rejeitadas."""
        if self._unlocked:
            raise DatasetSplitError(
                "TEST já foi desbloqueado; reuso indica ajuste indevido no TEST"
            )
        self._unlocked = True
