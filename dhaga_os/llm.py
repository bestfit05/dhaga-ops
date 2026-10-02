from __future__ import annotations

from functools import lru_cache
from typing import TypeVar

from pydantic import BaseModel

from dhaga_os.config import get_settings

T = TypeVar("T", bound=BaseModel)


class ModelUnavailable(RuntimeError):
    """Raised when a configured model cannot return a valid response."""


@lru_cache(maxsize=1)
def _client():
    settings = get_settings()
    if not settings.live_models_enabled:
        raise ModelUnavailable("Live model mode is not enabled.")
    try:
        from google import genai

        return genai.Client(api_key=settings.gemini_api_key)
    except Exception as exc:  # pragma: no cover - import and provider failures vary by environment
        raise ModelUnavailable("Could not initialize the Gemini client.") from exc


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
            raise ModelUnavailable("The model returned an empty response.")
        return response_model.model_validate_json(response.text)
    except ModelUnavailable:
        raise
    except Exception as exc:  # provider exceptions must become visible workflow failures
        raise ModelUnavailable(
            "The model request failed or returned invalid structured output."
        ) from exc
