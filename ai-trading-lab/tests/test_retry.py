from __future__ import annotations

import unittest

from ai_trading_lab.errors import RetryExhaustedError
from ai_trading_lab.retry import RetryPolicy, run_with_retry


class RetryTests(unittest.TestCase):
    def test_retries_until_operation_succeeds(self) -> None:
        attempts = 0

        def operation() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ValueError("temporary")
            return "ok"

        result = run_with_retry(operation, policy=RetryPolicy(max_attempts=3))

        self.assertEqual("ok", result)
        self.assertEqual(3, attempts)

    def test_raises_after_maximum_attempts(self) -> None:
        with self.assertRaises(RetryExhaustedError) as context:
            run_with_retry(lambda: (_ for _ in ()).throw(ValueError("temporary")), policy=RetryPolicy(2))

        self.assertIsInstance(context.exception.__cause__, ValueError)

    def test_rejects_invalid_policy(self) -> None:
        with self.assertRaises(ValueError):
            RetryPolicy(max_attempts=0)
