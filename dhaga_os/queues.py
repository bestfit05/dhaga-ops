"""Shared, local queue rules for operator lists and dashboard totals."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo

QUEUE_LABELS = {
    "all": "All customer messages",
    "pending": "Pending tickets",
    "high_risk": "Needs extra attention",
    "low_risk": "Routine pending tickets",
    "returns": "Pending returns and refunds",
    "ready": "Replies ready to review",
    "needs_order_details": "Needs order details",
    "approved": "Approved replies",
}
ATTENTION_STATUSES = {"needs_identifier", "not_found", "sync_failed", "blocked", "needs_review"}
ATTENTION_INTENTS = {"CANCELLATION", "CANCEL", "DISPUTE", "ESCALATION", "OTHER", "RETURN_REQUEST"}
TERMINAL_SHIPMENT_STATUSES = {"delivered", "rto initiated", "cancelled", "canceled", "returned to sender"}
RETURN_WORDS = re.compile(r"\b(?:returns?|refunds?|exchanges?|wapas|badal)\b", re.I)
PRODUCT_CHANGE_CONTEXT = re.compile(r"\b(?:product|item|size|sizes|exchange|kurta|kurti|dress|clothes|kapda|kapde)\b", re.I)
COORDINATED_REQUESTS = re.compile(r"\s*(?:,\s*)?(?:(?:and|or|nor|ya)\s+)?(?:(?:a|an|any|the)\s+)?", re.I)
DISPUTE_WORDS = re.compile(r"\b(?:fraud|chargeback|complaint|wrong item|damaged|missing item)\b", re.I)
NOT_RECEIVED = re.compile(r"\b(?:not received|haven't received|have not received|didn't get|did not get|nahi mila)\b", re.I)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _pending(case: dict[str, Any]) -> bool:
    return _text(case.get("status")) != "approved_for_handoff"


def _today() -> date:
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


def _order_number(case: dict[str, Any]) -> str:
    return _text(
        case.get("order_id") or _mapping(case.get("parsed_query")).get("order_id")
        or _mapping(case.get("carrier_facts")).get("order_id")
    )


def case_risk_reasons(case: dict[str, Any], *, today: date | None = None) -> list[str]:
    """Return attention reasons for a pending ticket; approved tickets have none.

    These are queue priorities, not a fraud score or a guarantee of safety.
    Carrier estimates are checked against the India calendar date each time.
    """
    if not _pending(case):
        return []
    reasons: list[str] = []
    parsed = _mapping(case.get("parsed_query"))
    facts = _mapping(case.get("carrier_facts"))
    status = _text(case.get("status"))
    if status in ATTENTION_STATUSES:
        reasons.append("This ticket needs missing details or a teammate's review.")
    if any(case.get(key) is True for key in ("requires_human_escalation", "requires_manual_review", "manual_review_required", "manual_review")):
        reasons.append("A teammate has been flagged to review or follow up.")
    if _text(parsed.get("sentiment")).upper() in {"ANGRY", "ANXIOUS"}:
        reasons.append("The customer sounds angry or worried.")
    if _text(parsed.get("detected_intent")).upper() in ATTENTION_INTENTS:
        reasons.append("This request needs an individual support decision.")
    ticket = _text(case.get("ticket_text"))
    if DISPUTE_WORDS.search(ticket) or (
        _text(facts.get("current_status")).casefold() == "delivered" and NOT_RECEIVED.search(ticket)
    ):
        reasons.append("The customer reports a complaint or disputed delivery.")
    if _order_number(case) and (
        not facts or _text(facts.get("sync_status")).upper() != "OK"
        or case.get("factual_verification_passed") is not True
    ):
        reasons.append("The order facts or reply have not passed verification.")
    if facts and _text(facts.get("current_status")).casefold() not in TERMINAL_SHIPMENT_STATUSES:
        expected = _text(facts.get("promised_delivery_date"))
        try:
            expected_date = date.fromisoformat(expected)
        except ValueError:
            reasons.append("The courier has no usable expected delivery date.")
        else:
            if expected_date < (today or _today()):
                reasons.append("The courier's expected delivery date has passed.")
        if facts.get("is_delayed") is True or facts.get("delivery_date_overdue") is True or facts.get("date_is_missing") is True:
            reasons.append("The saved courier update needs a delivery follow-up.")
    return reasons


def _return_request(case: dict[str, Any]) -> bool:
    ticket = _text(case.get("ticket_text"))
    mentions = list(RETURN_WORDS.finditer(ticket))
    groups: list[list[re.Match[str]]] = []
    for mention in mentions:
        if mention.group().casefold() == "badal":
            clause_before = re.split(r"[.!?;,]", ticket[:mention.start()])[-1]
            clause_after = re.split(r"[.!?;,]", ticket[mention.end():])[0]
            if not PRODUCT_CHANGE_CONTEXT.search(clause_before + " " + clause_after):
                # A delivery address or phone change is not an item exchange.
                continue
        if groups and COORDINATED_REQUESTS.fullmatch(ticket[groups[-1][-1].end():mention.start()]):
            groups[-1].append(mention)
        else:
            groups.append([mention])
    for group in groups:
        # Negation covers the entire coordinated object: 'no return or refund'.
        # A new request such as 'but please exchange' starts a separate group.
        prefix = re.split(r"[.!?;,]", ticket[:group[0].start()])[-1]
        suffix = ticket[group[-1].end():]
        negated_before = re.search(
            r"\b(?:no|not|don't|dont|never|nahi|nahin)\b\s*"
            r"(?:(?:a|an|any|the|need|needing|want|wanting|require|requiring|request|requesting|asking|for|interested|in|looking|to|get|issue|process|send|give|provide)\s+){0,4}$",
            prefix, re.I,
        )
        # 'No refund yet' and 'refund nahi mila' describe missing money;
        # they still need refund work, unlike an unwanted refund action.
        missing_refund = re.match(
            r"\s+(?:yet|received|credited|processed|issued|(?:has|was|is)\s+(?:been\s+)?(?:received|credited|processed|issued))\b",
            suffix, re.I,
        )
        if re.search(r"\bno\s*$", prefix, re.I) and missing_refund:
            negated_before = None
        negated_after = re.match(
            r"\s+(?:(?:nahi|nahin)\s+(?:chahiye|karna)|(?:is\s+)?not\s+(?:needed|required|wanted|requested))\b",
            suffix, re.I,
        )
        if not negated_before and not negated_after:
            return True
    if mentions:
        # An explicit negative request should not become refund work merely
        # because a broad intent classifier saw the word 'refund'.
        return False
    return _text(_mapping(case.get("parsed_query")).get("detected_intent")).upper() == "RETURN_REQUEST"


def _ready(case: dict[str, Any]) -> bool:
    return (
        _pending(case) and _text(case.get("status")) == "draft_ready"
        and bool(_text(case.get("draft_reply")))
        and case.get("factual_verification_passed") is True
        and _text(_mapping(case.get("carrier_facts")).get("sync_status")).upper() == "OK"
    )


def _needs_order_details(case: dict[str, Any]) -> bool:
    return _pending(case) and _text(case.get("status")) in {"needs_identifier", "not_found"}


def case_matches_queue(case: dict[str, Any], queue: str, *, today: date | None = None) -> bool:
    """Match a saved case to a queue using the same rules as the exact counts."""
    if queue not in QUEUE_LABELS:
        raise ValueError(f"Unknown customer message queue: {queue}")
    if queue == "all":
        return True
    if queue == "approved":
        return not _pending(case)
    if not _pending(case):
        return False
    if queue == "pending":
        return True
    if queue == "returns":
        return _return_request(case)
    if queue == "ready":
        return _ready(case)
    if queue == "needs_order_details":
        return _needs_order_details(case)
    high_risk = bool(case_risk_reasons(case, today=today))
    return high_risk if queue == "high_risk" else not high_risk


def support_queue_counts(cases: Iterable[dict[str, Any]], *, today: date | None = None) -> dict[str, int]:
    counts = {
        "pending_tickets": 0,
        "high_risk_tickets": 0,
        "low_risk_tickets": 0,
        "pending_return_requests": 0,
        "ready_replies": 0,
        "needs_order_details": 0,
    }
    current_date = today or _today()
    for case in cases:
        if not _pending(case):
            continue
        counts["pending_tickets"] += 1
        risk_key = "high_risk_tickets" if case_matches_queue(case, "high_risk", today=current_date) else "low_risk_tickets"
        counts[risk_key] += 1
        counts["pending_return_requests"] += int(case_matches_queue(case, "returns", today=current_date))
        counts["ready_replies"] += int(case_matches_queue(case, "ready", today=current_date))
        counts["needs_order_details"] += int(_needs_order_details(case))
    return counts
