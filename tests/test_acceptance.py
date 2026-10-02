from __future__ import annotations

import csv
import io
import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ["MODEL_MODE"] = "demo"
os.environ.pop("GEMINI_API_KEY", None)

from dhaga_os.catalog import (  # noqa: E402
    COLOR_ALIASES,
    _deterministic_copy_check,
    normalize_color,
    normalize_size_values,
    process_catalog_records,
    read_vendor_upload_detailed,
)
from dhaga_os.cx import (  # noqa: E402
    ORDERS,
    _carrier_facts,
    _deterministic_parse,
    _deterministic_reply_check,
    demo_phone_numbers,
    process_customer_ticket,
)
from dhaga_os.models import TicketIntent  # noqa: E402


class CatalogAcceptanceTests(unittest.TestCase):
    def test_every_color_alias_maps_to_a_master_color(self) -> None:
        for alias in COLOR_ALIASES:
            with self.subTest(alias=alias):
                self.assertEqual(normalize_color(alias), COLOR_ALIASES[alias])

    def test_common_alpha_sizes_and_ranges_are_standardized(self) -> None:
        self.assertEqual(normalize_size_values("Extra Small-2XL"), "XS, S, M, L, XL, XXL")
        self.assertEqual(normalize_size_values("small, Medium, 2XL"), "S, M, XXL")
        self.assertEqual(normalize_size_values("Free size"), "Free size")
        self.assertEqual(normalize_size_values(""), "")

    def test_malformed_csv_rows_are_reported_without_losing_valid_rows(self) -> None:
        source = (
            "sku,product_name,color,fabric,occasion\n"
            "GOOD-1,First kurta,red,cotton,festive\n"
            'BAD-QUOTE,"broken product,blue,rayon,party\n'
            "BAD-WIDTH,Extra fields,blue,silk,work,unexpected\n"
            "GOOD-2,Second kurta,blue,linen,office\n"
        ).encode()
        records, errors = read_vendor_upload_detailed(source, "vendor.csv")
        self.assertEqual([record["vendor_sku_raw"] for record in records], ["GOOD-1", "GOOD-2"])
        self.assertEqual(len(errors), 2)
        self.assertTrue(all(error["line"] > 1 and error["issue"] for error in errors))

    def test_demo_import_ids_are_stable_across_reloads(self) -> None:
        from dhaga_os.catalog import sample_vendor_csv

        first, _ = read_vendor_upload_detailed(
            sample_vendor_csv(), "demo_vendor.csv", stable_key_prefix="dhaga-demo-catalog"
        )
        second, _ = read_vendor_upload_detailed(
            sample_vendor_csv(), "demo_vendor.csv", stable_key_prefix="dhaga-demo-catalog"
        )
        self.assertEqual([row["row_key"] for row in first], [row["row_key"] for row in second])
        self.assertEqual(len({row["row_key"] for row in first}), len(first))

    def test_missing_required_fields_are_visible_and_blocked(self) -> None:
        source = (
            "sku,product_name,color,fabric\n"
            ",Missing SKU,red,cotton\n"
            "NO-NAME,,blue,cotton\n"
            "NO-FABRIC,Missing fabric,green,\n"
        ).encode()
        records, errors = read_vendor_upload_detailed(source, "vendor.csv")
        self.assertFalse(errors)
        results = process_catalog_records(records)
        self.assertEqual(len(results), 3)
        self.assertTrue(all(row["status"] == "blocked" for row in results))
        self.assertTrue(all(row["issues"] for row in results))

    def test_fifty_row_batch_finishes_within_acceptance_limit(self) -> None:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["sku", "product_name", "color", "fabric", "fit", "care", "size", "occasion"])
        for index in range(50):
            writer.writerow(
                [f"SKU-{index:03}", f"Cotton kurta {index}", "gulabi", "cotton slub", "straight", "hand wash", "S-XXL", "festive"]
            )
        start = time.perf_counter()
        rows, errors = read_vendor_upload_detailed(output.getvalue().encode(), "fifty.csv")
        prepared = process_catalog_records(rows)
        elapsed = time.perf_counter() - start
        self.assertFalse(errors)
        self.assertEqual(len(prepared), 50)
        self.assertTrue(all(row["standard_color"] == "Pink" for row in prepared))
        self.assertTrue(all(row["size_values"] == "S, M, L, XL, XXL" for row in prepared))
        self.assertLess(elapsed, 90)

    def test_fabric_discrepancy_is_flagged_even_if_other_source_text_mentions_it(self) -> None:
        record = {
            "vendor_fabric_source": "Rayon Slub",
            "wash_care": "Hand wash",
            "vendor_care_source": "Hand wash",
            "standard_color": "Green",
            "raw_color_input": "pista",
            "raw_payload": {"product_name": "Chiffon-look rayon kurta"},
        }
        copy = {
            "title_hinglish": "Pure Chiffon kurta",
            "description_hinglish": "Made with pure chiffon.",
            "key_highlights": ["Fabric: Pure Chiffon"],
        }
        passed, notes = _deterministic_copy_check(record, copy)
        self.assertFalse(passed)
        self.assertIn("chiffon", notes)
        self.assertIn("Rayon Slub", notes)

    def test_demo_copy_passes_for_supported_colors_in_the_sample_sheet(self) -> None:
        from dhaga_os.catalog import sample_vendor_csv

        records, errors = read_vendor_upload_detailed(sample_vendor_csv(), "demo.csv")
        processed = process_catalog_records(records)
        self.assertFalse(errors)
        copy_rows = [record for record in processed if record["generated_copy"]]
        self.assertTrue(copy_rows)
        self.assertTrue(all(record["compliance_passed"] is True for record in copy_rows))


class CustomerSupportAcceptanceTests(unittest.TestCase):
    def test_hinglish_wismo_and_negative_cancel_are_classified_safely(self) -> None:
        parsed = _deterministic_parse("Cancel nahi hua, mera order 84920 kahan hai?")
        self.assertEqual(parsed.detected_intent, TicketIntent.WISMO)
        self.assertEqual(parsed.order_id, "84920")
        self.assertEqual(parsed.language, "Hinglish")

    def test_missing_message_and_identifier_are_recoverable(self) -> None:
        self.assertEqual(process_customer_ticket("")["status"], "blocked")
        self.assertEqual(process_customer_ticket(None)["status"], "blocked")
        result = process_customer_ticket("Where is my order? I placed it last week.")
        self.assertEqual(result["status"], "needs_identifier")
        self.assertTrue(result["draft_reply"])
        self.assertTrue(_deterministic_reply_check(result["draft_reply"], {})[0])

    def test_malformed_carrier_fixture_becomes_a_visible_sync_failure(self) -> None:
        facts = _carrier_facts(
            {
                "order_id": 84923,
                "carrier_name": 7,
                "current_status": 3,
                "current_location": None,
                "tracking_url": "https://example.test/track",
                "destination_city": "Jaipur",
                "payment_mode": "COD",
                "awb": "AWB-1",
                "shipped_at": 7,
                "promised_delivery_date": "not-a-date",
                "sync_status": "OK",
            }
        )
        self.assertEqual(facts["sync_status"], "SYNC_FAILED")
        self.assertEqual(facts["current_status"], "3")
        self.assertEqual(facts["promised_delivery_date"], "")

    def test_phone_lookup_works_without_order_id(self) -> None:
        self.assertTrue(demo_phone_numbers())
        result = process_customer_ticket("Where is my order?", phone_override=demo_phone_numbers()[0])
        self.assertEqual(result["order_id"], "84920")
        self.assertEqual(result["status"], "draft_ready")

    def test_demo_triage_is_within_three_seconds(self) -> None:
        start = time.perf_counter()
        result = process_customer_ticket("Mera order 84920 kahan hai? Abhi tak nahi mila.")
        self.assertLess(time.perf_counter() - start, 3)
        self.assertEqual(result["status"], "draft_ready")

    def test_delayed_northeast_reply_has_verified_date_and_tracking_link(self) -> None:
        result = process_customer_ticket("Bhaiya order 84920 kahan hai? Abhi tak nahi mila.")
        self.assertTrue(result["carrier_facts"]["is_delayed"])
        self.assertTrue(result["requires_human_escalation"])
        self.assertIn(result["carrier_facts"]["promised_delivery_date"], result["draft_reply"])
        self.assertIn(result["carrier_facts"]["tracking_url"], result["draft_reply"])
        self.assertTrue(_deterministic_reply_check(result["draft_reply"], result["carrier_facts"])[0])

    def test_all_carrier_fixtures_have_a_safe_visible_outcome(self) -> None:
        for order in ORDERS:
            with self.subTest(order=order["order_id"]):
                result = process_customer_ticket(f"Where is order {order['order_id']}?")
                if order["sync_status"] != "OK":
                    self.assertEqual(result["status"], "sync_failed")
                    self.assertFalse(result.get("draft_reply"))
                else:
                    self.assertTrue(result.get("draft_reply"))
                    self.assertIn(order["carrier_name"], result["carrier_facts"]["carrier_name"])

    def test_cod_cancellation_and_unsupported_cancellation_paths(self) -> None:
        cod = process_customer_ticket("Please cancel order 84921. I do not want it.")
        self.assertEqual(cod["status"], "draft_ready")
        self.assertIn("doorstep", cod["draft_reply"])
        self.assertNotIn("refund", cod["draft_reply"].casefold())
        unsupported = process_customer_ticket("Please cancel order 84922.")
        self.assertEqual(unsupported["status"], "needs_review")
        self.assertTrue(unsupported["requires_human_escalation"])
        self.assertFalse(unsupported.get("draft_reply"))

    def test_return_request_uses_return_policy_even_after_long_transit(self) -> None:
        result = process_customer_ticket("I want to return order 84930 because the size does not fit.")
        self.assertEqual(result["parsed_query"]["detected_intent"], "RETURN_REQUEST")
        self.assertFalse(result["carrier_facts"]["is_delayed"])
        self.assertIn("Returns section", result["draft_reply"])

    def test_disputed_delivery_is_escalated_without_a_customer_reply(self) -> None:
        result = process_customer_ticket("Order 84924 says delivered but I have not received it.")
        self.assertEqual(result["status"], "needs_review")
        self.assertTrue(result["requires_human_escalation"])
        self.assertFalse(result.get("draft_reply"))

    def test_complaint_escalates_even_when_it_contains_an_order_id(self) -> None:
        result = process_customer_ticket(
            "I have a serious complaint about order 84921. This feels like fraud; I need a manager."
        )
        self.assertEqual(result["parsed_query"]["detected_intent"], "ESCALATION")
        self.assertTrue(result["requires_human_escalation"])
        self.assertFalse(result.get("draft_reply"))

    def test_date_check_catches_common_wrong_formats_and_allows_matching_date(self) -> None:
        facts = {"sync_status": "OK", "carrier_name": "Delhivery", "promised_delivery_date": "2026-10-03"}
        self.assertTrue(_deterministic_reply_check("Delivery expected on 03 Oct 2026.", facts)[0])
        for wrong_date in ("2026-10-04", "04 Oct 2026", "October 4, 2026", "4/10/2026"):
            with self.subTest(wrong_date=wrong_date):
                passed, notes = _deterministic_reply_check(f"Delivery expected {wrong_date}.", facts)
                self.assertFalse(passed)
                self.assertIn("date", notes.casefold())

    def test_missing_promised_date_blocks_made_up_dates(self) -> None:
        passed, notes = _deterministic_reply_check(
            "Your parcel should arrive tomorrow.",
            {"sync_status": "OK", "carrier_name": "Ekart", "promised_delivery_date": ""},
        )
        self.assertFalse(passed)
        self.assertIn("no delivery date", notes.casefold())


class DatabaseApprovalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env_before = {key: os.environ.get(key) for key in ("DATABASE_URL", "VERCEL", "SQLITE_PATH")}
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("VERCEL", None)
        os.environ["SQLITE_PATH"] = str(Path(self.temp_dir.name) / "acceptance.sqlite")
        from dhaga_os.db import get_engine, get_session_factory, initialize_database

        get_session_factory.cache_clear()
        get_engine.cache_clear()
        initialize_database.cache_clear()
        initialize_database()

    def tearDown(self) -> None:
        from dhaga_os.db import get_engine, get_session_factory, initialize_database

        get_engine().dispose()
        get_session_factory.cache_clear()
        get_engine.cache_clear()
        initialize_database.cache_clear()
        for key, value in self.env_before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temp_dir.cleanup()

    def test_database_blocks_unverified_approvals_and_records_safe_handoffs(self) -> None:
        from dhaga_os.db import (
            approve_listing,
            approve_support_case,
            approved_export_rows,
            recent_support_cases,
            save_listing_draft,
            save_support_case,
            unapproved_listing_rows,
        )

        listing = {
            "row_key": "listing-test",
            "source_filename": "test.csv",
            "vendor_sku_raw": "TEST-1",
            "raw_payload": {},
            "normalized_payload": {
                "product_name": "Test kurta",
                "fabric_composition": "Cotton",
                "standard_color": "Red",
            },
            "generated_copy": {"title_hinglish": "Test kurta"},
            "compliance_passed": False,
            "issues": [],
            "status": "needs_review",
        }
        save_listing_draft(listing)
        self.assertEqual(unapproved_listing_rows()[0]["row_key"], "listing-test")
        with self.assertRaisesRegex(ValueError, "factual check"):
            approve_listing("listing-test", listing["generated_copy"], record=listing)
        listing["compliance_passed"] = True
        listing["status"] = "draft"
        approve_listing("listing-test", listing["generated_copy"], record=listing)
        self.assertFalse(unapproved_listing_rows())

        case = {
            "case_id": "case-test",
            "ticket_text": "Where is order 84920?",
            "parsed_query": {"detected_intent": "WISMO"},
            "order_id": "84920",
            "carrier_facts": {"sync_status": "OK"},
            "draft_reply": "Verified draft",
            "factual_verification_passed": False,
            "requires_human_escalation": True,
            "status": "needs_review",
        }
        save_support_case(case)
        self.assertEqual(recent_support_cases()[0]["case_id"], "case-test")
        with self.assertRaisesRegex(ValueError, "fact check"):
            approve_support_case("case-test", case["draft_reply"], record=case)
        case["factual_verification_passed"] = True
        case["status"] = "draft_ready"
        approve_support_case("case-test", case["draft_reply"], record=case)
        listings, cases = approved_export_rows()
        self.assertEqual(len(listings), 1)
        self.assertEqual(len(cases), 1)
        self.assertTrue(cases[0]["agent_follow_up_required"])
        self.assertEqual(recent_support_cases()[0]["status"], "approved_for_handoff")


if __name__ == "__main__":
    unittest.main()
