from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from dhaga_os.config import get_settings

T = TypeVar("T", bound=BaseModel)
LOGGER = logging.getLogger(__name__)
REQUEST_TIMEOUT_MS = 20_000
FALLBACK_NOTICE = " Local checks or example text are being used instead."
PROVIDER_STATUSES = {
    "INVALID_ARGUMENT", "UNAUTHENTICATED", "PERMISSION_DENIED", "NOT_FOUND",
    "RESOURCE_EXHAUSTED", "DEADLINE_EXCEEDED", "INTERNAL", "UNAVAILABLE",
    "FAILED_PRECONDITION", "CANCELLED", "UNKNOWN", "OUT_OF_RANGE", "UNIMPLEMENTED",
}
PROVIDER_REASONS = {
    "API_KEY_INVALID", "API_KEY_EXPIRED", "API_KEY_SERVICE_BLOCKED", "API_KEY_HTTP_REFERRER_BLOCKED",
    "API_KEY_IP_ADDRESS_BLOCKED", "CONSUMER_INVALID", "BILLING_DISABLED", "SERVICE_DISABLED",
    "RATE_LIMIT_EXCEEDED", "QUOTA_EXCEEDED", "ACCESS_TOKEN_EXPIRED",
}
SAFE_ERROR_TYPES = {
    "APIError", "ClientError", "ServerError", "ReadTimeout", "ConnectTimeout", "WriteTimeout",
    "PoolTimeout", "TimeoutException", "TimeoutError", "ConnectError", "NetworkError",
    "ConnectionError", "ValidationError", "ValueError", "TypeError", "ImportError", "ModuleNotFoundError",
}


class ModelUnavailable(RuntimeError):
    """Raised when a configured model cannot return a valid response."""


def _provider_reason(exc: Exception) -> str | None:
    details = getattr(exc, "details", None)
    if not isinstance(details, dict):
        return None
    error = details.get("error", details)
    if not isinstance(error, dict):
        return None
    items = error.get("details", [])
    if not isinstance(items, list):
        return None
    for item in items:
        reason = item.get("reason") if isinstance(item, dict) else None
        if isinstance(reason, str) and reason in PROVIDER_REASONS:
            return reason
    return None


def _failure_details(exc: Exception) -> dict[str, Any]:
    code = getattr(exc, "code", None)
    code = code if isinstance(code, int) and 100 <= code <= 599 else None
    status = getattr(exc, "status", None)
    status = status if isinstance(status, str) and status in PROVIDER_STATUSES else None
    reason = _provider_reason(exc)
    if reason in {"API_KEY_INVALID", "API_KEY_EXPIRED", "ACCESS_TOKEN_EXPIRED"} or code == 401:
        category = "authentication"
    elif code == 403:
        category = "permission"
    elif code == 404:
        category = "model_unavailable"
    elif code == 429:
        category = "quota"
    elif code in {408, 504} or status == "DEADLINE_EXCEEDED" or isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.casefold():
        category = "timeout"
    elif isinstance(exc, ValidationError):
        category = "invalid_response"
    elif code == 400:
        category = "invalid_request"
    elif code and code >= 500:
        category = "provider_failure"
    elif type(exc).__name__ in {"ConnectError", "NetworkError", "ConnectionError"}:
        category = "connection"
    else:
        category = "unexpected_failure"
    return {
        "category": category,
        "provider_code": code,
        "provider_status": status,
        "provider_reason": reason,
        "error_type": type(exc).__name__ if type(exc).__name__ in SAFE_ERROR_TYPES else "UnexpectedError",
    }


def _report_failure(model: str, details: dict[str, Any]) -> None:
    # Provider exception strings, tracebacks and validation errors can contain
    # prompts, responses or credentials. Emit only this allowlisted metadata.
    safe_model = model if isinstance(model, str) and re.fullmatch(r"(?:models/)?gemini-[a-zA-Z0-9._-]{1,100}", model) else "configured-model"
    LOGGER.warning(json.dumps({"event": "gemini_request_failed", "model": safe_model, **details}, sort_keys=True))


def _failure_message(category: str) -> str:
    messages = {
        "authentication": "AI credentials were rejected. Ask your administrator to check the AI key.",
        "permission": "The AI service denied access. Ask your administrator to check the AI permissions and billing.",
        "model_unavailable": "The configured AI model is unavailable for this account. Ask your administrator to check the AI settings.",
        "quota": "The AI service has reached its request or usage limit. Try again later.",
        "timeout": "The AI service took too long to respond. Try again later.",
        "invalid_request": "The AI service rejected this step's request. Your administrator can check the service diagnostics.",
        "invalid_response": "The AI service returned text that could not pass the required format check.",
        "empty_response": "The AI service returned no usable text for this step.",
        "provider_failure": "The AI service is temporarily unavailable. Try again later.",
        "connection": "The AI service could not be reached. Try again later.",
    }
    return messages.get(category, "The AI service could not complete this step.") + FALLBACK_NOTICE


@lru_cache(maxsize=1)
def _client():
    settings = get_settings()
    if not settings.live_models_enabled:
        raise ModelUnavailable("AI help is not available. Local checks and example replies are being used.")
    try:
        from google import genai

        return genai.Client(
            api_key=settings.gemini_api_key,
            http_options={"timeout": REQUEST_TIMEOUT_MS, "retry_options": {"attempts": 1}},
        )
    except Exception as exc:  # pragma: no cover - import and provider failures vary by environment
        raise ModelUnavailable("Gemini could not be reached. Local checks and example replies are being used.") from exc


def generate_json(
    *, model: str, prompt: str, response_model: type[T], temperature: float
) -> T:
    """Call Gemini with a JSON Schema boundary and validate it again with Pydantic."""
    try:
        client = _client()
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_json_schema": response_model.model_json_schema(),
                "temperature": temperature,
            },
        )
        if not response.text:
            _report_failure(model, {"category": "empty_response", "provider_code": None})
            raise ModelUnavailable(_failure_message("empty_response"))
        return response_model.model_validate_json(response.text)
    except ModelUnavailable as exc:
        if exc.__cause__:
            details = _failure_details(exc.__cause__)
            _report_failure(model, details)
            raise ModelUnavailable(_failure_message(details["category"])) from exc
        raise
    except Exception as exc:  # provider exceptions must become visible workflow failures
        details = _failure_details(exc)
        _report_failure(model, details)
        raise ModelUnavailable(_failure_message(details["category"])) from exc
