from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from dhaga_os.config import ROOT_DIR, get_settings
from dhaga_os.llm import ModelUnavailable, generate_json
from dhaga_os.models import CXAudit, CXDraft, ParsedCustomerQuery, ParsedCustomerQueryBatch, Sentiment, TicketIntent
from dhaga_os.policy_rag import retrieve_policies


def _load_orders() -> list[dict[str, Any]]:
    return json.loads((ROOT_DIR / "data" / "mock_orders.json").read_text(encoding="utf-8"))


ORDERS = _load_orders()


def _deterministic_parse(text: str) -> ParsedCustomerQuery:
    order_match = re.search(r"\b(?:order\s*(?:id|no|number)?\s*[:#-]?\s*)?(\d{5,8})\b", text, flags=re.I)
    phone_match = re.search(r"(?:\+?91[ -]?)?[6-9]\d{9}\b", text)
    lowered = text.casefold()
    denied_cancellation = bool(
        re.search(r"\b(?:do not|don't|dont|not)\s+(?:want\s+to\s+)?cancel\b", lowered)
        or re.search(r"\b(?:cancel(?:led|ed)?|radd)\s+(?:nahi|nahin|not)\s+(?:hua|huwa|kiya|yet|still)\b", lowered)
    )
    direct_cancellation_request = any(
        phrase in lowered
        for phrase in (
            "cancel kar do", "cancel kardo", "please cancel", "cancel it", "cancel my order",
            "radd kar do", "radd kardo", "nahi chahiye", "mat bhejo",
        )
    )
    cancellation_words = any(word in lowered for word in ("cancel", "cancellation", "radd"))
    if any(word in lowered for word in ("fraud", "legal", "manager", "complaint", "chargeback")):
        intent = TicketIntent.ESCALATION
    elif not denied_cancellation and (direct_cancellation_request or cancellation_words):
        intent = TicketIntent.CANCELLATION
    elif any(word in lowered for word in ("return", "exchange", "refund", "wapas", "badal", "size")):
        intent = TicketIntent.RETURN_REQUEST
    elif any(word in lowered for word in ("where", "track", "tracking", "deliver", "order", "kahan", "kab", "mila", "nahi mila", "parcel")):
        intent = TicketIntent.WISMO
    else:
        intent = TicketIntent.OTHER
    if any(word in lowered for word in ("angry", "furious", "bakwas", "scam", "terrible", "complaint")):
        sentiment = Sentiment.ANGRY
    elif any(word in lowered for word in ("please", "kindly", "thank", "thanks", "kripya")):
        sentiment = Sentiment.POLITE
    elif any(word in lowered for word in ("anxious", "worried", "late", "shaadi", "tension", "abhi tak")):
        sentiment = Sentiment.ANXIOUS
    else:
        sentiment = Sentiment.NEUTRAL
    if re.search(r"[\u0900-\u097f]", text):
        language = "Hindi"
    elif re.search(r"\b(kahan|kab|mera|mujhe|bhaiya|nahi|hai|kardo|abhi|tak|chahiye|please|kripya)\b", lowered):
        language = "Hinglish"
    else:
        language = "English"
    return ParsedCustomerQuery(
        detected_intent=intent,
        order_id=order_match.group(1) if order_match else None,
        phone_number=phone_match.group(0) if phone_match else None,
        sentiment=sentiment,
        language=language,
    )


def _parse(text: str) -> tuple[ParsedCustomerQuery, list[str]]:
    settings = get_settings()
    baseline = _deterministic_parse(text)
    warnings: list[str] = []
    if settings.live_models_enabled:
        try:
            parsed = generate_json(
                model=settings.gemini_fast_model,
                temperature=0.0,
                response_model=ParsedCustomerQueryBatch,
                prompt=(
                    "Classify the customer ticket intent and extract an order ID and phone number if present. "
                    "Input may be Hinglish or Romanized Hindi. Never invent identifiers. Keep the output "
                    "inside the required structured schema. Ticket:\n" + text
                ),
            ).result
            # Regex is authoritative for literal identifiers when the model omitted them.
            parsed.order_id = parsed.order_id or baseline.order_id
            parsed.phone_number = parsed.phone_number or baseline.phone_number
            return parsed, warnings
        except ModelUnavailable as exc:
            warnings.append(str(exc))
    return baseline, warnings


def _today_india() -> date:
    from datetime import datetime

    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


def _lookup_order(order_id: str | None, phone_number: str | None) -> dict[str, Any] | None:
    if order_id:
        for order in ORDERS:
            if order["order_id"] == order_id:
                return dict(order)
    if phone_number:
        clean_phone = re.sub(r"\D", "", phone_number)[-10:]
        matching_orders = [
            order
            for order in ORDERS
            if order.get("phone_number")
            and re.sub(r"\D", "", order.get("phone_number", ""))[-10:] == clean_phone
        ]
        if matching_orders:
            active = [
                order
                for order in matching_orders
                if order.get("current_status", "").casefold() not in {"delivered", "rto initiated"}
            ]
            candidate = max(active or matching_orders, key=lambda item: item.get("shipped_at", ""))
            return dict(candidate)
    return None


def _carrier_facts(order: dict[str, Any]) -> dict[str, Any]:
    result = dict(order)
    for field in (
        "order_id", "carrier_name", "current_status", "current_location", "tracking_url",
        "destination_city", "payment_mode", "awb", "shipped_at", "promised_delivery_date",
    ):
        result[field] = str(result.get(field) or "").strip()
    result["days_in_transit"] = 0
    record_ok = all(
        str(result.get(field) or "").strip()
        for field in ("order_id", "carrier_name", "current_status", "current_location", "tracking_url")
    )
    result["carrier_name"] = result.get("carrier_name") or "Unknown carrier"
    result["current_status"] = result.get("current_status") or "Unavailable"
    result["current_location"] = result.get("current_location") or "Unavailable"
    result["tracking_url"] = result.get("tracking_url") or ""
    if order.get("shipped_at"):
        try:
            shipped = date.fromisoformat(order["shipped_at"])
            result["days_in_transit"] = max((_today_india() - shipped).days, 0)
        except (TypeError, ValueError):
            record_ok = False
    promised_date = result.get("promised_delivery_date") or ""
    if promised_date:
        try:
            date.fromisoformat(promised_date)
        except (TypeError, ValueError):
            result["promised_delivery_date"] = ""
            record_ok = False
    result["is_delayed"] = (
        result["days_in_transit"] > 4
        and str(result.get("current_status") or "").casefold() not in {"delivered", "rto initiated", "cancelled", "canceled"}
    )
    if order.get("sync_status") != "OK" or not record_ok:
        result["sync_status"] = "SYNC_FAILED"
    return result


def _fallback_reply(
    parsed: ParsedCustomerQuery, facts: dict[str, Any], policies: list[dict[str, Any]]
) -> CXDraft:
    policy_ids = ", ".join(policy["policy_id"] for policy in policies)
    if (
        parsed.detected_intent == TicketIntent.CANCELLATION
        and facts.get("current_status", "").casefold() == "out for delivery"
        and facts.get("payment_mode", "").casefold() == "cod"
    ):
        reply = (
            f"Namaste, aapka order {facts['order_id']} abhi delivery ke liye nikla hua hai. "
            "Is stage par system se cancel nahi ho paayega. Agar aap parcel nahi lena chahte, "
            "to delivery partner ko doorstep par bata sakte hain."
        )
    elif parsed.detected_intent == TicketIntent.RETURN_REQUEST:
        reply = (
            "Namaste, return ya exchange request ke liye Dhaga & Co. app ke Returns section mein "
            "eligibility check karke request shuru karein. Refund return inspection ke baad process hota hai."
        )
    elif facts.get("is_delayed"):
        reply = (
            f"Namaste, delay ke liye humein khed hai. Aapka order {facts['order_id']} "
            f"{facts['current_status'].lower()} hai aur latest scan {facts['current_location']} par hai. "
        )
        if facts.get("promised_delivery_date"):
            reply += f"Tracking mein expected delivery {facts['promised_delivery_date']} dikh rahi hai. "
        if facts.get("tracking_url"):
            reply += f"Tracking link: {facts['tracking_url']} "
        reply += "Humne isse follow-up ke liye flag kiya hai."
    else:
        reply = (
            f"Namaste, aapka order {facts['order_id']} {facts['current_status'].lower()} hai. "
            f"{facts['carrier_name']} ka latest update {facts['current_location']} se hai. "
        )
        if facts.get("promised_delivery_date"):
            reply += f"Tracking mein expected delivery {facts['promised_delivery_date']} dikh rahi hai. "
        if facts.get("tracking_url"):
            reply += f"Tracking link: {facts['tracking_url']} "
        reply += "Agar status update na ho, humse dobara sampark karein."
    return CXDraft(
        draft_reply_hinglish=reply,
        carrier_status_summary=(
            f"{facts['carrier_name']} · {facts['current_status']} · {facts['current_location']} · "
            f"ETA {facts.get('promised_delivery_date') or 'not available'}"
        ),
        policy_reference=policy_ids,
        requires_human_escalation=bool(facts.get("is_delayed")),
        escalation_reason="Transit exceeds four days; follow-up recommended." if facts.get("is_delayed") else "",
    )


MONTHS = {
    name.casefold(): number
    for number, names in enumerate(
        (
            ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
            ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
            ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
            ("dec", "december"),
        ),
        start=1,
    )
    for name in names
}


def _mentioned_dates(reply: str) -> tuple[list[date], bool]:
    """Extract common customer-facing date formats; return dates and whether one was malformed."""
    matches: list[tuple[int, int, date]] = []
    malformed = False

    def add_match(start: int, end: int, parts: tuple[int, int, int]) -> None:
        nonlocal malformed
        try:
            matches.append((start, end, date(parts[0], parts[1], parts[2])))
        except ValueError:
            malformed = True

    patterns = [
        (re.compile(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b"), lambda g: (int(g[0]), int(g[1]), int(g[2]))),
        (re.compile(r"\b(\d{1,2})[/. -](\d{1,2})[/. -](20\d{2})\b"), lambda g: (int(g[2]), int(g[1]), int(g[0]))),
        (
            re.compile(r"\b(\d{1,2})\s+(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?[,]?\s+(20\d{2})\b", re.I),
            lambda g: (int(g[2]), MONTHS[g[1].casefold().rstrip(".")[:3]], int(g[0])),
        ),
        (
            re.compile(r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2})[,]?\s+(20\d{2})\b", re.I),
            lambda g: (int(g[2]), MONTHS[g[0].casefold()[:3]], int(g[1])),
        ),
    ]
    for pattern, convert in patterns:
        for match in pattern.finditer(reply):
            if any(match.start() < end and match.end() > start for start, end, _ in matches):
                continue
            add_match(match.start(), match.end(), convert(match.groups()))
    return [value for _, _, value in sorted(matches)], malformed


def _deterministic_reply_check(reply: str, facts: dict[str, Any]) -> tuple[bool, str]:
    if not facts:
        if _mentioned_dates(reply)[0] or re.search(r"\b(?:Delhivery|Shiprocket|Ekart|delivered|in transit|out for delivery)\b", reply, re.I):
            return False, "There is no tracking record yet. Keep this message to a request for the order ID or registered phone."
        return True, "This reply only asks the customer for the missing order details."
    if facts.get("sync_status") != "OK":
        return False, "Carrier sync failed; response drafting must remain blocked."
    expected_date = facts.get("promised_delivery_date") or ""
    mentioned_dates, malformed_dates = _mentioned_dates(reply)
    if malformed_dates:
        return False, "Draft contains a date that could not be checked. Use the delivery date shown in tracking."
    if mentioned_dates and (not expected_date or any(value.isoformat() != expected_date for value in mentioned_dates)):
        return False, "Draft contains a date that does not match the carrier record."
    mentioned_carriers = re.findall(r"\b(Delhivery|Shiprocket|Ekart)\b", reply, flags=re.I)
    if any(value.casefold() != facts["carrier_name"].casefold() for value in mentioned_carriers):
        return False, "Draft names a different carrier from the tracking record."
    if expected_date and re.search(r"\b(?:tomorrow|today|kal|aaj)\b", reply, re.I):
        relative_date = _today_india() + timedelta(days=1) if re.search(r"\b(?:tomorrow|kal)\b", reply, re.I) else _today_india()
        if relative_date.isoformat() != expected_date:
            return False, "Draft uses a relative date that does not match the carrier record. Use the exact date instead."
    if not expected_date and re.search(r"\b(?:tomorrow|today|kal|aaj|\d+\s+days?)\b", reply, re.I):
        return False, "The carrier record has no delivery date. Remove date promises from the draft."
    return True, "Carrier name and any delivery date in the reply match the tracking record."


def process_customer_ticket(
    text: str, order_id_override: str = "", phone_override: str = ""
) -> dict[str, Any]:
    settings = get_settings()
    case_id = str(uuid4())
    warnings: list[str] = []
    text = text if isinstance(text, str) else ""
    order_id_override = str(order_id_override or "")
    phone_override = str(phone_override or "")
    if not text.strip():
        return {
            "case_id": case_id,
            "ticket_text": text,
            "status": "blocked",
            "error": "Enter the customer's message to start triage.",
            "model_warnings": warnings,
        }

    parsed, parse_warnings = _parse(text)
    warnings.extend(parse_warnings)
    parsed.order_id = order_id_override.strip() or parsed.order_id
    parsed.phone_number = phone_override.strip() or parsed.phone_number
    order = _lookup_order(parsed.order_id, parsed.phone_number)
    base = {
        "case_id": case_id,
        "ticket_text": text,
        "parsed_query": parsed.model_dump(mode="json"),
        "model_mode": "live" if settings.live_models_enabled else "demo-rule-based",
        "model_warnings": warnings,
        "policy_references": [],
        "carrier_facts": None,
        "draft_reply": "",
        "factual_verification_passed": None,
        "verification_notes": "",
        "requires_human_escalation": False,
        "escalation_reason": "",
    }

    if not parsed.order_id and not parsed.phone_number:
        base.update(
            status="needs_identifier",
            error="Order ID or registered phone number is missing. Ask the customer for one before lookup.",
            draft_reply="Namaste, aapka order check karne ke liye order ID ya registered phone number share kar dijiye.",
            order_id=None,
        )
        return base

    if parsed.detected_intent in {TicketIntent.ESCALATION, TicketIntent.OTHER}:
        base.update(
            status="needs_review",
            error="This message is outside routine WISMO triage and needs an agent to review it.",
            requires_human_escalation=True,
            escalation_reason="Intent is not a routine order-status request.",
            order_id=parsed.order_id,
        )
        return base

    if order is None:
        base.update(
            status="not_found",
            error="No matching order exists in the demo tracking fixtures. Verify the identifier in the courier portal.",
            order_id=parsed.order_id,
        )
        return base

    facts = _carrier_facts(order)
    base["order_id"] = facts["order_id"]
    base["carrier_facts"] = facts
    policies = retrieve_policies(
        " ".join([text, parsed.detected_intent.value, facts["current_status"], facts["destination_city"]]),
        limit=2,
    )
    base["policy_references"] = policies

    if facts["sync_status"] != "OK":
        base.update(
            status="sync_failed",
            error=f"3PL sync failure: {facts['carrier_name']} lookup needs a manual courier-portal check.",
            requires_human_escalation=True,
            escalation_reason="Carrier tracking fixture is unavailable; no customer reply was drafted.",
        )
        return base

    if facts.get("current_status", "").casefold() == "delivered" and re.search(
        r"\b(?:not received|haven't received|have not received|didn't get|did not get|nahi mila|nahi mila hai)\b",
        text.casefold(),
    ):
        base.update(
            status="needs_review",
            error="Tracking says delivered, but the customer says the parcel did not arrive. Check the delivery proof with the courier.",
            requires_human_escalation=True,
            escalation_reason="Delivered scan disputed by the customer; confirm proof of delivery before replying.",
        )
        return base

    if parsed.detected_intent == TicketIntent.CANCELLATION and not (
        facts.get("current_status", "").casefold() == "out for delivery"
        and facts.get("payment_mode", "").casefold() == "cod"
    ):
        base.update(
            status="needs_review",
            error="Check the order system for cancellation options. No cancellation has been made.",
            requires_human_escalation=True,
            escalation_reason="The demo policy only confirms doorstep refusal for COD orders already out for delivery.",
        )
        return base

    draft: CXDraft
    if settings.live_models_enabled:
        prompt_data = {
            "customer_message": text,
            "parsed_intent": parsed.model_dump(mode="json"),
            "verified_carrier_facts": facts,
            "retrieved_policy_clauses": [{"id": p["policy_id"], "text": p["text"]} for p in policies],
        }
        try:
            draft = generate_json(
                model=settings.gemini_creative_model,
                temperature=0.4,
                response_model=CXDraft,
                prompt=(
                "Draft an empathetic, concise Hinglish reply. Use only verified carrier facts and supplied "
                "policy clauses. Do not promise refunds, dates, compensation, or actions absent from context. "
                "If a promised delivery date exists, include that exact ISO date and the tracking URL. "
                "If the shipment is delayed, apologize and flag human follow-up. Context:\n"
                    + json.dumps(prompt_data, ensure_ascii=False)
                ),
            )
        except ModelUnavailable as exc:
            warnings.append(str(exc))
            draft = _fallback_reply(parsed, facts, policies)
    else:
        draft = _fallback_reply(parsed, facts, policies)

    passed, notes = _deterministic_reply_check(draft.draft_reply_hinglish, facts)
    if settings.live_models_enabled:
        try:
            audit = generate_json(
                model=settings.gemini_fast_model,
                temperature=0.1,
                response_model=CXAudit,
                prompt=(
                    "Check this draft only for factual consistency with the carrier record. Verify carrier, "
                    "status, location and delivery date; fail if any are unsupported or conflict. Return the "
                    "required structured result. Context:\n"
                    + json.dumps({"carrier_facts": facts, "draft": draft.model_dump(mode="json")}, ensure_ascii=False)
                ),
            )
            passed = passed and audit.factual_verification_passed
            notes = "; ".join(filter(None, [notes, audit.notes]))
        except ModelUnavailable as exc:
            warnings.append(str(exc))
            passed = False
            notes += " Model audit unavailable; manual review required."

    base.update(
        status="draft_ready" if passed else "needs_review",
        draft_reply=draft.draft_reply_hinglish,
        carrier_status_summary=draft.carrier_status_summary,
        factual_verification_passed=passed,
        verification_notes=notes,
        requires_human_escalation=draft.requires_human_escalation or facts["is_delayed"],
        escalation_reason=draft.escalation_reason or ("Transit exceeds four days; human follow-up required." if facts["is_delayed"] else ""),
        model_warnings=warnings,
    )
    return base


def demo_order_ids() -> list[str]:
    return [order["order_id"] for order in ORDERS]


def demo_phone_numbers() -> list[str]:
    return sorted({order["phone_number"] for order in ORDERS if order.get("phone_number")})


def demo_tickets() -> list[dict[str, str]]:
    return json.loads((ROOT_DIR / "data" / "demo_tickets.json").read_text(encoding="utf-8"))
