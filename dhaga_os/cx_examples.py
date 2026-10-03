"""Synthetic intent and handling examples for runtime prompts and regression.

These examples do not train model weights and contain no authoritative order
facts or merchant policy. The original messages remain available for a picker;
prompt patterns remove their numeric identifiers.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from functools import lru_cache
from typing import Any

from dhaga_os.config import ROOT_DIR


@lru_cache(maxsize=1)
def _source_examples() -> tuple[dict[str, Any], ...]:
    return tuple(json.loads((ROOT_DIR / "data" / "cx_examples.json").read_text(encoding="utf-8")))


def load_cx_examples() -> list[dict[str, Any]]:
    """Return independent copies of the eight exact labeled synthetic messages."""
    return deepcopy(list(_source_examples()))


def _identifier_free_pattern(message: str) -> str:
    identifiers: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        value = match.group()
        identifiers.setdefault(value, f"<IDENTIFIER_{len(identifiers) + 1}>")
        return identifiers[value]

    # Distinct placeholders preserve the two-order conflict pattern without
    # giving the provider example identifiers it could reuse on a fresh ticket.
    return re.sub(r"\d+", replace, message)


def prompt_cx_examples() -> list[dict[str, str]]:
    """Return intent/handling patterns, omitting identifiers and route fixtures."""
    return [
        {
            "message_pattern": _identifier_free_pattern(example["message"]),
            "detected_intent": example["intent"],
            "handling_instruction": example["handling_instruction"],
        }
        for example in _source_examples()
    ]
