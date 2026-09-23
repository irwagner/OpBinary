from __future__ import annotations

import unittest

from ai_trading_lab.errors import ExperimentIdentifierError
from ai_trading_lab.identifiers import ExperimentIdGenerator, SoftwareVersion


class IdentifierTests(unittest.TestCase):
    def test_generates_sequential_experiment_ids(self) -> None:
        generator = ExperimentIdGenerator()

        self.assertEqual("EXP-000001", generator.next_id())
        self.assertEqual("EXP-000002", generator.next_id())

    def test_validates_experiment_id_format(self) -> None:
        self.assertEqual("EXP-000999", ExperimentIdGenerator.validate("EXP-000999"))
        with self.assertRaises(ExperimentIdentifierError):
            ExperimentIdGenerator.validate("experiment-1")

    def test_validates_software_version(self) -> None:
        self.assertEqual("v1.2.3", SoftwareVersion("v1.2.3").value)
        with self.assertRaises(ValueError):
            SoftwareVersion("1.2.3")
