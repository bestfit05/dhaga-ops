from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from dhaga_os.config import ROOT_DIR


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def _load_policies() -> list[dict[str, Any]]:
    return json.loads((ROOT_DIR / "data" / "policies.json").read_text(encoding="utf-8"))


POLICIES = _load_policies()


def _vector(document: str) -> Counter[str]:
    return Counter(_tokens(document))


def _cosine(left: Counter[str], right: Counter[str]) -> float:
    shared = left.keys() & right.keys()
    numerator = sum(left[token] * right[token] for token in shared)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


def retrieve_policies(query: str, limit: int = 2) -> list[dict[str, Any]]:
    """Small local TF vectors keep policy lookup deterministic and database-free."""
    query_vector = _vector(query)
    results = []
    for policy in POLICIES:
        content = " ".join([policy["title"], policy["text"], *policy.get("keywords", [])])
        score = _cosine(query_vector, _vector(content))
        if score > 0:
            results.append({**policy, "score": round(score, 3)})
    results.sort(key=lambda policy: policy["score"], reverse=True)
    return results[:limit]
