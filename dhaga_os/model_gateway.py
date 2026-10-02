"""Rules-first routing for optional structured model requests.

Routine checks stay in Python. Gemini is reserved for unresolved color names,
meaningful free-text attribute extraction, listing copy, uncertain intent, and
customer replies that benefit from more careful language.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, TypeVar

from pydantic import BaseModel

from dhaga_os.config import get_settings
from dhaga_os.llm import generate_json

T = TypeVar("T", bound=BaseModel)


class ModelTask(StrEnum):
    COLOR_SUGGESTION = "color_suggestion"
    ATTRIBUTE_EXTRACTION = "attribute_extraction"
    LISTING_COPY = "listing_copy"
    LISTING_REVIEW = "listing_review"
    MESSAGE_INTENT = "message_intent"
    CUSTOMER_REPLY = "customer_reply"
    REPLY_REVIEW = "reply_review"


def should_use_model(
    task: ModelTask | str,
    context: dict[str, Any],
    *,
    live_enabled: bool | None = None,
) -> bool:
    """Return whether this task benefits from Gemini after local checks."""
    if live_enabled is None:
        live_enabled = get_settings().live_models_enabled
    if not live_enabled:
        return False

    task = ModelTask(task)
    if task is ModelTask.COLOR_SUGGESTION:
        return bool(context.get("unknown_color"))
    if task is ModelTask.ATTRIBUTE_EXTRACTION:
        return bool(context.get("missing_fields") and context.get("useful_free_text"))
    if task is ModelTask.LISTING_COPY:
        return bool(context.get("ready_products"))
    if task is ModelTask.LISTING_REVIEW:
        return bool(context.get("model_written_products"))
    if task is ModelTask.MESSAGE_INTENT:
        return bool(context.get("unclear_intent") and context.get("message"))
    if task is ModelTask.CUSTOMER_REPLY:
        return bool(
            context.get("verified_order")
            and context.get("benefits_careful_wording")
        )
    if task is ModelTask.REPLY_REVIEW:
        return bool(context.get("model_written_reply"))
    return False


def generate_for_task(
    task: ModelTask | str,
    *,
    context: dict[str, Any],
    model: str,
    prompt: str,
    response_model: type[T],
    temperature: float,
) -> T | None:
    """Call Gemini only when the gateway routes this task to a model."""
    if not should_use_model(task, context):
        return None
    return generate_json(
        model=model,
        prompt=prompt,
        response_model=response_model,
        temperature=temperature,
    )
