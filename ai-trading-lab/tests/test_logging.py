from __future__ import annotations

import io
import unittest

from ai_trading_lab.logging import configure_structured_logger, log_event, sanitize


class LoggingTests(unittest.TestCase):
    def test_sanitize_masks_sensitive_mapping_keys(self) -> None:
        payload = sanitize(
            {
                "api_key": "abc123",
                "nested": {"token": "xyz"},
                "Authorization": "Bearer live-token",
                "private_key": "key-material",
            }
        )

        self.assertEqual("***REDACTED***", payload["api_key"])
        self.assertEqual("***REDACTED***", payload["nested"]["token"])
        self.assertEqual("***REDACTED***", payload["Authorization"])
        self.assertEqual("***REDACTED***", payload["private_key"])

    def test_sanitize_masks_free_text_secret_formats(self) -> None:
        cases = (
            ("credential=very secret value; event=ok", "very secret value"),
            ("Authorization: Bearer abc.def, event=ok", "abc.def"),
            ("password=secret with space; event=ok", "secret with space"),
            ("access_token=access-live-secret; event=ok", "access-live-secret"),
            ("refreshToken=refresh-live-secret; event=ok", "refresh-live-secret"),
            ("request used Bearer standalone-token", "standalone-token"),
            (
                "-----BEGIN PRIVATE KEY-----\nraw-private-key\n-----END PRIVATE KEY-----",
                "raw-private-key",
            ),
        )

        for message, secret in cases:
            with self.subTest(message=message):
                sanitized = sanitize(message)
                self.assertIn("***REDACTED***", sanitized)
                self.assertNotIn(secret, sanitized)

    def test_structured_log_does_not_emit_secret(self) -> None:
        stream = io.StringIO()
        logger = configure_structured_logger("test.secure.logging", stream)

        log_event(
            logger,
            "credential=message-secret; configuration_loaded",
            api_key="field-secret",
            component="config",
        )

        output = stream.getvalue()
        self.assertIn("***REDACTED***", output)
        self.assertNotIn("message-secret", output)
        self.assertNotIn("field-secret", output)
