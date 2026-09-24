from __future__ import annotations

import unittest
from datetime import timedelta
from pathlib import Path

from ai_trading_lab.configuration import load_config_file, load_system_config
from ai_trading_lab.dashboard import (
    count_strategies,
    render_agent_screen,
    render_dataset_screen,
    render_health_screen,
    render_main_screen,
)
from ai_trading_lab.data_ingestion import ingest_raw_batch
from ai_trading_lab.data_models import RawPricePoint
from ai_trading_lab.data_persistence import DatasetStore
from ai_trading_lab.errors import ConfigurationError
from ai_trading_lab.health import ReadinessState
from ai_trading_lab.models import Actor, ActorRole, SystemMode, SystemStatus
from ai_trading_lab.persistence import SQLiteStore
from ai_trading_lab.runtime import ResearchRuntime
from ai_trading_lab.state import StateManager
from tests.fixtures import past_start

CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs"


def _runtime_config() -> object:
    """Config reduzida para manter o teste rápido, sem afrouxar barreiras."""
    return load_system_config(
        {
            "mode": "RESEARCH",
            "execution": {"enabled": False},
            "real": {"enabled": False},
            "human_approval": {"required": True},
            "kill_switch": {"enabled": True},
            "capital_scenarios": [100, 300],
            "validation": {
                "min_fold_pass_ratio": 1.0,
                "min_sample_size": 100,
                "walk_forward_folds": 3,
                "monte_carlo_runs": 20,
            },
            "research": {
                "max_experiments_per_cycle": 3,
                "max_retries_per_agent": 2,
                "max_parameter_variations": 12,
            },
            "risk": {
                "risk_per_trade": 0.02,
                "max_drawdown_limit": 0.30,
                "max_risk_of_ruin": 0.05,
            },
        }
    )


def _ingest_series(dataset_store: DatasetStore, dataset_id: str, count: int) -> None:
    start = past_start(count + 10)
    raw = tuple(
        RawPricePoint(
            broker="TestBroker",
            asset="TESTPAIR",
            timeframe="M1",
            timestamp=start + timedelta(minutes=index),
            price=1.0 + index * 0.01,
            source="test_fixture",
        )
        for index in range(count)
    )
    ingest_raw_batch(dataset_store, dataset_id, raw)


class ConfigFileTests(unittest.TestCase):
    def test_research_config_disables_execution(self) -> None:
        config = load_config_file(CONFIG_DIR / "research.yaml")

        self.assertIs(SystemMode.RESEARCH, config.mode)
        self.assertFalse(config.execution.enabled)
        self.assertFalse(config.execution_allowed)
        self.assertFalse(config.real_allowed)

    def test_demo_config_allows_execution_with_kill_switch(self) -> None:
        config = load_config_file(CONFIG_DIR / "demo.yaml")

        self.assertIs(SystemMode.DEMO, config.mode)
        self.assertTrue(config.execution.enabled)
        self.assertTrue(config.security.kill_switch_enabled)
        self.assertTrue(config.execution_allowed)
        self.assertFalse(config.real_allowed)

    def test_real_config_keeps_execution_blocked(self) -> None:
        config = load_config_file(CONFIG_DIR / "real.yaml")

        self.assertIs(SystemMode.REAL, config.mode)
        self.assertFalse(config.execution.enabled)
        self.assertFalse(config.execution_allowed)
        self.assertFalse(config.real_allowed)
        self.assertTrue(config.security.human_approval_required)
        self.assertTrue(config.security.kill_switch_enabled)

    def test_missing_file_is_rejected(self) -> None:
        with self.assertRaises(ConfigurationError):
            load_config_file(CONFIG_DIR / "inexistente.yaml")

    def test_real_enabled_flag_is_always_rejected(self) -> None:
        with self.assertRaises(ConfigurationError):
            load_system_config(
                {
                    "mode": "RESEARCH",
                    "execution": {"enabled": False},
                    "real": {"enabled": True},
                }
            )

    def test_execution_without_kill_switch_is_rejected(self) -> None:
        with self.assertRaises(ConfigurationError):
            load_system_config(
                {
                    "mode": "DEMO",
                    "execution": {"enabled": True},
                    "kill_switch": {"enabled": False},
                }
            )

    def test_boolean_is_not_accepted_as_capital(self) -> None:
        with self.assertRaises(ConfigurationError):
            load_system_config(
                {
                    "mode": "RESEARCH",
                    "execution": {"enabled": False},
                    "capital_scenarios": [True],
                }
            )


class HealthAndRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = _runtime_config()
        self.store = SQLiteStore()
        self.dataset_store = DatasetStore()
        self.runtime = ResearchRuntime(self.config, self.store, self.dataset_store)

    def tearDown(self) -> None:
        self.store.close()
        self.dataset_store.close()

    def test_health_reports_no_data_without_dataset(self) -> None:
        health = self.runtime.health(("DATA-EMPTY",))

        self.assertIs(ReadinessState.NO_DATA, health.readiness)
        self.assertTrue(health.real_blocked)
        self.assertFalse(health.execution_allowed)
        self.assertFalse(health.can_run_cycle)

    def test_health_is_ready_once_dataset_exists(self) -> None:
        _ingest_series(self.dataset_store, "DATA-READY", 150)

        health = self.runtime.health(("DATA-READY",))

        self.assertIs(ReadinessState.READY, health.readiness)
        self.assertEqual(1, health.dataset_count)

    def test_health_blocks_when_emergency_stopped(self) -> None:
        _ingest_series(self.dataset_store, "DATA-READY", 150)
        StateManager(self.store).emergency_stop(
            "teste", actor=Actor("human-test", ActorRole.HUMAN)
        )

        health = self.runtime.health(("DATA-READY",))

        self.assertIs(ReadinessState.BLOCKED, health.readiness)
        self.assertIs(SystemStatus.EMERGENCY_STOPPED, health.system_status)

    def test_cycle_does_not_run_without_data(self) -> None:
        outcome = self.runtime.run_cycle("DATA-MISSING", payout=0.87)

        self.assertIs(ReadinessState.NO_DATA, outcome.readiness)
        self.assertEqual(0, outcome.evaluated)
        self.assertTrue(outcome.errors)

    def test_cycle_runs_and_produces_reports(self) -> None:
        _ingest_series(self.dataset_store, "DATA-CYCLE", 150)

        outcome = self.runtime.run_cycle("DATA-CYCLE", payout=0.87, cycle_index=1)

        self.assertIs(ReadinessState.READY, outcome.readiness)
        self.assertGreater(outcome.evaluated, 0)
        self.assertTrue(outcome.reports)
        self.assertIn("CYCLE REPORT", outcome.reports[-1])

    def test_cycle_blocks_promotion_without_broker_risk_pass(self) -> None:
        _ingest_series(self.dataset_store, "DATA-BROKER", 150)

        outcome = self.runtime.run_cycle(
            "DATA-BROKER", payout=0.87, require_broker_risk=True
        )

        counters = count_strategies(self.store)
        self.assertGreater(counters.total, 0)
        self.assertEqual(0, counters.candidates)
        self.assertGreater(outcome.rejected + outcome.needs_research, 0)

    def test_cycle_never_enables_execution_in_research(self) -> None:
        _ingest_series(self.dataset_store, "DATA-SAFE", 150)

        self.runtime.run_cycle("DATA-SAFE", payout=0.87)

        health = self.runtime.health(("DATA-SAFE",))
        self.assertFalse(health.execution_allowed)
        self.assertTrue(health.real_blocked)

    def test_stop_moves_system_to_stopped(self) -> None:
        _ingest_series(self.dataset_store, "DATA-STOP", 150)
        self.runtime.run_cycle("DATA-STOP", payout=0.87)

        self.runtime.stop("fim do teste")

        self.assertIs(SystemStatus.STOPPED, self.runtime.system_status)

    def test_stopped_cycle_does_not_poison_tried_count(self) -> None:
        """Regressão: um ciclo negado por STOPPED não pode contar como testado.

        Antes do fix, run_cycle gravava o experimento e marcava a hipótese como
        testada ANTES do gate de status do Supervisor. Com o sistema em STOPPED
        o espaço inteiro era marcado como varrido sem nada ter sido avaliado.
        """
        _ingest_series(self.dataset_store, "DATA-STOPPED", 150)
        human = Actor("human-test", ActorRole.HUMAN)
        self.runtime._system_state.transition(
            SystemStatus.RUNNING, "iniciar", actor=human
        )
        self.runtime._system_state.transition(
            SystemStatus.STOPPED, "parar antes de varrer", actor=human
        )
        self.assertIs(SystemStatus.STOPPED, self.runtime.system_status)

        experiments_before = len(self.store.load_experiment_parameters())

        outcome = self.runtime.run_cycle("DATA-STOPPED", payout=0.87)

        # Nada avaliado, nada avançado, e — o ponto do fix — nada contado nem gravado.
        self.assertEqual(0, outcome.evaluated)
        self.assertEqual(0, self.runtime.tried_count)
        self.assertEqual(
            experiments_before, len(self.store.load_experiment_parameters())
        )

    def test_tried_count_is_scoped_per_dataset(self) -> None:
        """Regressão: varrer um ativo não marca o espaço de busca de outro.

        Antes do fix, tried_count era global (sem dataset_prefix), então
        experimentos de um dataset marcavam todos os outros como já testados.
        """
        _ingest_series(self.dataset_store, "DATA-ONE", 150)
        _ingest_series(self.dataset_store, "DATA-TWO", 150)

        self.runtime.run_cycle("DATA-ONE", payout=0.87)
        tried_one = self.runtime.tried_count
        self.assertGreater(tried_one, 0)

        # Trocar para o segundo dataset: a contagem reflete SÓ o que foi testado
        # nele, não herda as assinaturas do primeiro.
        outcome_two = self.runtime.run_cycle("DATA-TWO", payout=0.87)
        self.assertGreater(outcome_two.evaluated, 0)


class DashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = _runtime_config()
        self.store = SQLiteStore()
        self.dataset_store = DatasetStore()
        self.runtime = ResearchRuntime(self.config, self.store, self.dataset_store)

    def tearDown(self) -> None:
        self.store.close()
        self.dataset_store.close()

    def test_main_screen_shows_mode_and_barriers(self) -> None:
        health = self.runtime.health(())
        screen = render_main_screen(self.config, health, count_strategies(self.store))

        self.assertIn("AI TRADING LAB", screen)
        self.assertIn("Mode:              RESEARCH", screen)
        self.assertIn("REAL:              BLOCKED", screen)
        self.assertIn("Execution:         DISABLED", screen)

    def test_agent_screen_lists_all_agents(self) -> None:
        screen = render_agent_screen()

        for agent in ("Supervisor", "Broker Risk", "Validator", "Reporter"):
            self.assertIn(agent, screen)

    def test_health_screen_lists_checks(self) -> None:
        screen = render_health_screen(self.runtime.health(()))

        self.assertIn("HEALTH CHECK", screen)
        self.assertIn("real_blocked", screen)
        self.assertIn("kill_switch", screen)

    def test_dataset_screen_without_datasets(self) -> None:
        self.assertIn("nenhum dataset registrado", render_dataset_screen(self.dataset_store, ()))

    def test_dataset_screen_shows_hash_and_coverage(self) -> None:
        _ingest_series(self.dataset_store, "DATA-DASH", 120)

        screen = render_dataset_screen(self.dataset_store, ("DATA-DASH",))

        self.assertIn("DATA-DASH v1", screen)
        self.assertIn("hash=", screen)
