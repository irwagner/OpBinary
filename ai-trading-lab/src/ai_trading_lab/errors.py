"""Exceções explícitas da infraestrutura."""


class TradingLabError(Exception):
    """Erro base do domínio."""


class ConfigurationError(TradingLabError):
    """Configuração ausente, inválida ou insegura."""


class InvalidStateTransition(TradingLabError):
    """Transição não permitida pela máquina de estados."""


class PersistenceError(TradingLabError):
    """Falha ao persistir ou recuperar informação."""


class ConcurrentStateUpdate(PersistenceError):
    """Estado persistido mudou desde que o chamador o carregou."""


class PermissionDeniedError(TradingLabError):
    """Ator sem capacidade para executar uma ação protegida."""


class PromotionApprovalRequired(TradingLabError):
    """Promoção para REAL sem aprovação humana persistida."""


class PromotionRequestError(TradingLabError):
    """Solicitação de promoção inexistente ou em estado inválido."""


class RetryExhaustedError(TradingLabError):
    """Uma operação excedeu as tentativas configuradas."""


class ExperimentIdentifierError(TradingLabError):
    """Identificador de experimento inválido."""


class DataIngestionError(TradingLabError):
    """Falha ao ingerir um ponto de preço a partir da fonte da corretora."""


class DataQualityError(TradingLabError):
    """Dataset reprovado por violar uma regra de qualidade obrigatória."""


class DatasetSplitError(TradingLabError):
    """Uso indevido de TRAIN, VALIDATION ou TEST."""


class DatasetVersionError(TradingLabError):
    """Versão ou hash de dataset inválido ou incompatível."""
