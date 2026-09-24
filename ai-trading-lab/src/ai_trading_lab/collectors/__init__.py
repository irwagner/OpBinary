"""Coletores de dados de mercado.

Cada coletor é somente leitura: obtém histórico de preço e alimenta o Data
Engine. Nenhum coletor envia ordem, altera saldo ou modifica configuração de
conta.
"""

from .quadcode import CollectorConfig, CollectorSession

__all__ = ["CollectorConfig", "CollectorSession"]
