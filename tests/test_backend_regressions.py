from __future__ import annotations

import csv
import io
import os
import tempfile
import unittest
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from unittest.mock import patch
from threading import Barrier, Event, current_thread

from sqlalchemy import func, select
from openpyxl import Workbook

from dhaga_os.catalog import (
    _deterministic_copy,
    _deterministic_copy_check,
    process_catalog_records,
    read_vendor_upload_detailed,
    refresh_catalog_validation,
)
from dhaga_os.cx import ORDERS, _carrier_facts, _deterministic_reply_check, _parse, process_customer_ticket
from dhaga_os.db import (
    AuditEvent,
    approve_listing,
    approve_support_case,
    approved_export_rows,
    get_engine,
    get_listing_rows,
    get_session_factory,
    initialize_database,
    recent_support_cases,
    save_listing_draft,
    save_support_case,
    session_scope,
    workspace_counts,
)
from dhaga_os.exports import csv_export_bytes
from dhaga_os.model_gateway import ModelTask
from dhaga_os.models import CatalogCopyBatch, CXDraft, ParsedCustomerQuery, ParsedCustomerQueryBatch, TicketIntent


def listing_row(sku: str = "REG-1") -> dict:
    rows, errors = read_vendor_upload_detailed(
        f"sku,product_name,color,fabric,care\n{sku},Everyday kurta,red,cotton,hand wash\n".encode(), "source.csv"
    )
    assert not errors
    return process_catalog_records(rows)[0]


class UploadAndValidationRegressions(unittest.TestCase):
    def test_multiline_quoted_cells_preserve_lines_and_other_rows(self):
        content = (
            'sku,product_name,color,fabric\n'
            'A,"Kurta with\na quoted ""detail""",red,cotton\n'
            'B,Second kurta,blue,rayon\n'
        ).encode()
        rows, errors = read_vendor_upload_detailed(content, "vendor.csv")
        self.assertFalse(errors)
        self.assertEqual([row["vendor_sku_raw"] for row in rows], ["A", "B"])
        self.assertEqual(rows[0]["product_name"], 'Kurta with\na quoted "detail"')
        self.assertEqual(rows[1]["source_line_number"], 4)

    def test_multiline_description_can_contain_commas(self):
        rows, errors = read_vendor_upload_detailed(
            b'sku,product_name,color,fabric\nA,"Festival kurta\nSoft, breathable, comfortable, festive",red,cotton\nB,Other kurta,blue,rayon\n',
            "vendor.csv",
        )
        self.assertFalse(errors)
        self.assertEqual([row["vendor_sku_raw"] for row in rows], ["A", "B"])

    def test_excel_headers_are_validated_before_pandas_can_rename_them(self):
        for headers in (["sku", "sku", "color", "fabric"], ["sku", "", "color", "fabric"]):
            workbook = Workbook()
            workbook.active.append(headers)
            workbook.active.append(["FIRST", "SECOND", "red", "cotton"])
            output = io.BytesIO()
            workbook.save(output)
            with self.subTest(headers=headers), self.assertRaises(ValueError):
                read_vendor_upload_detailed(output.getvalue(), "vendor.xlsx")

    def test_duplicate_and_blank_headers_cannot_silently_replace_cells(self):
        for header in ("sku,sku,color,fabric", "sku,product_name,color,color", "sku,,color,fabric"):
            with self.subTest(header=header), self.assertRaises(ValueError):
                read_vendor_upload_detailed((header + "\nA,Kurta,red,cotton\n").encode(), "vendor.csv")

    def test_exact_reupload_has_same_ids_even_when_renamed(self):
        content = b"sku,product_name,color,fabric\nA,Kurta,red,cotton\n"
        first, _ = read_vendor_upload_detailed(content, "original.csv")
        second, _ = read_vendor_upload_detailed(content, "renamed.csv")
        self.assertEqual(first[0]["row_key"], second[0]["row_key"])

    def test_duplicate_supplier_codes_require_correction(self):
        content = b"sku,product_name,color,fabric\nA,First,red,cotton\na,Second,blue,rayon\n"
        rows, _ = read_vendor_upload_detailed(content, "vendor.csv")
        self.assertTrue(all(row["issues"] for row in rows))
        row = rows[1]
        row["vendor_sku_raw"] = "B"
        row["generated_copy"] = _deterministic_copy(row)
        refresh_catalog_validation(row)
        self.assertEqual(row["status"], "draft")

    def test_fixing_unknown_color_removes_the_current_missing_issue(self):
        rows, _ = read_vendor_upload_detailed(b"sku,product_name,color,fabric\nA,Kurta,mystery,cotton\n", "vendor.csv")
        row = rows[0]
        row["standard_color"] = "Red"
        row["generated_copy"] = _deterministic_copy(row)
        refresh_catalog_validation(row)
        self.assertFalse(row["issues"])
        self.assertEqual(row["normalized_payload"]["standard_color"], "Red")
        row["product_name"] = ""
        refresh_catalog_validation(row)
        self.assertEqual(row["status"], "blocked")

    def test_fabric_blends_cannot_become_pure_and_missing_care_is_not_evidence(self):
        row = listing_row()
        row["vendor_fabric_source"] = "cotton blend"
        copy = deepcopy(row["generated_copy"])
        copy["description_hinglish"] = "Pure cotton kurta."
        self.assertFalse(_deterministic_copy_check(row, copy)[0])
        row["vendor_care_source"] = ""
        row["wash_care"] = "Machine wash"
        copy["description_hinglish"] = "Cotton kurta. Machine wash."
        self.assertFalse(_deterministic_copy_check(row, copy)[0])

    def test_csv_formula_text_is_neutralized_without_changing_numeric_values(self):
        exported = csv_export_bytes([{"sku": "=HYPERLINK(\"bad\")", "reply": " \t@SUM(A1)", "price": -2, "name": "Normal"}])
        row = next(csv.DictReader(io.StringIO(exported.decode("utf-8-sig"))))
        self.assertTrue(row["sku"].startswith("'="))
        self.assertTrue(row["reply"].startswith("'"))
        self.assertEqual(row["price"], "-2")
        self.assertEqual(row["name"], "Normal")


class CustomerFactRegressions(unittest.TestCase):
    def test_clear_live_message_uses_local_route_without_none_dereference(self):
        with patch.dict(os.environ, {"MODEL_MODE": "live", "GEMINI_API_KEY": "test"}), patch("dhaga_os.cx.generate_for_task", return_value=None):
            result = process_customer_ticket("Where is order 84922?")
        self.assertEqual(result["status"], "draft_ready")

    def test_model_cannot_invent_customer_identifiers(self):
        response = ParsedCustomerQueryBatch(result=ParsedCustomerQuery(detected_intent=TicketIntent.WISMO, order_id="84920", phone_number="9000084920"))
        with patch.dict(os.environ, {"MODEL_MODE": "live", "GEMINI_API_KEY": "test"}), patch("dhaga_os.cx.generate_for_task", return_value=response):
            parsed, _ = _parse("Please help with this")
        self.assertIsNone(parsed.order_id)
        self.assertIsNone(parsed.phone_number)

    def test_explicit_wrong_order_never_falls_back_to_another_phone_order(self):
        result = process_customer_ticket("Where is order 99999?", phone_override="9000084920")
        self.assertEqual(result["status"], "not_found")

    def test_operator_override_conflicting_with_message_needs_confirmation(self):
        result = process_customer_ticket("Where is order 84923?", order_id_override="84922")
        self.assertEqual(result["status"], "needs_review")
        self.assertFalse(result["draft_reply"])
        self.assertIn("differs", result["error"])
        self.assertFalse(result["carrier_facts"])
        result = process_customer_ticket("Where is order 84922?", phone_override="9000084920")
        self.assertEqual(result["status"], "not_found")

    def test_phone_with_multiple_orders_requires_specific_order(self):
        orders = [deepcopy(ORDERS[0]), deepcopy(ORDERS[0])]
        orders[1]["order_id"] = "89999"
        with patch("dhaga_os.cx.ORDERS", orders):
            result = process_customer_ticket("Where is my order?", phone_override="9000084920")
        self.assertEqual(result["status"], "not_found")
        self.assertFalse(result["draft_reply"])

    def test_long_northeast_transit_is_not_a_delay_before_carrier_eta(self):
        with patch("dhaga_os.cx._today_india", return_value=date(2026, 10, 2)):
            facts = _carrier_facts(ORDERS[0])
        self.assertEqual(facts["days_in_transit"], 8)
        self.assertFalse(facts["is_delayed"])
        with patch("dhaga_os.cx._today_india", return_value=date(2026, 10, 4)):
            self.assertTrue(_carrier_facts(ORDERS[0])["is_delayed"])

    def test_unsafe_tracking_url_is_not_rendered_as_verified(self):
        order = {**ORDERS[0], "tracking_url": "javascript:alert(1)"}
        facts = _carrier_facts(order)
        self.assertEqual(facts["sync_status"], "SYNC_FAILED")
        self.assertFalse(facts["tracking_url"])

    def test_edited_reply_checks_order_status_url_location_and_promises(self):
        facts = _carrier_facts(ORDERS[2])
        replies = (
            "Order 84920 is in transit.",
            "Your order is delivered.",
            "It is out for delivery.",
            "Tracking: https://malicious.example/",
            "The parcel is at Guwahati hub.",
            "Your delivery is guaranteed tomorrow.",
            "We have cancelled your order.",
            "Please refuse the delivery at the doorstep.",
            "The parcel will arrive 5 October.",
        )
        for reply in replies:
            with self.subTest(reply=reply):
                self.assertFalse(_deterministic_reply_check(reply, facts)[0])
        self.assertTrue(_deterministic_reply_check("Order 84922 is in transit. Expected delivery 2026-10-04.", facts)[0])

    def test_missing_identifier_reply_cannot_claim_order_facts(self):
        for reply in ("It will arrive tomorrow.", "Refund today.", "Tracking https://example.com", "ETA 31 Feb 2026."):
            with self.subTest(reply=reply):
                self.assertFalse(_deterministic_reply_check(reply, {})[0])

    def test_live_ai_reply_needs_completed_factual_audit(self):
        draft = CXDraft(draft_reply_hinglish="Order 84922 is in transit.", carrier_status_summary="In transit")
        def respond(task, **kwargs):
            return draft if task == ModelTask.CUSTOMER_REPLY else None
        with patch.dict(os.environ, {"MODEL_MODE": "live", "GEMINI_API_KEY": "test"}), patch("dhaga_os.cx.generate_for_task", side_effect=respond):
            result = process_customer_ticket("Mera order 84922 kahan hai?")
        self.assertFalse(result["factual_verification_passed"])
        self.assertEqual(result["status"], "needs_review")

    def test_live_ai_listing_needs_completed_source_audit_or_operator_review(self):
        row = listing_row()
        generated = CatalogCopyBatch(items=[row["generated_copy"]])
        def respond(task, **kwargs):
            return generated if task == ModelTask.LISTING_COPY else None
        with patch.dict(os.environ, {"MODEL_MODE": "live", "GEMINI_API_KEY": "test"}), patch("dhaga_os.catalog.generate_for_task", side_effect=respond):
            row = process_catalog_records([row])[0]
        self.assertFalse(row["compliance_passed"])
        refresh_catalog_validation(row)
        self.assertFalse(row["compliance_passed"])
        row["normalized_payload"]["human_source_verified"] = True
        refresh_catalog_validation(row)
        self.assertTrue(row["compliance_passed"])


class PersistenceRegressions(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"DATABASE_URL": "", "VERCEL": "", "SQLITE_PATH": str(Path(self.temp_dir.name) / "regressions.sqlite"), "MODEL_MODE": "demo", "GEMINI_API_KEY": ""})
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

    def test_approval_rechecks_the_actual_listing_copy_and_rolls_back(self):
        row = listing_row()
        save_listing_draft(row)
        unsafe = {**row["generated_copy"], "description_hinglish": "Silk kurta."}
        with self.assertRaisesRegex(ValueError, "factual check"):
            approve_listing(row["row_key"], unsafe, record=row)
        self.assertFalse(approved_export_rows()[0])
        self.assertEqual(get_listing_rows([row["row_key"]])[0]["generated_copy"], row["generated_copy"])

    def test_approval_rechecks_the_actual_customer_reply_and_order_record(self):
        case = process_customer_ticket("Where is order 84922?")
        save_support_case(case)
        with self.assertRaisesRegex(ValueError, "fact check"):
            approve_support_case(case["case_id"], "Your order is delivered.", record=case)
        changed = deepcopy(case)
        changed["carrier_facts"]["current_status"] = "Delivered"
        with self.assertRaisesRegex(ValueError, "details changed"):
            approve_support_case(case["case_id"], "Your order is delivered.", record=changed)
        self.assertFalse(approved_export_rows()[1])

    def test_reapproval_is_idempotent_and_stale_save_cannot_undo_approval(self):
        row = listing_row()
        save_listing_draft(row)
        approve_listing(row["row_key"], row["generated_copy"], actor="reviewer", record=row)
        approve_listing(row["row_key"], row["generated_copy"], actor="reviewer", record=row)
        with self.assertRaisesRegex(ValueError, "already approved"):
            save_listing_draft(row)
        self.assertEqual(get_listing_rows([row["row_key"]])[0]["status"], "approved")
        with session_scope() as session:
            count = session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "approved_for_staging"))
        self.assertEqual(count, 1)

    def test_ordinary_save_cannot_forge_an_approved_export(self):
        row = listing_row()
        row["status"] = "approved"
        with self.assertRaisesRegex(ValueError, "review action"):
            save_listing_draft(row)
        case = process_customer_ticket("Where is order 84922?")
        case["status"] = "approved_for_handoff"
        with self.assertRaisesRegex(ValueError, "review action"):
            save_support_case(case)
        self.assertEqual(approved_export_rows(), ([], []))

    def test_edited_drafts_and_exact_counts_survive_reload(self):
        for index in range(105):
            row = listing_row(f"REG-{index}")
            save_listing_draft(row)
        row["product_name"] = "Operator corrected kurta"
        row["generated_copy"] = _deterministic_copy(row)
        refresh_catalog_validation(row)
        save_listing_draft(row)
        self.assertEqual(get_listing_rows([row["row_key"]])[0]["product_name"], "Operator corrected kurta")
        self.assertEqual(workspace_counts()["listing_pending"], 105)
        case = process_customer_ticket("Where is order 84922?")
        save_support_case(case)
        case["draft_reply"] = "Order 84922 is in transit."
        save_support_case(case)
        self.assertEqual(recent_support_cases()[0]["draft_reply"], case["draft_reply"])

    def test_second_approved_listing_with_same_supplier_code_is_blocked(self):
        first = listing_row()
        save_listing_draft(first)
        approve_listing(first["row_key"], first["generated_copy"], record=first)
        second = deepcopy(first)
        second["row_key"] = "distinct-import-id"
        second["generated_copy"]["row_key"] = second["row_key"]
        save_listing_draft(second)
        with self.assertRaisesRegex(ValueError, "already has an approved"):
            approve_listing(second["row_key"], second["generated_copy"], record=second)

    def test_stale_draft_revision_cannot_overwrite_a_teammates_edit(self):
        row = listing_row()
        save_listing_draft(row)
        stale = deepcopy(row)
        row["product_name"] = "Latest reviewed name"
        row["generated_copy"] = _deterministic_copy(row)
        refresh_catalog_validation(row)
        save_listing_draft(row)
        stale["product_name"] = "Stale browser edit"
        refresh_catalog_validation(stale)
        with self.assertRaisesRegex(ValueError, "teammate changed"):
            save_listing_draft(stale)
        self.assertEqual(get_listing_rows([row["row_key"]])[0]["product_name"], "Latest reviewed name")

    def test_concurrent_stale_listing_save_cannot_change_approved_copy(self):
        import dhaga_os.db as database
        row = listing_row()
        save_listing_draft(row)
        stale = deepcopy(row)
        stale["generated_copy"]["description_hinglish"] = "Unreviewed stale text"
        approval_has_lock, release_approval, saver_started = Event(), Event(), Event()
        original_apply = database._apply_listing_record
        def pause_approval(saved, incoming):
            if current_thread().name.startswith("approve"):
                approval_has_lock.set()
                self.assertTrue(release_approval.wait(3))
            return original_apply(saved, incoming)
        def save_stale():
            saver_started.set()
            try:
                save_listing_draft(stale)
            except ValueError as exc:
                return str(exc)
            return ""
        with patch.object(database, "_apply_listing_record", side_effect=pause_approval), ThreadPoolExecutor(max_workers=1, thread_name_prefix="approve") as approving, ThreadPoolExecutor(max_workers=1, thread_name_prefix="save") as saving:
            approval = approving.submit(approve_listing, row["row_key"], row["generated_copy"], "reviewer", row)
            self.assertTrue(approval_has_lock.wait(3))
            save = saving.submit(save_stale)
            self.assertTrue(saver_started.wait(3))
            release_approval.set()
            approval.result(timeout=5)
            self.assertIn("already approved", save.result(timeout=5))
        self.assertEqual(approved_export_rows()[0][0]["description_hinglish"], row["generated_copy"]["description_hinglish"])

    def test_concurrent_stale_reply_save_cannot_change_approved_reply(self):
        import dhaga_os.db as database
        case = process_customer_ticket("Where is order 84922?")
        save_support_case(case)
        stale = deepcopy(case)
        stale["draft_reply"] = "Unreviewed stale text"
        approval_has_lock, release_approval, saver_started = Event(), Event(), Event()
        original_apply = database._apply_support_case
        def pause_approval(saved, incoming):
            if current_thread().name.startswith("approve"):
                approval_has_lock.set()
                self.assertTrue(release_approval.wait(3))
            return original_apply(saved, incoming)
        def save_stale():
            saver_started.set()
            try:
                save_support_case(stale)
            except ValueError as exc:
                return str(exc)
            return ""
        with patch.object(database, "_apply_support_case", side_effect=pause_approval), ThreadPoolExecutor(max_workers=1, thread_name_prefix="approve") as approving, ThreadPoolExecutor(max_workers=1, thread_name_prefix="save") as saving:
            approval = approving.submit(approve_support_case, case["case_id"], case["draft_reply"], "reviewer", case)
            self.assertTrue(approval_has_lock.wait(3))
            save = saving.submit(save_stale)
            self.assertTrue(saver_started.wait(3))
            release_approval.set()
            approval.result(timeout=5)
            self.assertIn("already approved", save.result(timeout=5))
        self.assertEqual(approved_export_rows()[1][0]["draft_reply"], case["draft_reply"])

    def test_two_concurrent_approvals_cannot_export_the_same_supplier_code(self):
        first = listing_row()
        second = deepcopy(first)
        second["row_key"] = "concurrent-second"
        second["generated_copy"]["row_key"] = second["row_key"]
        save_listing_draft(first)
        save_listing_draft(second)
        start = Barrier(2)
        def approve(candidate):
            start.wait(timeout=3)
            try:
                approve_listing(candidate["row_key"], candidate["generated_copy"], record=candidate)
                return "approved"
            except ValueError:
                return "blocked"
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(approve, candidate) for candidate in (first, second)]
            self.assertEqual(sorted(future.result(timeout=5) for future in futures), ["approved", "blocked"])
        self.assertEqual(len(approved_export_rows()[0]), 1)


if __name__ == "__main__":
    unittest.main()
