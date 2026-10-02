from __future__ import annotations

import os
import tempfile
import unittest
from copy import deepcopy
from datetime import date
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import func, select

from dhaga_os.db import (
    AuditEvent,
    ListingRecord,
    SupportCase,
    get_engine,
    get_session_factory,
    initialize_database,
    recent_support_cases,
    session_scope,
    workspace_counts,
)
from dhaga_os.models import Sentiment, TicketIntent
from dhaga_os.queues import QUEUE_LABELS, case_matches_queue, case_risk_reasons, support_queue_counts


TODAY = date(2026, 10, 3)
COUNT_QUEUES = {
    "pending_tickets": "pending",
    "high_risk_tickets": "high_risk",
    "low_risk_tickets": "low_risk",
    "pending_return_requests": "returns",
    "ready_replies": "ready",
    "needs_order_details": "needs_order_details",
}


def routine_case(**changes) -> dict:
    result = {
        "ticket_text": "Where is order 84922?",
        "parsed_query": {"detected_intent": "WISMO", "sentiment": "NEUTRAL", "order_id": "84922"},
        "order_id": "84922",
        "carrier_facts": {
            "order_id": "84922", "sync_status": "OK", "current_status": "In transit",
            "promised_delivery_date": "2026-10-04",
        },
        "status": "draft_ready",
        "draft_reply": "Order 84922 is in transit. Expected delivery 2026-10-04.",
        "factual_verification_passed": True,
        "requires_human_escalation": False,
    }
    result.update(changes)
    return result


def matches(case: dict, queue: str) -> bool:
    return case_matches_queue(case, queue, today=TODAY)


class CustomerQueueRules(unittest.TestCase):
    def test_pending_priorities_partition_and_approved_is_completed(self):
        cases = [
            routine_case(),
            routine_case(status="needs_review"),
            routine_case(factual_verification_passed=False),
            routine_case(status="approved_for_handoff", requires_human_escalation=True),
        ]
        for case in cases:
            with self.subTest(status=case["status"]):
                self.assertTrue(matches(case, "all"))
                pending = case["status"] != "approved_for_handoff"
                self.assertEqual(matches(case, "pending"), pending)
                self.assertEqual(matches(case, "approved"), not pending)
                self.assertEqual(int(matches(case, "high_risk")) + int(matches(case, "low_risk")), int(pending))
                if not pending:
                    self.assertEqual(case_risk_reasons(case, today=TODAY), [])
                    for queue in COUNT_QUEUES.values():
                        self.assertFalse(matches(case, queue))

    def test_each_attention_status_and_manual_flag_enters_high_priority(self):
        for status in ("needs_identifier", "not_found", "sync_failed", "blocked", "needs_review"):
            with self.subTest(status=status):
                self.assertTrue(matches(routine_case(status=status), "high_risk"))
        for flag in ("requires_human_escalation", "requires_manual_review", "manual_review_required", "manual_review"):
            with self.subTest(flag=flag):
                case = routine_case(**{flag: True})
                self.assertTrue(matches(case, "high_risk"))
                self.assertTrue(all(isinstance(reason, str) for reason in case_risk_reasons(case, today=TODAY)))

    def test_emotion_dispute_and_individual_decisions_need_attention(self):
        for sentiment in (Sentiment.ANGRY, Sentiment.ANXIOUS):
            with self.subTest(sentiment=sentiment):
                self.assertTrue(matches(routine_case(parsed_query={"detected_intent": TicketIntent.WISMO, "sentiment": sentiment}), "high_risk"))
        for intent in (TicketIntent.CANCELLATION, TicketIntent.ESCALATION, TicketIntent.OTHER, TicketIntent.RETURN_REQUEST, "DISPUTE"):
            with self.subTest(intent=intent):
                self.assertTrue(matches(routine_case(parsed_query={"detected_intent": intent}), "high_risk"))
        self.assertTrue(matches(routine_case(ticket_text="I received the wrong item."), "high_risk"))
        delivered = routine_case(ticket_text="It says delivered but I have not received it.")
        delivered["carrier_facts"]["current_status"] = "Delivered"
        self.assertTrue(matches(delivered, "high_risk"))

    def test_identified_order_requires_verified_facts(self):
        for facts, passed in ((None, True), ({"sync_status": "SYNC_FAILED"}, True), ({"sync_status": "OK"}, None), ({"sync_status": "OK"}, False)):
            with self.subTest(facts=facts, passed=passed):
                self.assertTrue(matches(routine_case(carrier_facts=facts, factual_verification_passed=passed), "high_risk"))
        facts_only = routine_case(order_id=None, parsed_query={}, factual_verification_passed=False)
        self.assertTrue(matches(facts_only, "high_risk"))

    def test_delivery_date_boundary_and_terminal_shipment_exemption(self):
        for expected, high in (("2026-10-02", True), ("2026-10-03", False), ("2026-10-04", False), ("", True), ("bad-date", True)):
            case = routine_case()
            case["carrier_facts"]["promised_delivery_date"] = expected
            with self.subTest(expected=expected):
                self.assertEqual(matches(case, "high_risk"), high)
        for status in ("Delivered", "RTO Initiated", "Cancelled", "Canceled", "Returned to sender"):
            case = routine_case()
            case["carrier_facts"].update(current_status=status, promised_delivery_date="2026-09-01", is_delayed=True)
            with self.subTest(status=status):
                self.assertTrue(matches(case, "low_risk"))
        case = routine_case()
        case["carrier_facts"]["is_delayed"] = True
        self.assertTrue(matches(case, "high_risk"))

    def test_refund_requests_include_missing_money_and_exclude_unwanted_action(self):
        positives = (
            "Please return this order.", "I want an exchange.", "Please issue a refund.",
            "I have not received my refund", "My refund has not arrived", "Refund nahi mila",
            "No refund yet", "No refund has been credited", "The order has not arrived I need refund",
            "I don't want a refund, please exchange the kurta.",
            "I do not want a return but please refund the payment.",
            "I have not received my return or refund confirmation.",
        )
        negatives = (
            "No refund please", "I do not want a refund", "I do not need a refund",
            "Please don't process a refund", "Refund nahi chahiye", "Refund not required",
            "No refund is needed", "The parcel is returning to sender", "The parcel returned yesterday",
            "I do not want a return or refund.", "I am not requesting a refund.",
            "No return, refund or exchange is needed.", "Return or refund not required.",
            "I am not asking for a return or a refund.",
        )
        for ticket in positives:
            with self.subTest(ticket=ticket):
                self.assertTrue(matches(routine_case(ticket_text=ticket), "returns"))
        for ticket in negatives:
            with self.subTest(ticket=ticket):
                self.assertFalse(matches(routine_case(ticket_text=ticket), "returns"))
        parsed_only = routine_case(ticket_text="Please help with this request", parsed_query={"detected_intent": "RETURN_REQUEST"})
        self.assertTrue(matches(parsed_only, "returns"))
        parsed_only["ticket_text"] = "I do not want a refund"
        self.assertFalse(matches(parsed_only, "returns"))

    def test_hindi_change_requires_product_context_and_excludes_contact_updates(self):
        for ticket in ("Mera delivery address badal do.", "Phone number badal do.", "Order 84922 ka address badal do."):
            # Explicit contact changes should also correct a broad legacy intent.
            case = routine_case(ticket_text=ticket, parsed_query={"detected_intent": "RETURN_REQUEST"})
            with self.subTest(ticket=ticket):
                self.assertFalse(matches(case, "returns"))
                self.assertEqual(support_queue_counts([case], today=TODAY)["pending_return_requests"], 0)
        for ticket in ("Mera size badal do.", "Ye kurta badal do.", "Product badal do please.", "Badal do item ko."):
            with self.subTest(ticket=ticket):
                self.assertTrue(matches(routine_case(ticket_text=ticket), "returns"))

    def test_ready_reply_is_a_verified_draft_and_can_overlap_attention(self):
        case = routine_case(ticket_text="Please refund this order", parsed_query={"detected_intent": "RETURN_REQUEST"})
        self.assertTrue(matches(case, "ready"))
        self.assertTrue(matches(case, "returns"))
        self.assertTrue(matches(case, "high_risk"))
        for changes in ({"status": "needs_review"}, {"draft_reply": "  "}, {"factual_verification_passed": False}, {"carrier_facts": {"sync_status": "SYNC_FAILED"}}):
            with self.subTest(changes=changes):
                self.assertFalse(matches(routine_case(**changes), "ready"))

    def test_needs_order_details_queue_is_missing_or_unmatched_identifier(self):
        for status in ("needs_identifier", "not_found", "needs_review", "sync_failed", "draft_ready", "approved_for_handoff"):
            with self.subTest(status=status):
                self.assertEqual(matches(routine_case(status=status), "needs_order_details"), status in {"needs_identifier", "not_found"})
        self.assertEqual(set(QUEUE_LABELS), {"all", "pending", "high_risk", "low_risk", "returns", "ready", "needs_order_details", "approved"})
        with self.assertRaisesRegex(ValueError, "Unknown"):
            case_matches_queue(routine_case(), "not-a-queue")

    def test_counts_match_filters_and_partition_on_a_fixed_date(self):
        cases = [
            routine_case(), routine_case(status="needs_identifier"), routine_case(status="not_found"),
            routine_case(ticket_text="Please refund this order", parsed_query={"detected_intent": "RETURN_REQUEST"}),
            routine_case(status="approved_for_handoff"),
        ]
        counts = support_queue_counts(iter(cases), today=TODAY)
        for key, queue in COUNT_QUEUES.items():
            self.assertEqual(counts[key], sum(matches(case, queue) for case in cases), key)
        self.assertEqual(counts["pending_tickets"], counts["high_risk_tickets"] + counts["low_risk_tickets"])
        self.assertEqual(support_queue_counts([], today=TODAY), dict.fromkeys(COUNT_QUEUES, 0))


class ExactQueueDatabaseCounts(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {
            "DATABASE_URL": "", "VERCEL": "", "MODEL_MODE": "demo", "GEMINI_API_KEY": "",
            "SQLITE_PATH": str(Path(self.temp_dir.name) / "queue-tests.sqlite"),
        })
        self.environment.start()
        get_session_factory.cache_clear()
        get_engine.cache_clear()
        initialize_database.cache_clear()
        initialize_database()

    def tearDown(self):
        get_engine().dispose()
        get_session_factory.cache_clear()
        get_engine.cache_clear()
        initialize_database.cache_clear()
        self.environment.stop()
        self.temp_dir.cleanup()

    def test_all_record_counts_agree_with_queue_lists_without_writing_or_calling_ai(self):
        templates = [
            routine_case(), routine_case(status="needs_identifier"), routine_case(status="not_found"),
            routine_case(ticket_text="I need a refund", parsed_query={"detected_intent": "RETURN_REQUEST"}, requires_human_escalation=True),
            routine_case(factual_verification_passed=False), routine_case(status="approved_for_handoff", requires_human_escalation=True),
        ]
        with session_scope(write=True) as session:
            for index in range(66):
                case = deepcopy(templates[index % len(templates)])
                session.add(SupportCase(id=f"case-{index}", **case))
            session.add(ListingRecord(id="draft-product", status="draft"))
            session.add(ListingRecord(id="approved-product", status="approved"))
            session.add(AuditEvent(entity_type="support_case", entity_id="case-0", action="fixture"))
        self.assertEqual(len(recent_support_cases()), 50)
        cases = recent_support_cases(limit=None)
        with patch("dhaga_os.queues._today", return_value=TODAY), patch("dhaga_os.model_gateway.generate_json") as ai:
            counts = workspace_counts()
        ai.assert_not_called()
        self.assertEqual(counts["support_total"], 66)
        self.assertEqual(counts["support_pending"], 55)
        self.assertEqual(counts["support_approved"], 11)
        self.assertEqual(counts["support_needs_review"], 11)
        self.assertEqual(counts["listing_total"], 2)
        self.assertEqual(counts["listing_pending"], 1)
        self.assertEqual(counts["listing_approved"], 1)
        for key, queue in COUNT_QUEUES.items():
            self.assertEqual(counts[key], sum(matches(case, queue) for case in cases), key)
        self.assertEqual(counts["pending_tickets"], counts["support_pending"])
        self.assertEqual(counts["pending_tickets"], counts["high_risk_tickets"] + counts["low_risk_tickets"])
        with session_scope() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(AuditEvent)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(SupportCase)), 66)


if __name__ == "__main__":
    unittest.main()
