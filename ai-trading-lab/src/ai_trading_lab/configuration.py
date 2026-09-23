"""Configuração tipada e segura, sem credenciais no código.

Falha fechada: qualquer combinação insegura é rejeitada no carregamento, não
em runtime. A barreira de REAL é modelada explicitamente (`real.enabled`),
além do campo `mode` (MASTER_SPEC seção 68).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .errors import ConfigurationError
from .models import SystemMode

DEFAULT_CAPITAL_SCENARIOS = (100, 300, 500, 700, 1000)


@dataclass(frozen=True, slots=True)
class ExecutionConfig:
    enabled: bool


@dataclass(frozen=True, slots=True)
class RealBarrierConfig:
    """Barreira adicional de REAL, independente de `mode`."""

    enabled: bool = False


@dataclass(frozen=True, slots=True)
class SecurityConfig:
    human_approval_required: bool
    kill_switch_enabled: bool


@dataclass(frozen=True, slots=True)
class ValidationConfig:
    min_fold_pass_ratio: float = 1.0
    min_sample_size: int = 200
    walk_forward_folds: int = 5
    monte_carlo_runs: int = 1000


@dataclass(frozen=True, slots=True)
class ResearchConfig:
    max_experiments_per_cycle: int = 10
    max_retries_per_agent: int = 3
    max_parameter_variations: int = 24


@dataclass(frozen=True, slots=True)
class RiskConfig:
    risk_per_trade: float = 0.02
    max_drawdown_limit: float = 0.30
    max_risk_of_ruin: float = 0.05


@dataclass(frozen=True, slots=True)
class SystemConfig:
    mode: SystemMode
    execution: ExecutionConfig
    security: SecurityConfig
    capital_scenarios: tuple[int, ...] = DEFAULT_CAPITAL_SCENARIOS
    validation: ValidationConfig = ValidationConfig()
    research: ResearchConfig = ResearchConfig()
    risk: RiskConfig = RiskConfig()
    real: RealBarrierConfig = RealBarrierConfig()

    @property
    def execution_allowed(self) -> bool:
        """Execução só é permitida em DEMO com kill switch ativo."""
        return self.execution.enabled and self.mode is SystemMode.DEMO

    @property
    def real_allowed(self) -> bool:
        """REAL nunca é permitido por configuração nesta fase do projeto."""
        return False


def load_config_file(path: Path | str) -> SystemConfig:
    """Carrega e valida um arquivo YAML de configuração."""
    import yaml

    file_path = Path(path)
    if not file_path.is_file():
        raise ConfigurationError(f"arquivo de configuração não encontrado: {file_path}")
    try:
        raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ConfigurationError(f"YAML inválido em {file_path}") from error
    if not isinstance(raw, Mapping):
        raise ConfigurationError(f"configuração de {file_path} deve ser um mapeamento")
    return load_system_config(raw)


def load_system_config(raw: Mapping[str, object]) -> SystemConfig:
    """Valida um mapeamento de configuração e aplica barreiras de segurança."""
    config = SystemConfig(
        mode=_read_mode(raw),
        execution=ExecutionConfig(enabled=_read_bool(raw, "execution", "enabled")),
        security=SecurityConfig(
            human_approval_required=_read_bool(raw, "human_approval", "required", True),
            kill_switch_enabled=_read_bool(raw, "kill_switch", "enabled", True),
        ),
        capital_scenarios=_read_capital_scenarios(raw),
        validation=_read_validation(raw),
        research=_read_research(raw),
        risk=_read_risk(raw),
        real=RealBarrierConfig(enabled=_read_bool(raw, "real", "enabled", False)),
    )
    _validate_safety(config)
    return config


def _read_mode(raw: Mapping[str, object]) -> SystemMode:
    value = raw.get("mode")
    try:
        return SystemMode(str(value))
    except ValueError as error:
        raise ConfigurationError("mode deve ser RESEARCH, DEMO ou REAL") from error


def _read_bool(
    raw: Mapping[str, object], section: str, key: str, default: bool | None = None
) -> bool:
    nested = raw.get(section)
    if nested is None and default is not None:
        return default
    if not isinstance(nested, Mapping) or not isinstance(nested.get(key), bool):
        raise ConfigurationError(f"{section}.{key} deve ser booleano")
    return nested[key]


def _read_capital_scenarios(raw: Mapping[str, object]) -> tuple[int, ...]:
    values = raw.get("capital_scenarios", DEFAULT_CAPITAL_SCENARIOS)
    if not isinstance(values, (list, tuple)) or not values:
        raise ConfigurationError("capital_scenarios deve ser uma lista não vazia")
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ConfigurationError("capital_scenarios deve conter inteiros positivos")
    return tuple(values)


def _section(raw: Mapping[str, object], name: str) -> Mapping[str, Any]:
    section = raw.get(name, {})
    if not isinstance(section, Mapping):
        raise ConfigurationError(f"{name} deve ser um mapeamento")
    return section


def _read_ratio(section: Mapping[str, Any], name: str, key: str, default: float) -> float:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 1:
        raise ConfigurationError(f"{name}.{key} deve estar entre 0 e 1")
    return float(value)


def _read_positive_int(section: Mapping[str, Any], name: str, key: str, default: int) -> int:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigurationError(f"{name}.{key} deve ser um inteiro >= 1")
    return value


def _read_validation(raw: Mapping[str, object]) -> ValidationConfig:
    section = _section(raw, "validation")
    return ValidationConfig(
        min_fold_pass_ratio=_read_ratio(section, "validation", "min_fold_pass_ratio", 1.0),
        min_sample_size=_read_positive_int(section, "validation", "min_sample_size", 200),
        walk_forward_folds=_read_positive_int(section, "validation", "walk_forward_folds", 5),
        monte_carlo_runs=_read_positive_int(section, "validation", "monte_carlo_runs", 1000),
    )


def _read_research(raw: Mapping[str, object]) -> ResearchConfig:
    section = _section(raw, "research")
    return ResearchConfig(
        max_experiments_per_cycle=_read_positive_int(
            section, "research", "max_experiments_per_cycle", 10
        ),
        max_retries_per_agent=_read_positive_int(
            section, "research", "max_retries_per_agent", 3
        ),
        max_parameter_variations=_read_positive_int(
            section, "research", "max_parameter_variations", 24
        ),
    )


def _read_risk(raw: Mapping[str, object]) -> RiskConfig:
    section = _section(raw, "risk")
    return RiskConfig(
        risk_per_trade=_read_ratio(section, "risk", "risk_per_trade", 0.02),
        max_drawdown_limit=_read_ratio(section, "risk", "max_drawdown_limit", 0.30),
        max_risk_of_ruin=_read_ratio(section, "risk", "max_risk_of_ruin", 0.05),
    )


def _validate_safety(config: SystemConfig) -> None:
    if config.real.enabled:
        raise ConfigurationError("real.enabled deve permanecer false nesta fase")
    if config.mode is SystemMode.RESEARCH and config.execution.enabled:
        raise ConfigurationError("RESEARCH não pode habilitar execução")
    if config.execution.enabled and not config.security.kill_switch_enabled:
        raise ConfigurationError("execução habilitada exige kill switch habilitado")
    if config.mode is SystemMode.DEMO and config.execution.enabled:
        if not config.security.human_approval_required:
            raise ConfigurationError("DEMO exige aprovação humana configurada")
    if config.mode is SystemMode.REAL:
        if config.execution.enabled:
            raise ConfigurationError("REAL permanece bloqueado nesta fase")
        if not config.security.human_approval_required:
            raise ConfigurationError("REAL exige aprovação humana")
        if not config.security.kill_switch_enabled:
            raise ConfigurationError("REAL exige kill switch habilitado")
