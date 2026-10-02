from __future__ import annotations

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from google.genai import errors
from pydantic import BaseModel

from dhaga_os.llm import ModelUnavailable, REQUEST_TIMEOUT_MS, _client, generate_json


class Response(BaseModel):
    answer: str


class ModelDiagnosticsTests(unittest.TestCase):
    def tearDown(self):
        _client.cache_clear()

    def call_model(self, failure=None, text=None, model="gemini-3.8-flash"):
        model_api = Mock()
        model_api.generate_content.side_effect = failure
        model_api.generate_content.return_value = SimpleNamespace(text=text)
        with patch("dhaga_os.llm._client", return_value=SimpleNamespace(models=model_api)):
            return generate_json(model=model, prompt="PRIVATE_CUSTOMER_TEXT", response_model=Response, temperature=0.0)

    def test_provider_failure_categories_are_useful_and_logs_contain_no_private_text(self):
        for code, status, expected_category, message_fragment in (
            (401, "UNAUTHENTICATED", "authentication", "credentials"),
            (403, "PERMISSION_DENIED", "permission", "denied access"),
            (404, "NOT_FOUND", "model_unavailable", "model is unavailable"),
            (429, "RESOURCE_EXHAUSTED", "quota", "usage limit"),
            (400, "INVALID_ARGUMENT", "invalid_request", "rejected"),
            (503, "UNAVAILABLE", "provider_failure", "temporarily unavailable"),
        ):
            error_class = errors.ClientError if code < 500 else errors.ServerError
            failure = error_class(code, {"error": {"status": status, "message": "PRIVATE_CUSTOMER_TEXT SECRET_KEY PRIVATE_RESPONSE", "details": []}})
            with self.subTest(code=code), self.assertLogs("dhaga_os.llm", level="WARNING") as captured:
                with self.assertRaises(ModelUnavailable) as raised:
                    self.call_model(failure)
            self.assertIn(message_fragment, str(raised.exception))
            self.assertIn("Local checks", str(raised.exception))
            logged = json.loads(captured.records[0].getMessage())
            self.assertEqual(logged["category"], expected_category)
            self.assertEqual(logged["provider_code"], code)
            self.assertEqual(logged["provider_status"], status)
            self.assertEqual(logged["model"], "gemini-3.8-flash")
            for secret in ("PRIVATE_CUSTOMER_TEXT", "SECRET_KEY", "PRIVATE_RESPONSE"):
                self.assertNotIn(secret, str(raised.exception))
                self.assertNotIn(secret, str(captured.output))
            self.assertIsNone(captured.records[0].exc_info)

    def test_api_key_invalid_reason_is_allowlisted_even_when_provider_returns_400(self):
        failure = errors.ClientError(400, {"error": {"status": "INVALID_ARGUMENT", "message": "SECRET_KEY", "details": [{"reason": "API_KEY_INVALID", "metadata": {"secret": "SECRET_KEY"}}]}})
        with self.assertLogs("dhaga_os.llm", level="WARNING") as captured, self.assertRaisesRegex(ModelUnavailable, "credentials"):
            self.call_model(failure)
        logged = json.loads(captured.records[0].getMessage())
        self.assertEqual(logged["provider_reason"], "API_KEY_INVALID")
        self.assertNotIn("SECRET_KEY", str(captured.output))

    def test_timeout_becomes_visible_fallback_with_safe_log(self):
        with self.assertLogs("dhaga_os.llm", level="WARNING") as captured, self.assertRaisesRegex(ModelUnavailable, "too long"):
            self.call_model(TimeoutError("PRIVATE_CUSTOMER_TEXT"))
        self.assertEqual(json.loads(captured.records[0].getMessage())["category"], "timeout")
        self.assertNotIn("PRIVATE_CUSTOMER_TEXT", str(captured.output))

    def test_invalid_response_does_not_log_model_response_or_validation_errors(self):
        with self.assertLogs("dhaga_os.llm", level="WARNING") as captured, self.assertRaisesRegex(ModelUnavailable, "format check"):
            self.call_model(text='{"private_response": "PRIVATE_RESPONSE"}')
        self.assertEqual(json.loads(captured.records[0].getMessage())["category"], "invalid_response")
        self.assertNotIn("PRIVATE_RESPONSE", str(captured.output))

    def test_empty_response_is_a_diagnosable_failure(self):
        with self.assertLogs("dhaga_os.llm", level="WARNING") as captured, self.assertRaisesRegex(ModelUnavailable, "no usable text"):
            self.call_model(text="")
        self.assertEqual(json.loads(captured.records[0].getMessage())["category"], "empty_response")

    def test_unrecognized_provider_metadata_and_model_config_are_not_logged(self):
        failure = errors.ClientError(400, {"error": {"status": "SECRET_KEY", "message": "PRIVATE_CUSTOMER_TEXT", "details": [{"reason": "PRIVATE_CUSTOMER_TEXT"}, {"reason": ["malformed"]}]}})
        with self.assertLogs("dhaga_os.llm", level="WARNING") as captured, self.assertRaises(ModelUnavailable):
            self.call_model(failure, model="SECRET_KEY\nPRIVATE_CUSTOMER_TEXT")
        logged = json.loads(captured.records[0].getMessage())
        self.assertEqual(logged["model"], "configured-model")
        self.assertIsNone(logged["provider_status"])
        self.assertIsNone(logged["provider_reason"])
        self.assertNotIn("SECRET_KEY", str(captured.output))
        self.assertNotIn("PRIVATE_CUSTOMER_TEXT", str(captured.output))

    def test_client_has_explicit_request_timeout_and_no_automatic_retries(self):
        _client.cache_clear()
        with patch.dict(os.environ, {"MODEL_MODE": "live", "GEMINI_API_KEY": "test"}), patch("google.genai.Client") as client:
            _client()
        self.assertEqual(client.call_args.kwargs["http_options"], {"timeout": REQUEST_TIMEOUT_MS, "retry_options": {"attempts": 1}})
        self.assertLessEqual(REQUEST_TIMEOUT_MS, 30_000)

    def test_valid_structured_output_still_returns_the_requested_model(self):
        response = self.call_model(text='{"answer": "Valid answer"}')
        self.assertEqual(response.answer, "Valid answer")


if __name__ == "__main__":
    unittest.main()
