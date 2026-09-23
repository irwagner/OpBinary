from __future__ import annotations

import unittest

from ai_trading_lab.configuration import load_system_config
from ai_trading_lab.errors import ConfigurationError
from ai_trading_lab.models import SystemMode


class ConfigurationTests(unittest.TestCase):
    def test_loads_safe_research_configuration(self) -> None:
        config = load_system_config(
            {
                "mode": "RESEARCH",
                "execution": {"enabled": False},
                "capital_scenarios": [100, 300],
            }
        )

        self.assertEqual(SystemMode.RESEARCH, config.mode)
        self.assertFalse(config.execution.enabled)
        self.assertEqual((100, 300), config.capital_scenarios)
        self.assertEqual(1.0, config.validation.min_fold_pass_ratio)

    def test_rejects_research_with_execution_enabled(self) -> None:
        with self.assertRaises(ConfigurationError):
            load_system_config({"mode": "RESEARCH", "execution": {"enabled": True}})

    def test_rejects_real_execution_in_phase_one(self) -> None:
        with self.assertRaises(ConfigurationError):
            load_system_config(
                {
                    "mode": "REAL",
                    "execution": {"enabled": True},
                    "human_approval": {"required": True},
                    "kill_switch": {"enabled": True},
                }
            )

    def test_requires_real_security_barriers(self) -> None:
        with self.assertRaises(ConfigurationError):
            load_system_config(
                {
                    "mode": "REAL",
                    "execution": {"enabled": False},
                    "human_approval": {"required": False},
                    "kill_switch": {"enabled": True},
                }
            )
