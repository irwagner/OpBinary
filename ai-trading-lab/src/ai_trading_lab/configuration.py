"""Configuração tipada e segura, sem credenciais no código."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .errors import ConfigurationError
from .models import SystemMode

DEFAULT_CAPITAL_SCENARIOS = (100, 300, 500, 700, 1000)


@dataclass(frozen=True, slots=True)
class ExecutionConfig:
    enabled: bool


@dataclass(frozen=True, slots=True)
class SecurityConfig:
    human_approval_required: bool
    kill_switch_enabled: bool


@dataclass(frozen=True, slots=True)
class ValidationConfig:
    min_fold_pass_ratio: float = 1.0


@dataclass(frozen=True, slots=True)
class SystemConfig:
    mode: SystemMode
    execution: ExecutionConfig
    security: SecurityConfig
    capital_scenarios: tuple[int, ...] = DEFAULT_CAPITAL_SCENARIOS
    validation: ValidationConfig = ValidationConfig()


def load_system_config(raw: Mapping[str, object]) -> SystemConfig:
    """Valida um mapeamento de configuração e aplica barreiras de segurança."""
    mode = _read_mode(raw)
    execution = ExecutionConfig(enabled=_read_bool(raw, "execution", "enabled"))
    security = SecurityConfig(
        human_approval_required=_read_bool(raw, "human_approval", "required", True),
        kill_switch_enabled=_read_bool(raw, "kill_switch", "enabled", True),
    )
    capital_scenarios = _read_capital_scenarios(raw)
    validation = ValidationConfig(min_fold_pass_ratio=_read_fold_ratio(raw))
    config = SystemConfig(mode, execution, security, capital_scenarios, validation)
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
    if any(not isinstance(value, int) or value <= 0 for value in values):
        raise ConfigurationError("capital_scenarios deve conter inteiros positivos")
    return tuple(values)


def _read_fold_ratio(raw: Mapping[str, object]) -> float:
    validation = raw.get("validation", {})
    if not isinstance(validation, Mapping):
        raise ConfigurationError("validation deve ser um mapeamento")
    ratio = validation.get("min_fold_pass_ratio", 1.0)
    if not isinstance(ratio, (int, float)) or isinstance(ratio, bool) or not 0 < ratio <= 1:
        raise ConfigurationError("validation.min_fold_pass_ratio deve estar entre 0 e 1")
    return float(ratio)


def _validate_safety(config: SystemConfig) -> None:
    if config.mode is SystemMode.RESEARCH and config.execution.enabled:
        raise ConfigurationError("RESEARCH não pode habilitar execução")
    if config.mode is SystemMode.REAL:
        if config.execution.enabled:
            raise ConfigurationError("REAL permanece bloqueado nesta fase")
        if not config.security.human_approval_required:
            raise ConfigurationError("REAL exige aprovação humana")
        if not config.security.kill_switch_enabled:
            raise ConfigurationError("REAL exige kill switch habilitado")
