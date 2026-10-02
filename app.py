from __future__ import annotations

import time
import logging
from copy import deepcopy
from typing import Any

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from dhaga_os.catalog import (
    _deterministic_copy_check,
    _deterministic_copy,
    normalize_size_values,
    process_catalog_records,
    read_vendor_upload_detailed,
    sample_vendor_csv,
)
from dhaga_os.config import get_settings
from dhaga_os.cx import _deterministic_reply_check, demo_order_ids, demo_phone_numbers, demo_tickets, process_customer_ticket
from dhaga_os.db import (
    approve_listing,
    approve_support_case,
    approved_export_rows,
    initialize_database,
    is_database_persistent,
    recent_support_cases,
    save_listing_draft,
    save_support_case,
    unapproved_listing_rows,
)
from dhaga_os.models import MasterColor

st.set_page_config(page_title="Dhaga Ops", layout="wide")

settings = get_settings()
logger = logging.getLogger("dhaga_ops")
COMMON_FABRICS = (
    "Cotton", "Rayon", "Viscose", "Polyester", "Silk", "Linen", "Georgette", "Chiffon",
    "Chanderi", "Satin", "Velvet", "Wool", "Nylon", "Modal", "Poplin", "Other — enter below",
)


def _authenticated() -> bool:
    if not settings.app_password:
        return True
    if st.session_state.get("authenticated"):
        return True
    st.title("Dhaga Ops sign in")
    with st.form("login"):
        candidate = st.text_input("App password", type="password", help="Use the password shared by your Dhaga Ops administrator.")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted:
        import hmac

        if hmac.compare_digest(candidate, settings.app_password):
            st.session_state.authenticated = True
            st.rerun()
        st.error("That password did not match. Check it and try again.")
    return False


if not _authenticated():
    st.stop()

database_ready = False
database_error = ""
try:
    initialize_database()
    database_ready = True
except Exception as exc:
    logger.exception("Could not initialize the staging database")
    database_error = "Could not connect to the staging database. Check the database connection settings and try again."


def _status_badge(status: str) -> None:
    labels = {
        "draft": ("Draft", "info"),
        "needs_review": ("Needs review", "warning"),
        "blocked": ("Required information is missing", "error"),
        "approved": ("Approved for staging", "success"),
        "draft_ready": ("Tracking facts checked · review the reply", "success"),
        "needs_identifier": ("Order number or registered phone needed", "warning"),
        "not_found": ("No matching example order found", "warning"),
        "sync_failed": ("Tracking could not be checked", "error"),
    }
    label, kind = labels.get(status, (status.replace("_", " ").title(), "info"))
    getattr(st, kind)(label)


def _persist_listing(record: dict[str, Any]) -> None:
    if database_ready:
        save_listing_draft(record)


def _persist_support(record: dict[str, Any]) -> None:
    if database_ready:
        save_support_case(record)


def _friendly_exception(exc: Exception, action: str) -> str:
    logger.exception("Dhaga Ops action failed: %s", action)
    return f"{action} could not be completed. Your current form entries are still available; try again or contact the app administrator."


def _switch_workspace(workspace: str) -> None:
    """Set the navigation widget before Streamlit rebuilds the page after a button click."""
    st.session_state.workspace = workspace


def _catalog_workspace() -> None:
    reset_attestation_for = st.session_state.pop("pending_attestation_reset", None)
    if reset_attestation_for:
        st.session_state.pop(f"attest-{reset_attestation_for}", None)
    pending_copy = st.session_state.pop("pending_listing_copy", None)
    if pending_copy:
        for field in ("title", "description", "highlights"):
            st.session_state.pop(f"{field}-{pending_copy['row_key']}", None)
    st.header("Product listings")
    st.write("Upload a supplier sheet. Dhaga Ops standardizes product details and drafts listing copy for you to check.")
    st.caption("Nothing is published automatically. Each listing stays a draft until you review and approve it.")
    left, right = st.columns([3, 1])
    with left:
        uploaded = st.file_uploader(
            "Supplier sheet (CSV or Excel)",
            type=["csv", "xlsx", "xlsm"],
            key="vendor_upload",
            help="Use one product per row. If a row is malformed, other readable rows will still be processed.",
        )
    with right:
        st.download_button(
            "Download example sheet",
            data=sample_vendor_csv(),
            file_name="dhaga_vendor_sample.csv",
            mime="text/csv",
            width="stretch",
        )
    controls = st.columns([1, 1, 3])
    with controls[0]:
        process_upload = st.button("Process supplier sheet", disabled=uploaded is None, type="primary")
    with controls[1]:
        process_demo = st.button("Load demo batch")
    if process_upload or process_demo:
        try:
            started = time.perf_counter()
            if process_demo:
                records, parse_errors = read_vendor_upload_detailed(
                    sample_vendor_csv(), "demo_vendor.csv", stable_key_prefix="dhaga-demo-catalog"
                )
            else:
                records, parse_errors = read_vendor_upload_detailed(uploaded.getvalue(), uploaded.name)
            if records:
                records = process_catalog_records(records)
            elapsed = time.perf_counter() - started
            for record in records:
                _persist_listing(record)
            st.session_state.catalog_batch = records
            st.session_state.catalog_parse_errors = parse_errors
            st.session_state.catalog_elapsed = elapsed
            st.session_state.catalog_saved = database_ready
        except (ValueError, ValidationError) as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(_friendly_exception(exc, "The supplier sheet"))

    records = st.session_state.get("catalog_batch", [])
    parse_errors = st.session_state.get("catalog_parse_errors", [])
    if parse_errors:
        st.warning(f"{len(parse_errors)} row(s) could not be read. The other readable rows were kept.")
        error_frame = pd.DataFrame(parse_errors).rename(columns={"line": "Row number", "issue": "What needs fixing"})
        st.dataframe(error_frame, width="stretch", hide_index=True)
        st.download_button(
            "Download row error report",
            data=error_frame.to_csv(index=False).encode("utf-8-sig"),
            file_name="dhaga_vendor_row_errors.csv",
            mime="text/csv",
        )
    if database_ready:
        try:
            saved_listings = unapproved_listing_rows()
            if saved_listings:
                with st.expander(f"Open saved product drafts ({len(saved_listings)})", expanded=not records):
                    selected_listing = st.selectbox(
                        "Saved product",
                        options=[row["row_key"] for row in saved_listings],
                        format_func=lambda row_id: next(
                            f"{row['vendor_sku_raw'] or 'No SKU'} · {row['product_name'] or 'Product name missing'} · {row['status'].replace('_', ' ')}"
                            for row in saved_listings
                            if row["row_key"] == row_id
                        ),
                    )
                    if st.button("Open saved drafts", key="open-saved-listings"):
                        st.session_state.catalog_batch = saved_listings
                        st.session_state.catalog_saved = True
                        st.rerun()
        except Exception as exc:
            st.warning(_friendly_exception(exc, "Loading saved product drafts"))
    if not records:
        if not parse_errors:
            st.info("Upload a supplier sheet or load the example batch to begin.")
        return

    total = len(records)
    blocked = sum(record["status"] == "blocked" for record in records)
    review = sum(record["status"] == "needs_review" for record in records)
    c1, c2, c3 = st.columns(3)
    c1.metric("Products received", total)
    c2.metric("Need required details", blocked)
    c3.metric("Time to prepare", f"{st.session_state.get('catalog_elapsed', 0):.1f}s")
    if st.session_state.get("catalog_saved"):
        st.caption("Draft rows are saved to the staging database. Approval is recorded separately.")
    else:
        st.warning("Database is not connected. This batch is only in this browser session and approvals are disabled.")
    if not settings.live_models_enabled:
        st.info("Example mode is on. Sample products and local copy templates are used; no AI service is called.")
    if review:
        st.caption(f"{review} product(s) need a color choice or another review. Open a row marked ‘Needs review’ to continue.")
    for record in records:
        name = record.get("product_name") or record.get("vendor_sku_raw") or "Vendor row"
        status_title = {
            "blocked": "Needs required details",
            "needs_review": "Needs review",
            "approved": "Approved",
            "draft": "Draft",
        }.get(record["status"], record["status"].replace("_", " ").title())
        title = f"{record.get('vendor_sku_raw') or 'No SKU'} · {name} · {status_title}"
        with st.expander(title, expanded=record["status"] == "blocked"):
            _status_badge(record["status"])
            if record.get("inferred_color") and not record.get("standard_color"):
                st.warning(
                    f"Suggested color: {record['inferred_color']}. Choose it only if it matches the supplier sheet. "
                    + record.get("color_inference_reason", "")
                )
            if record["issues"]:
                for issue in record["issues"]:
                    st.warning(issue)
            if record.get("model_warnings"):
                for warning in record["model_warnings"]:
                    st.warning(warning)
            st.caption(record.get("compliance_notes") or "Listing copy has not been checked yet.")
            copy = record.get("generated_copy") or {}
            with st.form(f"listing-edit-{record['row_key']}"):
                a, b = st.columns(2)
                with a:
                    vendor_sku = st.text_input(
                        "Vendor SKU (required)",
                        record.get("vendor_sku_raw", ""),
                        key=f"sku-{record['row_key']}",
                    )
                    product_name = st.text_input(
                        "Product name (required)",
                        record.get("product_name", ""),
                        key=f"product-{record['row_key']}",
                    )
                    current_color = record.get("standard_color") or "Needs confirmation"
                    color_options = [color.value for color in MasterColor] + ["Needs confirmation"]
                    chosen_color = st.selectbox(
                        "Standard color",
                        color_options,
                        index=color_options.index(current_color) if current_color in color_options else len(color_options) - 1,
                        key=f"color-{record['row_key']}",
                    )
                    fabric_options = ["Choose a fabric"]
                    fabric_options.extend(COMMON_FABRICS)
                    current_fabric = record.get("fabric_composition", "")
                    if current_fabric and current_fabric not in fabric_options:
                        fabric_options.insert(1, current_fabric)
                    current_fabric_option = current_fabric if current_fabric in fabric_options else "Choose a fabric"
                    fabric_choice = st.selectbox(
                        "Fabric or material (required)",
                        fabric_options,
                        index=fabric_options.index(current_fabric_option),
                        key=f"fabric-{record['row_key']}",
                    )
                    if fabric_choice == "Other — enter below":
                        fabric = st.text_input("Enter fabric or material", key=f"fabric-other-{record['row_key']}")
                    elif fabric_choice == "Choose a fabric":
                        fabric = ""
                    else:
                        fabric = fabric_choice
                    fit = st.text_input("Fit or shape", record.get("fit_silhouette", ""), key=f"fit-{record['row_key']}")
                with b:
                    care = st.text_input("Wash or care instructions", record.get("wash_care", ""), key=f"care-{record['row_key']}")
                    size_values = st.text_input(
                        "Sizes",
                        record.get("size_values", ""),
                        key=f"sizes-{record['row_key']}",
                        help="Common names such as Extra Small and 2XL are standardized to XS and XXL.",
                    )
                    occasion_text = st.text_input(
                        "Where customers may wear it (separate with commas)",
                        ", ".join(record.get("occasion_tags", [])),
                        key=f"occasion-{record['row_key']}",
                    )
                    title_edit = st.text_input(
                        "Product title (Hinglish)", copy.get("title_hinglish", ""), key=f"title-{record['row_key']}"
                    )
                description = st.text_area(
                    "Product description (Hinglish)",
                    copy.get("description_hinglish", ""),
                    height=100,
                    key=f"description-{record['row_key']}",
                )
                highlights = st.text_area(
                    "Product highlights (one per line)",
                    "\n".join(copy.get("key_highlights", [])),
                    height=90,
                    key=f"highlights-{record['row_key']}",
                )
                human_checked = st.checkbox(
                    "I checked these details and copy against the supplier sheet",
                    key=f"attest-{record['row_key']}",
                )
                save_edits = st.form_submit_button("Save edits for later", disabled=not database_ready)
                save_approval = st.form_submit_button(
                    "Save and approve for staging",
                    type="primary",
                    disabled=not database_ready or record["status"] == "approved",
                )
            if save_edits or save_approval:
                try:
                    candidate = deepcopy(record)
                    candidate["vendor_sku_raw"] = vendor_sku.strip()
                    candidate["product_name"] = product_name.strip()
                    candidate["standard_color"] = "" if chosen_color == "Needs confirmation" else chosen_color
                    candidate["fabric_composition"] = fabric.strip()
                    candidate["fit_silhouette"] = fit.strip()
                    candidate["wash_care"] = care.strip()
                    candidate["size_values"] = normalize_size_values(size_values)
                    candidate["occasion_tags"] = [item.strip() for item in occasion_text.split(",") if item.strip()]
                    candidate["normalized_payload"].update(
                        {
                            "vendor_sku_raw": candidate["vendor_sku_raw"],
                            "product_name": candidate["product_name"],
                            "standard_color": candidate["standard_color"],
                            "fabric_composition": candidate["fabric_composition"],
                            "fit_silhouette": candidate["fit_silhouette"],
                            "wash_care": candidate["wash_care"],
                            "size_values": candidate["size_values"],
                            "occasion_tags": candidate["occasion_tags"],
                        }
                    )
                    candidate["generated_copy"] = {
                        **copy,
                        "title_hinglish": title_edit.strip(),
                        "description_hinglish": description.strip(),
                        "key_highlights": [line.strip() for line in highlights.splitlines() if line.strip()],
                    }
                    copy_needs_first_review = not title_edit.strip() or not description.strip()
                    if copy_needs_first_review:
                        template = _deterministic_copy(candidate)
                        if not title_edit.strip():
                            candidate["generated_copy"]["title_hinglish"] = template["title_hinglish"]
                        if not description.strip():
                            candidate["generated_copy"]["description_hinglish"] = template["description_hinglish"]
                        if not candidate["generated_copy"].get("key_highlights"):
                            candidate["generated_copy"]["key_highlights"] = template["key_highlights"]
                    if not candidate.get("vendor_fabric_source") and candidate["fabric_composition"] and human_checked:
                        candidate["vendor_fabric_source"] = candidate["fabric_composition"]
                        candidate["normalized_payload"]["vendor_fabric_source"] = candidate["vendor_fabric_source"]
                    candidate["issues"] = [
                        issue
                        for issue in candidate["issues"]
                        if not ((issue.startswith("Add the fabric") or issue.startswith("Mandatory missing")) and candidate["fabric_composition"])
                        and not ((issue.startswith("Add the supplier SKU") or issue.startswith("Missing vendor SKU")) and candidate["vendor_sku_raw"])
                        and not ((issue.startswith("Add the product name") or issue.startswith("Missing product name")) and candidate["product_name"])
                        and not ((issue.startswith(("Choose the standard color", "Choose a standard color")) or issue.startswith(("Unknown vendor shade", "Color missing"))) and candidate["standard_color"])
                    ]
                    candidate["compliance_passed"], candidate["compliance_notes"] = _deterministic_copy_check(
                        candidate, candidate["generated_copy"]
                    )
                    required_missing = (
                        not candidate["vendor_sku_raw"]
                        or not candidate["product_name"]
                        or not candidate["fabric_composition"]
                        or not candidate["standard_color"]
                    )
                    if save_edits:
                        if not candidate["vendor_sku_raw"] and not any(issue.startswith("Add the supplier SKU") for issue in candidate["issues"]):
                            candidate["issues"].append("Add the supplier SKU before approval.")
                        if not candidate["product_name"] and not any(issue.startswith("Add the product name") for issue in candidate["issues"]):
                            candidate["issues"].append("Add the product name before approval.")
                        if not candidate["fabric_composition"] and not any(issue.startswith("Add the fabric") for issue in candidate["issues"]):
                            candidate["issues"].append("Add the fabric or material before approval.")
                        if not candidate["standard_color"] and not any(issue.startswith(("Choose the standard color", "Choose a standard color")) for issue in candidate["issues"]):
                            candidate["issues"].append("Choose a standard color before approval.")
                        candidate["status"] = "blocked" if required_missing else "needs_review" if candidate["issues"] or not candidate["compliance_passed"] else "draft"
                        _persist_listing(candidate)
                        record.update(candidate)
                        if copy_needs_first_review:
                            st.session_state.pending_listing_copy = {
                                "row_key": candidate["row_key"],
                                "title": candidate["generated_copy"]["title_hinglish"],
                                "description": candidate["generated_copy"]["description_hinglish"],
                                "highlights": "\n".join(candidate["generated_copy"].get("key_highlights", [])),
                            }
                            st.session_state.pending_attestation_reset = candidate["row_key"]
                        st.success("Your edits are saved. Review the listing copy, then approve it when it is ready.")
                        st.rerun()
                    missing_details = []
                    if not candidate["vendor_sku_raw"]:
                        missing_details.append("supplier SKU")
                    if not candidate["product_name"]:
                        missing_details.append("product name")
                    if not candidate["fabric_composition"]:
                        missing_details.append("fabric or material")
                    if not candidate["standard_color"]:
                        missing_details.append("confirmed standard color")
                    if missing_details:
                        st.error("Cannot approve yet. Add or choose: " + ", ".join(missing_details) + ".")
                    elif not human_checked:
                        st.error("Check the supplier details and listing copy before approving.")
                    elif copy_needs_first_review:
                        candidate["status"] = "needs_review"
                        _persist_listing(candidate)
                        record.update(candidate)
                        st.session_state.pending_listing_copy = {
                            "row_key": candidate["row_key"],
                            "title": candidate["generated_copy"]["title_hinglish"],
                            "description": candidate["generated_copy"]["description_hinglish"],
                            "highlights": "\n".join(candidate["generated_copy"].get("key_highlights", [])),
                        }
                        st.session_state.pending_attestation_reset = candidate["row_key"]
                        st.info("A first copy draft has been prepared from these details. Review it before approving.")
                        st.rerun()
                    elif not candidate["compliance_passed"]:
                        record.update(candidate)
                        record["status"] = "needs_review"
                        _persist_listing(record)
                        st.error("The copy includes a material or care claim that is not supported by the supplier sheet. Edit it and check again before approval.")
                    elif not candidate["generated_copy"]["title_hinglish"].strip() or not candidate["generated_copy"]["description_hinglish"].strip():
                        st.error("Add a product title and description before approval.")
                    elif candidate["issues"]:
                        st.error("Resolve the remaining row issues before approval.")
                    else:
                        candidate["status"] = "approved"
                        approve_listing(candidate["row_key"], candidate["generated_copy"], record=candidate)
                        record.update(candidate)
                        st.success("Listing approved for staging. It has not been published to a store.")
                        st.rerun()
                except Exception as exc:
                    st.error(_friendly_exception(exc, "Saving the listing"))

    export_frame = pd.DataFrame(
        [
            {
                "sku": row["vendor_sku_raw"],
                "product": row["product_name"],
                "color": row["standard_color"],
                "fabric": row["fabric_composition"],
                "title_hinglish": (row.get("generated_copy") or {}).get("title_hinglish", ""),
                "status": row["status"],
            }
            for row in records
        ]
    )
    st.download_button(
        "Download this batch for review",
        data=export_frame.to_csv(index=False).encode("utf-8-sig"),
        file_name="dhaga_catalog_drafts.csv",
        mime="text/csv",
    )


def _cx_workspace() -> None:
    st.header("Customer messages")
    st.write("Paste a customer message to check its intent, look up a demo shipment, and prepare a reply for an agent to review.")
    st.caption("The sample orders and policies are examples only. No courier lookup or customer message is sent to a live service.")
    if database_ready:
        try:
            saved_cases = recent_support_cases()
            if saved_cases:
                with st.expander(f"Open a saved customer case ({len(saved_cases)})", expanded=False):
                    selected_case_id = st.selectbox(
                        "Saved case",
                        options=[case["case_id"] for case in saved_cases],
                        format_func=lambda case_id: next(
                            f"{case.get('order_id') or 'No order'} · {case['status'].replace('_', ' ')} · {case['ticket_text'][:45]}"
                            for case in saved_cases
                            if case["case_id"] == case_id
                        ),
                    )
                    if st.button("Open saved case", key="open-saved-case"):
                        st.session_state.support_case = next(
                            case for case in saved_cases if case["case_id"] == selected_case_id
                        )
                        st.rerun()
        except Exception as exc:
            st.warning(_friendly_exception(exc, "Loading saved customer cases"))
    examples = demo_tickets()
    example_names = [example["scenario"] for example in examples]
    selected_example = st.selectbox("Try a sample customer message", ["Choose an example…", *example_names])
    if st.button("Use selected example", disabled=selected_example == "Choose an example…"):
        selected = next(example for example in examples if example["scenario"] == selected_example)
        st.session_state.cx_ticket_text = selected["message"]
        st.rerun()
    with st.expander("Demo tracking fixtures", expanded=False):
        st.write("Use one of these demo order IDs: " + ", ".join(demo_order_ids()))
        if demo_phone_numbers():
            st.write("Example registered phone: " + ", ".join(demo_phone_numbers()))
        st.caption("These are synthetic example records. No live Delhivery, Shiprocket, Ekart, Freshdesk, or WhatsApp systems are connected.")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Scenario": example["scenario"],
                        "Order ID": example["order_id"] or "Needs identifier",
                        "Sample customer message": example["message"],
                    }
                    for example in demo_tickets()
                ]
            ),
            width="stretch",
            hide_index=True,
        )

    with st.form("cx-triage"):
        ticket_text = st.text_area(
            "Customer message",
            placeholder="Example: bhaiya mera order 84920 kahan hai? abhi tak nahi mila",
            height=120,
            key="cx_ticket_text",
            help="Paste the customer's words. You can add an order ID or registered phone below if it is missing from the message.",
        )
        c1, c2 = st.columns(2)
        order_override = c1.text_input("Order ID (optional)")
        phone_override = c2.text_input("Registered phone (optional)", help="Use the phone number linked to the order.")
        submitted = st.form_submit_button("Check message", type="primary")
    if submitted:
        result = process_customer_ticket(ticket_text, order_override, phone_override)
        try:
            _persist_support(result)
            result["saved"] = database_ready
        except Exception as exc:
            result["save_error"] = _friendly_exception(exc, "Saving the customer message")
            result["saved"] = False
        st.session_state.support_case = result

    result = st.session_state.get("support_case")
    if not result:
        return
    st.divider()
    _status_badge(result.get("status", "draft"))
    if result.get("error"):
        if result["status"] in {"sync_failed", "not_found"}:
            st.error(result["error"])
        elif result["status"] == "blocked":
            st.error(result["error"])
        else:
            st.warning(result["error"])
    if result.get("model_warnings"):
        for warning in result["model_warnings"]:
            st.warning(warning)
    if result.get("parsed_query"):
        parsed = result["parsed_query"]
        col1, col2, col3 = st.columns(3)
        intent_labels = {
            "WISMO": "Order tracking",
            "RETURN_REQUEST": "Return or exchange",
            "CANCELLATION": "Cancellation",
            "ESCALATION": "Agent review",
            "OTHER": "Agent review",
        }
        col1.metric("Message type", intent_labels.get(parsed.get("detected_intent", ""), "Needs review"))
        col2.metric("Order ID", result.get("order_id") or parsed.get("order_id") or "Missing")
        col3.metric("Language", parsed.get("language", ""))
    facts = result.get("carrier_facts")
    if facts:
        st.subheader("Verified carrier record")
        f1, f2, f3, f4 = st.columns(4)
        f1.metric("Carrier", facts["carrier_name"])
        f2.metric("Status", facts["current_status"])
        f3.metric("Transit", f"{facts['days_in_transit']} days")
        f4.metric("Expected delivery", facts.get("promised_delivery_date") or "Not available")
        st.caption(
            f"Latest location: {facts['current_location']} · Destination: {facts['destination_city']} · "
            f"Payment: {facts['payment_mode']} · Tracking number: {facts['awb']}"
        )
        if facts.get("is_delayed"):
            st.warning("This shipment has been in transit for more than four days. An agent must follow up after reviewing the draft.")
        if facts.get("tracking_url"):
            st.link_button("Open carrier tracking site", facts["tracking_url"])
    policies = result.get("policy_references", [])
    if policies:
        st.subheader("Retrieved policy clauses")
        for policy in policies:
            with st.expander(f"{policy['policy_id']} · {policy['title']} · match {policy['score']}"):
                st.write(policy["text"])
    if result.get("draft_reply"):
        st.subheader("Draft reply")
        reply = st.text_area("Edit before handoff", value=result["draft_reply"], height=150, key=f"reply-{result['case_id']}")
        facts = result.get("carrier_facts") or {}
        reply_passed, reply_notes = _deterministic_reply_check(reply, facts)
        if reply_passed:
            st.success(reply_notes)
        else:
            st.warning(reply_notes)
        if result.get("requires_human_escalation"):
            st.info("This handoff is for an agent to follow up. It does not authorize an automatic customer reply.")
        st.caption("Approval saves this for an agent to handle. It does not send a message to the customer.")
        allowed_status = result.get("status") in {"draft_ready", "needs_identifier", "needs_review"}
        can_approve = database_ready and allowed_status and reply_passed
        attested = st.checkbox("I checked the facts and approve this for agent handoff", key=f"cx-attest-{result['case_id']}")
        approval_label = "Approve for agent follow-up" if result.get("requires_human_escalation") else "Approve for agent handoff"
        if st.button(approval_label, type="primary", disabled=not can_approve or not attested):
            try:
                result["draft_reply"] = reply
                result["factual_verification_passed"] = reply_passed if facts else None
                result["verification_notes"] = reply_notes
                result["status"] = "draft_ready" if facts else "needs_identifier"
                approve_support_case(result["case_id"], reply, record=result)
                result["status"] = "approved_for_handoff"
                result["saved"] = True
                st.success("Agent handoff approved and saved. No customer message was sent.")
                st.rerun()
            except Exception as exc:
                st.error(_friendly_exception(exc, "Approving the agent handoff"))
    if result.get("requires_human_escalation"):
        st.warning(result.get("escalation_reason") or "An agent must review this case before replying to the customer.")
    if result.get("save_error"):
        st.warning(result["save_error"])
    elif result.get("saved"):
        st.caption("Case draft saved in the staging database.")
    if not database_ready:
        st.warning("The triage result is not persisted. Connect the database before using approvals or shared queues.")


def _exports_workspace() -> None:
    st.header("Approved work")
    st.write("Download records that an operator approved for staging or agent handoff.")
    if not database_ready:
        st.warning("Connect PostgreSQL to browse shared approvals.")
        return
    try:
        listings, cases = approved_export_rows()
    except Exception as exc:
        st.error(_friendly_exception(exc, "Loading approved work"))
        return
    a, b = st.columns(2)
    with a:
        st.subheader("Approved listings")
        if listings:
            st.dataframe(pd.DataFrame(listings), width="stretch", hide_index=True)
        else:
            st.info("No listings have been approved for staging yet.")
        st.download_button(
            "Download listings CSV",
            data=pd.DataFrame(listings).to_csv(index=False).encode("utf-8-sig"),
            file_name="dhaga_approved_listings.csv",
            mime="text/csv",
            disabled=not listings,
        )
    with b:
        st.subheader("Approved CX handoffs")
        if cases:
            st.dataframe(pd.DataFrame(cases), width="stretch", hide_index=True)
        else:
            st.info("No customer cases have been approved for agent follow-up yet.")
        st.download_button(
            "Download CX handoffs CSV",
            data=pd.DataFrame(cases).to_csv(index=False).encode("utf-8-sig"),
            file_name="dhaga_approved_cx_handoffs.csv",
            mime="text/csv",
            disabled=not cases,
        )


st.title("Dhaga Ops")
st.caption("Prepare product listings and customer replies for a human to review")

if not database_ready:
    if settings.is_vercel:
        st.error(database_error)
    else:
        st.warning(f"Database is unavailable: {database_error}. Workflows will remain session-only.")
elif is_database_persistent():
    st.success("PostgreSQL connected · shared staging and audit records enabled")
else:
    st.info("Local SQLite connected · approvals are stored on this machine only.")

if not settings.app_password:
    st.warning("No shared password is configured. Set DHAGA_APP_PASSWORD before sharing a public deployment.")
if settings.live_models_enabled:
    st.caption(f"Live model mode · extraction/evaluation: {settings.gemini_fast_model} · copy: {settings.gemini_creative_model}")
    st.warning("Gemini live mode sends the current product or customer-message context to Google. Use synthetic data for free-tier demos.")
else:
    st.caption("Demo model mode · local rules and template drafts are active")
    if settings.model_mode == "live" and not settings.gemini_api_key:
        st.warning("Gemini live mode was selected, but GEMINI_API_KEY is missing. Add a key to enable live model calls; example logic is active for now.")

workspace = st.sidebar.radio("Choose a task", ["Overview", "Product listings", "Customer messages", "Approved work"], key="workspace")
st.sidebar.caption("Example mode uses sample orders and policies. Confirm all policies with Dhaga before customer use.")

if workspace == "Overview":
    st.header("Welcome to Dhaga Ops")
    st.write("Use the two work areas below to prepare supplier product listings and customer support replies. A person reviews each item before it moves to staging.")
    if not st.session_state.get("quick_start_dismissed", False):
        with st.container(border=True):
            guide_title, guide_action = st.columns([5, 1])
            with guide_title:
                st.subheader("Quick start")
                st.write("You can try the app without a demo or any live Dhaga account.")
            with guide_action:
                if st.button("Hide guide", key="hide-quick-start"):
                    st.session_state.quick_start_dismissed = True
                    st.rerun()
            step1, step2, step3 = st.columns(3)
            step1.markdown("**1. Choose a task**\n\nProduct listings or customer messages.")
            step2.markdown("**2. Use sample data or your own**\n\nThe sample data is clearly marked and safe to explore.")
            step3.markdown("**3. Check and approve**\n\nNothing is published or sent automatically.")
            guide_left, guide_right = st.columns(2)
            guide_left.button(
                "Start with product listings",
                type="primary",
                width="stretch",
                on_click=_switch_workspace,
                args=("Product listings",),
            )
            guide_right.button(
                "Start with customer messages",
                width="stretch",
                on_click=_switch_workspace,
                args=("Customer messages",),
            )
    st.subheader("Choose what you need to do")
    left, right = st.columns(2)
    with left:
        st.markdown("### Prepare product listings")
        st.write("Upload a supplier sheet, confirm product details and color, then review the Hinglish listing copy.")
        st.button(
            "Open product listings",
            width="stretch",
            on_click=_switch_workspace,
            args=("Product listings",),
        )
    with right:
        st.markdown("### Prepare a customer reply")
        st.write("Paste a customer message, check an example shipment, and prepare a reply or agent follow-up for review.")
        st.button(
            "Open customer messages",
            width="stretch",
            on_click=_switch_workspace,
            args=("Customer messages",),
        )
    st.info("Example mode uses sample supplier rows, shipments and policies. It does not connect to live Dhaga, courier, catalog or messaging systems.")
    st.caption("Weekly volumes and response-time figures in the supplied case brief are planning baselines, not live app measurements.")
elif workspace == "Product listings":
    _catalog_workspace()
elif workspace == "Customer messages":
    _cx_workspace()
else:
    _exports_workspace()
