"""Agentes do AI Trading Research Lab (Fases 4 e 5).

Cada agente tem responsabilidade única, entrada e saída definidas por
`contracts.py`, e depende do Supervisor para autorizar qualquer tarefa
com efeito (ADR-001). Nenhum agente chama outro agente diretamente.
"""

from .adversarial import AdversarialAgent
from .backtester import BacktesterAgent
from .base import AGENT_TASKS, BaseAgent
from .broker_risk import BrokerIntelligenceSource, BrokerRiskAgent, NullIntelligenceSource
from .quant import QuantAgent
from .reporter import ReporterAgent
from .researcher import ResearcherAgent
from .risk import RiskAgent
from .statistician import StatisticianAgent
from .supervisor import SupervisorAgent
from .validator import ValidatorAgent

__all__ = [
    "AGENT_TASKS",
    "AdversarialAgent",
    "BacktesterAgent",
    "BaseAgent",
    "BrokerIntelligenceSource",
    "BrokerRiskAgent",
    "NullIntelligenceSource",
    "QuantAgent",
    "ReporterAgent",
    "ResearcherAgent",
    "RiskAgent",
    "StatisticianAgent",
    "SupervisorAgent",
    "ValidatorAgent",
]
