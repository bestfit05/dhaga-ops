from __future__ import annotations

import time
import logging
from copy import deepcopy
from html import escape
from pathlib import Path
from datetime import datetime
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
    refresh_catalog_validation,
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
    get_listing_rows,
    workspace_counts,
)
from dhaga_os.exports import csv_export_bytes as _csv_export, safe_spreadsheet_frame
from dhaga_os.models import MasterColor
from dhaga_os.navigation import WORKSPACES, WORKSPACE_KEY, prepare_workspace_widget, request_workspace

st.set_page_config(page_title="Dhaga Ops · Team workspace", page_icon="🧵", layout="wide", initial_sidebar_state="auto")
st.markdown("<style>" + (Path(__file__).parent / "assets/dhaga.css").read_text() + "</style>", unsafe_allow_html=True)

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
    st.markdown('<div class="eyebrow">DHAGA & CO · TEAM WORKSPACE</div><h1 class="page-title">Welcome back.</h1><p class="page-description">Prepare product listings and customer replies in one place.</p>', unsafe_allow_html=True)
    st.caption("Enter the team password to open your workspace.")
    with st.form("login"):
        candidate = st.text_input("Team password", type="password", help="Use the password shared by your Dhaga Ops administrator.")
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
    logger.exception("Could not initialize shared work storage")
    database_error = "Could not open shared work storage. Check its connection and try again."


def _status_badge(status: str) -> None:
    labels = {
        "draft": ("Draft", "info"),
        "needs_review": ("Needs review", "warning"),
        "blocked": ("Needs more details", "error"),
        "approved": ("Approved for internal review", "success"),
        "draft_ready": ("Order details checked · review the reply", "success"),
        "needs_identifier": ("An order number or linked phone is needed", "warning"),
        "not_found": ("No sample order matches that number", "warning"),
        "sync_failed": ("Could not check the sample order", "error"),
        "approved_for_handoff": ("Reply approved and saved for the team", "success"),
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
    return f"{action} could not be completed. Your form entries are still here; try again or ask the app administrator."


def _switch_workspace(workspace: str) -> None:
    """Defer navigation until before Streamlit creates the sidebar radio."""
    request_workspace(st.session_state, workspace)


def _show_table(data: pd.DataFrame, **options: Any) -> None:
    # Streamlit's table toolbar also offers CSV downloads; protect those cells.
    st.dataframe(safe_spreadsheet_frame(data), **options)


def _actor() -> str:
    return st.session_state.get("operator_name", "").strip() or "operator"


def _flash(message: str) -> None:
    st.session_state.flash_message = message


def _select_product(key: str) -> None:
    st.session_state.pending_product_key = key


def _reset_reply_review(case_id: str) -> None:
    st.session_state[f"cx-attest-{case_id}"] = False


def _page_header(eyebrow: str, title: str, description: str) -> None:
    st.markdown(f'<div class="eyebrow">{escape(eyebrow)}</div><h1 class="page-title">{escape(title)}</h1><p class="page-description">{escape(description)}</p>', unsafe_allow_html=True)


def _empty(title: str, description: str) -> None:
    st.markdown(f'<div class="empty-state"><div class="empty-title">{escape(title)}</div><div class="empty-copy">{escape(description)}</div></div>', unsafe_allow_html=True)


def _steps(labels: list[str], active: int) -> None:
    st.markdown('<div class="step-bar">' + ''.join(f'<span class="step{ " active" if i == active else ""}">{i+1} · {escape(label)}</span>' for i, label in enumerate(labels)) + '</div>', unsafe_allow_html=True)


def _status_label(status: str) -> str:
    return {"draft": "Ready to review", "needs_review": "Needs review", "blocked": "Details missing", "approved": "Approved", "draft_ready": "Reply ready to review", "needs_identifier": "Order number needed", "not_found": "Order not found", "sync_failed": "Tracking unavailable", "approved_for_handoff": "Approved for team", "manual_review": "Team follow-up needed"}.get(status, status.replace("_", " ").title())


def _display_date(value: str | None) -> str:
    if not value:
        return "Not confirmed"
    try:
        return datetime.fromisoformat(value).strftime("%d %b %Y")
    except ValueError:
        return value


def _catalog_workspace() -> None:
    reset_attestation_for = st.session_state.pop("pending_attestation_reset", None)
    if reset_attestation_for:
        st.session_state.pop(f"attest-{reset_attestation_for}", None)
    pending_copy = st.session_state.pop("pending_listing_copy", None)
    if pending_copy:
        for field in ("title", "description", "highlights"):
            st.session_state.pop(f"{field}-{pending_copy['row_key']}", None)
    _page_header("CATALOG WORKSPACE", "Make every product ready.", "Check supplier details, review the listing text, and approve one product at a time.")
    records = st.session_state.get("catalog_batch", [])
    _steps(["Load a supplier sheet", "Review each product", "Approve & download"], 1 if records else 0)
    with st.expander("Add a supplier sheet or try sample products", expanded=not records):
        left, right = st.columns([2, 1], gap="large")
        with left:
            uploaded = st.file_uploader("Supplier product sheet", type=["csv", "xlsx", "xlsm"], key="vendor_upload", help="CSV or Excel, up to 5 MB. One product per row. Required: supplier code, product name, color and fabric.")
            process_upload = st.button("Check supplier sheet", disabled=uploaded is None, type="primary", width="stretch")
        with right:
            st.markdown("**Just exploring?**")
            st.caption("Try 26 sample products, including a few that need fixing.")
            process_demo = st.button("Load sample products", width="stretch")
            st.download_button("Download example sheet", data=sample_vendor_csv(), file_name="dhaga_vendor_sample.csv", mime="text/csv", width="stretch")
        with st.expander("What should my sheet include?"):
            st.write("Use columns for supplier code (SKU), product name, color and fabric. Add sizes, care, fit, price and occasions when available. Common column names are recognized automatically.")
            st.caption("A missing detail stays visible for you to fix. The app keeps readable rows if another row has an error.")
    if process_upload or process_demo:
        try:
            with st.spinner("Reading products and preparing the review queue…"):
                started = time.perf_counter()
                records, parse_errors = read_vendor_upload_detailed(sample_vendor_csv(), "demo_vendor.csv", stable_key_prefix="dhaga-demo-catalog") if process_demo else read_vendor_upload_detailed(uploaded.getvalue(), uploaded.name)
                recovered = {row["row_key"]: row for row in get_listing_rows([row["row_key"] for row in records])} if database_ready else {}
                new_rows = process_catalog_records([row for row in records if row["row_key"] not in recovered])
                processed = {row["row_key"]: row for row in new_rows}
                records = [recovered.get(row["row_key"]) or processed[row["row_key"]] for row in records]
                saved = database_ready
                for record in new_rows:
                    try:
                        _persist_listing(record)
                    except Exception as exc:
                        logger.exception("Could not save imported product draft")
                        saved = False
                st.session_state.catalog_batch = records
                st.session_state.catalog_parse_errors = parse_errors
                st.session_state.catalog_elapsed = time.perf_counter() - started
                st.session_state.catalog_saved = database_ready and saved
                st.session_state.pop("review_product", None)
                st.session_state.pop("catalog_search", None)
                st.session_state.pop("catalog_filter", None)
                _flash(f"{len(records)} products in your queue. {len(recovered)} saved versions reopened." if recovered else f"{len(records)} products checked. Start with the products needing attention.")
            st.rerun()
        except (ValueError, ValidationError) as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(_friendly_exception(exc, "Checking the supplier sheet"))
    parse_errors = st.session_state.get("catalog_parse_errors", [])
    if parse_errors:
        with st.expander(f"{len(parse_errors)} unreadable rows · download the error report", expanded=True):
            error_frame = pd.DataFrame(parse_errors).rename(columns={"line": "Row number", "issue": "What needs fixing"})
            _show_table(error_frame, width="stretch", hide_index=True)
            st.download_button("Download row error report", data=_csv_export(error_frame), file_name="dhaga_vendor_row_errors.csv", mime="text/csv")
    if database_ready:
        try:
            saved_listings = unapproved_listing_rows(limit=None)
            if saved_listings:
                with st.expander(f"Continue saved product drafts · {len(saved_listings)} waiting", expanded=not records):
                    index = {row["row_key"]: row for row in saved_listings}
                    selected_listing = st.selectbox("Choose a saved product", options=list(index), format_func=lambda row_id: f"{index[row_id]['vendor_sku_raw'] or 'Code missing'} · {index[row_id]['product_name'] or 'Name missing'}")
                    if st.button("Open this draft", key="open-saved-listings"):
                        st.session_state.catalog_batch = saved_listings
                        st.session_state.catalog_saved = True
                        st.session_state.pending_product_key = selected_listing
                        st.session_state.pop("catalog_filter", None)
                        st.session_state.pop("catalog_search", None)
                        st.rerun()
        except Exception as exc:
            st.warning(_friendly_exception(exc, "Loading saved product drafts"))
    if not records:
        _empty("Your product queue starts here.", "Upload a supplier sheet above, or load the sample products to try the full review process.")
        return
    total = len(records)
    approved = sum(row["status"] == "approved" for row in records)
    attention = sum(row["status"] in {"blocked", "needs_review"} for row in records)
    c1, c2, c3 = st.columns(3)
    c1.metric("Products in this batch", total)
    c2.metric("Need attention", attention)
    c3.metric("Approved", f"{approved} / {total}")
    st.progress(approved / total, text=f"{total - approved} products left to review")
    if not st.session_state.get("catalog_saved"):
        st.warning("Some drafts could not be saved. Keep this page open and try saving them again.")
        if database_ready and st.button("Retry saving product drafts"):
            try:
                for row in records:
                    if row["status"] != "approved":
                        _persist_listing(row)
                st.session_state.catalog_saved = True
                _flash("Your product drafts are now saved.")
                st.rerun()
            except Exception as exc:
                st.error(_friendly_exception(exc, "Saving product drafts"))
    search, filters = st.columns([2, 1])
    query = search.text_input("Find a product", placeholder="Search product name or supplier code", key="catalog_search").strip().lower()
    scope = filters.selectbox("Show products", ["All products", "Need attention", "Ready to review", "Approved"], key="catalog_filter")
    filtered = [row for row in records if (not query or query in (row.get("vendor_sku_raw", "") + " " + row.get("product_name", "")).lower()) and (scope == "All products" or scope == "Need attention" and row["status"] in {"blocked", "needs_review"} or scope == "Ready to review" and row["status"] == "draft" or scope == "Approved" and row["status"] == "approved")]
    if not filtered:
        _empty("No products match these filters.", "Clear the search or choose All products to see your queue.")
        return
    priority = {"blocked": 0, "needs_review": 1, "draft": 2, "approved": 3}
    filtered.sort(key=lambda row: priority.get(row["status"], 2))
    row_index = {row["row_key"]: row for row in filtered}
    pending = st.session_state.pop("pending_product_key", None)
    if pending in row_index:
        st.session_state.review_product = pending
    if st.session_state.get("review_product") not in row_index:
        st.session_state.review_product = next(iter(row_index))
    selected = st.selectbox("Product to review", list(row_index), format_func=lambda key: f"{row_index[key].get('vendor_sku_raw') or 'Code missing'} · {row_index[key].get('product_name') or 'Name missing'} · {_status_label(row_index[key]['status'])}", key="review_product")
    position = list(row_index).index(selected)
    prev, count, nxt = st.columns([1, 2, 1])
    prev.button("← Previous product", disabled=position == 0, on_click=_select_product, args=(list(row_index)[max(0, position-1)],), width="stretch")
    count.caption(f"Product {position + 1} of {len(filtered)} in this view · drafts save only when you choose Save draft")
    nxt.button("Next product →", disabled=position == len(filtered)-1, on_click=_select_product, args=(list(row_index)[min(len(filtered)-1, position+1)],), width="stretch")
    with st.expander("View the full batch"):
        _show_table(pd.DataFrame([{"Supplier code": row.get("vendor_sku_raw"), "Product": row.get("product_name"), "Color": row.get("standard_color") or "Choose a color", "Status": _status_label(row["status"])} for row in filtered]), hide_index=True, width="stretch")
        st.download_button("Download this batch for review", _csv_export(pd.DataFrame([{ "sku": row.get("vendor_sku_raw"), "product": row.get("product_name"), "color": row.get("standard_color"), "fabric": row.get("fabric_composition"), "price": row.get("price", ""), "sizes": row.get("size_values", ""), "care": row.get("wash_care", ""), "title_hinglish": (row.get("generated_copy") or {}).get("title_hinglish", ""), "description_hinglish": (row.get("generated_copy") or {}).get("description_hinglish", ""), "highlights": " | ".join((row.get("generated_copy") or {}).get("key_highlights", [])), "status": _status_label(row["status"]) } for row in records])), "dhaga_catalog_drafts.csv", "text/csv")
    record = row_index[selected]
    with st.expander("Supplier's original details · compare before approving"):
        st.caption(record.get("source_filename", "Supplier sheet"))
        _show_table(pd.DataFrame([{"Field": str(k).replace("_", " ").title(), "Supplier value": str(v)} for k, v in record.get("raw_payload", {}).items()]), hide_index=True, width="stretch")
    if record["status"] == "approved":
        st.success("This product is approved and saved. Download it from Saved approvals.")
        copy = record.get("generated_copy") or {}
        st.subheader(copy.get("title_hinglish", record.get("product_name", "Product")))
        st.write(copy.get("description_hinglish", ""))
        for point in copy.get("key_highlights", []):
            st.write("• " + point)
        return
    with st.container(border=True):
        _status_badge(record["status"])
        if record.get("inferred_color") and not record.get("standard_color"):
            st.warning(
                f"Color suggestion: {record['inferred_color']}. Use it only if it matches the supplier sheet. "
                + record.get("color_inference_reason", "")
            )
        if record["issues"]:
            for issue in record["issues"]:
                plain_issue = issue.replace("supplier SKU", "supplier code").replace("standard color", "product color")
                st.warning(plain_issue)
        if record.get("model_warnings"):
            for warning in record["model_warnings"]:
                st.warning(warning)
        notes = record.get("compliance_notes") or "Listing text has not been checked yet."
        st.caption(notes.replace("Offline rule check only.", "Material and care checks complete.").replace("deterministic check", "source comparison"))
        copy = record.get("generated_copy") or {}
        with st.form(f"listing-edit-{record['row_key']}"):
            st.subheader("Product details")
            a, b = st.columns(2)
            with a:
                vendor_sku = st.text_input(
                    "Supplier code (required)",
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
                    "Product color",
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
                custom_fabric = st.text_input("Other fabric (fill only when choosing Other)", key=f"fabric-other-{record['row_key']}")
                fabric = custom_fabric if fabric_choice == "Other — enter below" else "" if fabric_choice == "Choose a fabric" else fabric_choice
            with b:
                price = st.text_input("Price in rupees (optional)", str(record.get("price", "")), key=f"price-{record['row_key']}", help="Enter a positive amount without a currency symbol, for example 899.")
                fit = st.text_input("Fit or shape", record.get("fit_silhouette", ""), key=f"fit-{record['row_key']}")
                care = st.text_input("Wash or care instructions", record.get("wash_care", ""), key=f"care-{record['row_key']}")
                size_values = st.text_input(
                    "Sizes",
                    record.get("size_values", ""),
                    key=f"sizes-{record['row_key']}",
                    help="Common names such as Extra Small and 2XL are changed to XS and XXL.",
                )
                occasion_text = st.text_input(
                    "Where to wear it (separate with commas)",
                    ", ".join(record.get("occasion_tags", [])),
                    key=f"occasion-{record['row_key']}",
                )
            st.divider()
            st.subheader("Listing text")
            st.caption("The title and description are drafted in simple Hindi-English. Check or edit them before approval.")
            title_edit = st.text_input(
                "Product title", copy.get("title_hinglish", ""), key=f"title-{record['row_key']}"
            )
            description = st.text_area(
                "Product description",
                copy.get("description_hinglish", ""),
                height=110,
                key=f"description-{record['row_key']}",
            )
            highlights = st.text_area(
                "Product highlights (one per line)",
                "\n".join(copy.get("key_highlights", [])),
                height=90,
                key=f"highlights-{record['row_key']}",
            )
            human_checked = st.checkbox(
                "I compared these details and listing text with the supplier sheet",
                key=f"attest-{record['row_key']}",
            )
            save_edits = st.form_submit_button("Save draft", disabled=not database_ready)
            save_approval = st.form_submit_button(
                "Approve product",
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
                candidate["price"] = price.strip()
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
                if human_checked:
                    candidate["normalized_payload"]["human_source_verified"] = True
                    if not candidate.get("vendor_care_source"):
                        candidate["vendor_care_source"] = candidate["wash_care"]
                        candidate["normalized_payload"]["vendor_care_source"] = candidate["wash_care"]
                else:
                    candidate["normalized_payload"]["human_source_verified"] = False
                refresh_catalog_validation(candidate)
                required_missing = any(not candidate.get(field) for field in ("vendor_sku_raw", "product_name", "fabric_composition", "standard_color"))
                if save_edits:
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
                    _flash("Your edits are saved. Review the listing text, then approve when it is ready.")
                    st.rerun()
                missing_details = []
                if not candidate["vendor_sku_raw"]:
                    missing_details.append("supplier code")
                if not candidate["product_name"]:
                    missing_details.append("product name")
                if not candidate["fabric_composition"]:
                    missing_details.append("fabric or material")
                if not candidate["standard_color"]:
                    missing_details.append("confirmed product color")
                if missing_details:
                    st.error("Cannot approve yet. Add or choose: " + ", ".join(missing_details) + ".")
                elif not human_checked:
                    st.error("Check the supplier details and listing text before approving.")
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
                    _flash("A listing draft has been prepared from these details. Review it before approving.")
                    st.rerun()
                elif not candidate["compliance_passed"]:
                    record.update(candidate)
                    record["status"] = "needs_review"
                    _persist_listing(record)
                    st.error(candidate.get("compliance_notes") or "The listing text needs a factual review. Compare it with the supplier details and edit it before approval.")
                elif not candidate["generated_copy"]["title_hinglish"].strip() or not candidate["generated_copy"]["description_hinglish"].strip():
                    st.error("Add a product title and description before approval.")
                elif candidate["issues"]:
                    st.error("Resolve the remaining row issues before approval.")
                else:
                    candidate["status"] = "approved"
                    approve_listing(candidate["row_key"], candidate["generated_copy"], actor=_actor(), record=candidate)
                    record.update(candidate)
                    _flash("Product approved. It is ready in Saved approvals.")
                    st.rerun()
            except (ValueError, ValidationError) as exc:
                st.error(str(exc))
            except Exception as exc:
                st.error(_friendly_exception(exc, "Saving the listing"))


def _load_example(message: str) -> None:
    st.session_state.cx_ticket_text = message
    st.session_state.cx_order_override = ""
    st.session_state.cx_phone_override = ""
    st.session_state.pop("support_case", None)


def _cx_workspace() -> None:
    _page_header("CUSTOMER CARE", "Give every customer a clear reply.", "Paste a message, check the order facts, and prepare a reply for your team.")
    _steps(["Add the message", "Check facts & edit reply", "Save for your team"], 1 if st.session_state.get("support_case") else 0)
    if database_ready:
        try:
            saved_cases = recent_support_cases(limit=None)
            if saved_cases:
                with st.expander(f"Continue saved customer messages · {len(saved_cases)} recent"):
                    lookup = {case["case_id"]: case for case in saved_cases}
                    selected_case_id = st.selectbox("Choose a saved message", list(lookup), format_func=lambda key: f"{lookup[key].get('order_id') or 'No order number'} · {_status_label(lookup[key]['status'])} · {lookup[key]['ticket_text'][:50]}")
                    if st.button("Open this message", key="open-saved-case"):
                        st.session_state.support_case = lookup[selected_case_id]
                        st.session_state.cx_ticket_text = lookup[selected_case_id]["ticket_text"]
                        st.session_state.cx_order_override = ""
                        st.session_state.cx_phone_override = ""
                        st.session_state.pop(f"reply-{selected_case_id}", None)
                        st.session_state.pop(f"cx-attest-{selected_case_id}", None)
                        st.rerun()
        except Exception as exc:
            st.warning(_friendly_exception(exc, "Loading saved customer messages"))
    current_case = st.session_state.get("support_case") or {}
    with st.expander("Customer message & sample scenarios", expanded=not current_case or current_case.get("status") in {"needs_identifier", "not_found"}):
        compose, examples_col = st.columns([2, 1], gap="large")
        with compose:
            with st.form("cx-triage"):
                st.subheader("1. Customer's message")
                ticket_text = st.text_area("Message", placeholder="Example: bhaiya mera order 84920 kahan hai? abhi tak nahi mila", height=120, key="cx_ticket_text", help="Paste the customer's own words. English and Hindi-English are supported.")
                st.caption("If the message has an order number, leave the fields below empty.")
                c1, c2 = st.columns(2)
                order_override = c1.text_input("Order number (optional)", key="cx_order_override")
                phone_override = c2.text_input("Phone number on the order (optional)", key="cx_phone_override")
                submitted = st.form_submit_button("Check order & prepare reply", type="primary", width="stretch")
        with examples_col:
            with st.container(border=True):
                st.subheader("Try a sample message")
                st.caption("Choose an example, then check the order.")
                examples = demo_tickets()
                for index, title in [(2, "Track an order"), (0, "A delivery is late"), (1, "Customer wants to cancel"), (12, "Order number is missing")]:
                    st.button(title, key=f"quick-example-{index}", on_click=_load_example, args=(examples[index]["message"],), width="stretch")
                with st.expander("More sample scenarios"):
                    selected_example = st.selectbox("Scenario", [example["scenario"] for example in examples])
                    selected = next(example for example in examples if example["scenario"] == selected_example)
                    st.button("Load example message", on_click=_load_example, args=(selected["message"],), width="stretch")
                st.caption("Sample orders: " + ", ".join(demo_order_ids()[:4]) + ". Courier data is illustrative.")
    if submitted:
        if not ticket_text.strip():
            st.error("Add the customer's message before checking the order.")
        else:
            try:
                with st.spinner("Checking the order details and preparing a reply…"):
                    result = process_customer_ticket(ticket_text, order_override, phone_override)
                    try:
                        _persist_support(result)
                        result["saved"] = database_ready
                    except Exception as exc:
                        result["save_error"] = _friendly_exception(exc, "Saving the customer message")
                        result["saved"] = False
                    st.session_state.support_case = result
                    st.rerun()
            except (ValueError, ValidationError) as exc:
                st.error(str(exc))
            except Exception as exc:
                st.error(_friendly_exception(exc, "Checking this message"))
    result = st.session_state.get("support_case")
    if not result:
        _empty("A good reply starts with the facts.", "The app checks an order number or linked phone, explains what it found, and prepares wording for your review.")
        return
    st.divider()
    _status_badge(result.get("status", "draft"))
    if result.get("error"):
        st.warning(result["error"])
    if result["status"] in {"needs_identifier", "not_found"}:
        st.info("Next step: add or correct the order number in the message form above, then check the order again.")
    elif result["status"] in {"sync_failed", "manual_review", "blocked"}:
        st.info("Next step: ask a support teammate to verify the order or contact the courier. No reply will be approved automatically.")
    for warning in result.get("model_warnings", []):
        st.warning(warning)
    reply_col, facts_col = st.columns([3, 2], gap="large")
    with facts_col:
        with st.container(border=True):
            st.subheader("Order facts")
            parsed = result.get("parsed_query", {})
            intent = {"WISMO": "Order tracking", "RETURN_REQUEST": "Return or exchange", "CANCELLATION": "Cancellation", "ESCALATION": "Complaint / escalation", "OTHER": "Team review"}.get(parsed.get("detected_intent"), "Needs review")
            st.caption(f"Request: {intent} · Order: {result.get('order_id') or 'Not identified'}")
            facts = result.get("carrier_facts") or {}
            if facts:
                state = facts.get("current_status", "").replace("_", " ").title()
                st.markdown(f"**{state}**")
                st.write("Courier: " + facts["carrier_name"])
                st.write("Expected arrival: " + _display_date(facts.get("promised_delivery_date")))
                st.write("Latest location: " + facts.get("current_location", "Not available"))
                st.write(f"Time since shipping: {facts.get('days_in_transit', 0)} days")
                if facts.get("is_delayed"):
                    st.warning("The expected arrival date has passed. A teammate should follow up with the courier.")
                if facts.get("tracking_url"):
                    st.link_button("Open courier tracking", facts["tracking_url"], width="stretch")
                with st.expander("More order details"):
                    st.write("Tracking number: " + facts.get("awb", ""))
                    st.write("Destination: " + facts.get("destination_city", ""))
                    st.write("Payment: " + facts.get("payment_mode", ""))
                    st.caption("The facts above are from the sample order record. Check the courier before using them for a real customer.")
            else:
                st.caption("No order facts have been confirmed. Avoid promising a delivery date, refund or cancellation.")
            policies = result.get("policy_references", [])
            if policies:
                with st.expander("Example policy references · approval needed"):
                    for policy in policies:
                        st.markdown("**" + policy["title"] + "**")
                        st.write(policy["text"])
                    st.caption("These examples need the Dhaga policy owner's approval before a pilot.")
    with reply_col:
        st.subheader("2. Review the reply")
        with st.expander("Customer message being reviewed"):
            st.write(result["ticket_text"])
        if result.get("status") == "approved_for_handoff":
            st.success("This reply is approved and saved for your team.")
            st.code(result.get("draft_reply", ""), language=None, wrap_lines=True)
            st.caption("Use the copy button on the reply. Sending to the customer happens in your support tool.")
        elif result.get("draft_reply"):
            reply = st.text_area("Reply for your team to review", value=result["draft_reply"], height=220, key=f"reply-{result['case_id']}", on_change=_reset_reply_review, args=(result["case_id"],))
            facts = result.get("carrier_facts") or {}
            reply_passed, reply_notes = _deterministic_reply_check(reply, facts)
            if reply_passed:
                st.caption("Fact check: " + reply_notes)
            else:
                st.warning(reply_notes)
            if result.get("requires_human_escalation"):
                st.warning(result.get("escalation_reason") or "A support teammate must follow up before replying.")
            with st.expander("Copy the current reply"):
                st.code(reply, language=None, wrap_lines=True)
                st.caption("Use the copy icon. Nothing is sent to the customer by this app.")
            attested = st.checkbox("I checked this reply against the order facts", key=f"cx-attest-{result['case_id']}")
            allowed_status = result.get("status") in {"draft_ready", "needs_identifier", "needs_review"}
            save, approve = st.columns(2)
            save_clicked = save.button("Save reply draft", disabled=not database_ready, width="stretch")
            approve_clicked = approve.button("Approve for team", type="primary", disabled=not database_ready or not allowed_status or not reply_passed or not attested or not reply.strip(), width="stretch")
            if not attested:
                st.caption("To approve: check the facts, then tick the confirmation above.")
            if save_clicked or approve_clicked:
                try:
                    candidate = deepcopy(result)
                    candidate["draft_reply"] = reply.strip()
                    candidate["factual_verification_passed"] = reply_passed if facts else None
                    candidate["verification_notes"] = reply_notes
                    if approve_clicked:
                        approve_support_case(candidate["case_id"], reply, actor=_actor(), record=candidate)
                        candidate["status"] = "approved_for_handoff"
                        _flash("Reply approved and saved for your team. No customer message was sent.")
                    else:
                        _persist_support(candidate)
                        _flash("Your edited reply draft is saved. You can return to it later.")
                    candidate["saved"] = True
                    candidate.pop("save_error", None)
                    st.session_state.support_case = candidate
                    st.rerun()
                except (ValueError, ValidationError) as exc:
                    st.error(str(exc))
                except Exception as exc:
                    st.error(_friendly_exception(exc, "Saving this reply"))
        else:
            _empty("A teammate needs to investigate.", result.get("escalation_reason") or "Review the details with your support team before writing a customer reply.")
            handoff = "\n".join([
                "INTERNAL FOLLOW-UP · Do not send as a customer reply",
                "Order: " + (result.get("order_id") or "Not identified"),
                "Customer message: " + result.get("ticket_text", ""),
                "Reason: " + (result.get("escalation_reason") or result.get("error") or "Verify the order and policy before replying."),
                "Next step: a support teammate verifies the order, courier facts and applicable policy.",
            ])
            st.subheader("Internal handoff")
            st.code(handoff, language=None, wrap_lines=True)
            st.download_button("Download follow-up note", data=handoff.encode("utf-8"), file_name="dhaga_follow_up.txt", mime="text/plain")
            st.caption("The case is saved in customer messages for follow-up." if result.get("saved") else "This follow-up has not been saved. Keep this page open.")
        st.caption("Approval saves work for the team. It does not send a customer message.")
    if result.get("save_error"):
        st.warning(result["save_error"])
    if not database_ready:
        st.warning("Saving is unavailable. Keep this page open until the connection is restored.")


def _exports_workspace() -> None:
    _page_header("COMPLETED WORK", "Reviewed. Ready for your team.", "Find approved products and replies, then download them for the next step.")
    if not database_ready:
        st.error("Saved work is unavailable. Ask the app administrator to restore the connection.")
        return
    try:
        listings, cases = approved_export_rows()
    except Exception as exc:
        st.error(_friendly_exception(exc, "Loading approved work"))
        return
    a, b = st.columns(2)
    a.metric("Approved products", len(listings))
    b.metric("Approved replies", len(cases))
    st.caption("These are internal approvals. Products have not been published and customer messages have not been sent.")
    products_tab, replies_tab = st.tabs([f"Product listings ({len(listings)})", f"Customer replies ({len(cases)})"])
    for pane, rows, kind in [(products_tab, listings, "products"), (replies_tab, cases, "replies")]:
        with pane:
            if not rows:
                _empty("No approved " + kind + " yet.", "Complete a review, then approve the work. It will appear here for your team to download.")
                target = "Product listings" if kind == "products" else "Customer messages"
                st.button("Go to " + target.lower(), key="exports-go-" + kind, on_click=_switch_workspace, args=(target,))
            else:
                query = st.text_input("Search approved " + kind, placeholder="Search names, codes or reply text", key="exports-query-" + kind).strip().lower()
                visible = [row for row in rows if not query or query in " ".join(str(value) for value in row.values()).lower()]
                if visible:
                    if kind == "products":
                        summary = [{"Supplier code": row.get("sku"), "Product": row.get("product"), "Color": row.get("standard_color"), "Price (₹)": row.get("price"), "Reviewed by": row.get("approved_by")} for row in visible]
                    else:
                        summary = [{"Order": row.get("order_id") or "Number needed", "Request": {"WISMO": "Order tracking", "RETURN_REQUEST": "Return / exchange", "CANCELLATION": "Cancellation"}.get(row.get("intent"), "Team review"), "Follow-up needed": "Yes" if row.get("agent_follow_up_required") else "No", "Reviewed by": row.get("approved_by")} for row in visible]
                    _show_table(pd.DataFrame(summary), hide_index=True, width="stretch")
                    with st.expander("Preview approved work"):
                        selected = st.selectbox("Choose an approved " + ("product" if kind == "products" else "reply"), list(range(len(visible))), format_func=lambda index: (str(visible[index].get("sku", "")) + " · " + str(visible[index].get("product", ""))) if kind == "products" else "Order " + str(visible[index].get("order_id") or "number needed"), key="approval-preview-" + kind)
                        row = visible[selected]
                        if kind == "products":
                            st.subheader(row.get("title_hinglish") or row.get("product") or "Product")
                            st.write(row.get("description_hinglish", ""))
                            st.caption(" · ".join(str(row.get(field) or "") for field in ("standard_color", "fabric_composition", "sizes")))
                            st.write("Care: " + str(row.get("wash_care") or "Not supplied"))
                            st.write("Highlights: " + str(row.get("key_highlights") or "Not supplied"))
                        else:
                            st.code(row.get("draft_reply", ""), language=None, wrap_lines=True)
                            if row.get("follow_up_reason"):
                                st.warning(row["follow_up_reason"])
                        st.caption("Reviewed by " + str(row.get("approved_by") or "operator") + " · " + _display_date(row.get("approved_at_utc")))
                else:
                    st.info("No approved work matches your search.")
                st.download_button("Download " + str(len(visible)) + " " + kind + " as CSV", data=_csv_export(pd.DataFrame(visible)), file_name="dhaga_approved_" + kind + ".csv", mime="text/csv", disabled=not visible)


def _overview_workspace() -> None:
    _page_header("YOUR TEAM'S WORKSPACE", "Your team’s work, in one place.", "Review product listings and customer replies. Choose a task or continue saved work.")
    drafts, messages = [], []
    counts = {}
    if database_ready:
        try:
            drafts = unapproved_listing_rows(limit=3)
            messages = recent_support_cases(limit=3)
            counts = workspace_counts()
        except Exception as exc:
            st.warning(_friendly_exception(exc, "Loading your work queue"))
    c1, c2, c3 = st.columns(3)
    c1.metric("Products awaiting review", counts.get("listing_pending", 0))
    c2.metric("Customer messages to follow up", counts.get("support_pending", 0))
    c3.metric("Approved work", counts.get("listing_approved", 0) + counts.get("support_approved", 0))
    st.subheader("What would you like to work on?")
    left, right = st.columns(2, gap="large")
    with left:
        with st.container(border=True):
            st.markdown('<div class="task-icon">▤</div><div class="task-label">PRODUCT LISTINGS</div><div class="task-title">Prepare product listings.</div><p class="task-description">Check supplier details and suggested text, then save reviewed listings for your team.</p>', unsafe_allow_html=True)
            st.button("Go to product listings", key="overview-product-listings", type="primary", width="stretch", on_click=_switch_workspace, args=("Product listings",))
            st.caption("Start with a CSV / Excel sheet or 26 sample products.")
    with right:
        with st.container(border=True):
            st.markdown('<div class="task-icon teal">↗</div><div class="task-label">CUSTOMER CARE</div><div class="task-title">Prepare a customer reply.</div><p class="task-description">Find the order, check the facts, and save a reviewed reply or an internal follow-up.</p>', unsafe_allow_html=True)
            st.button("Go to customer messages", key="overview-customer-messages", width="stretch", on_click=_switch_workspace, args=("Customer messages",))
            st.caption("Start with a message or try a sample scenario.")
    if drafts or messages:
        st.subheader("Pick up where you left off")
        recent = [{"Task": "Product review", "Item": row.get("product_name") or row.get("vendor_sku_raw") or "Unnamed product", "Status": _status_label(row["status"])} for row in drafts[:3]]
        recent += [{"Task": "Customer reply", "Item": "Order " + (row.get("order_id") or "number needed"), "Status": _status_label(row["status"])} for row in messages[:3]]
        _show_table(pd.DataFrame(recent), width="stretch", hide_index=True)
    with st.expander("First time here? A quick guide"):
        st.write("1. Choose a task and add a supplier sheet or customer message. Samples let you practice.")
        st.write("2. Check the original details, fix anything missing, and edit the suggested text.")
        st.write("3. Save a draft to return later, or confirm your review and approve it for the team.")
        st.write("4. Download completed work from Saved approvals. Publishing and sending happen in your usual tools.")


prepare_workspace_widget(st.session_state)
with st.sidebar:
    st.markdown('<div class="brand"><div class="brand-mark">d.</div><div><div class="brand-name">dhaga ops</div><div class="brand-caption">A calmer way to work.</div></div></div>', unsafe_allow_html=True)
    workspace = st.radio("WORKSPACE", WORKSPACES, key=WORKSPACE_KEY)
    st.divider()
    st.text_input("Your name (for approvals)", key="operator_name", placeholder="E.g. Ananya", max_chars=100, help="Records who reviewed the work. The shared team password does not verify individual identity.")
    st.caption("Shared work saved" if database_ready and is_database_persistent() else "Saved on this computer" if database_ready else "Saving unavailable")
    st.caption("AI assistance on" if settings.live_models_enabled else "Sample mode · no AI calls")
    with st.expander("Help & workspace details"):
        st.write("Samples use illustrative orders and policies. Your store and courier accounts are not connected.")
        if settings.live_models_enabled:
            st.write("AI may send relevant supplier details and customer message text to Google. Use sample data while exploring.")
        st.write("Save draft before leaving an editor. Reopen it from the saved drafts section on that page.")
        st.write("Approval saves work internally. Use your store or support tool to publish or send.")
        if not settings.app_password:
            st.caption("Local workspace · no app password configured")
    if settings.app_password and st.button("Sign out", width="stretch"):
        st.session_state.clear()
        st.rerun()

st.markdown(f'<div class="topline"><span>Dhaga & Co. <span aria-hidden="true"> / </span> {escape(workspace)}</span><span class="mode-pill">Sample orders & policies</span></div>', unsafe_allow_html=True)
flash = st.session_state.pop("flash_message", None)
if flash:
    st.success(flash)
if not database_ready:
    st.error("Saving is unavailable. You can review results, but approval needs a working storage connection.")
if settings.model_mode == "live" and not settings.gemini_api_key:
    st.warning("AI assistance is unavailable. Local checks and sample wording are available.")

if workspace == "Overview":
    _overview_workspace()
elif workspace == "Product listings":
    _catalog_workspace()
elif workspace == "Customer messages":
    _cx_workspace()
else:
    _exports_workspace()
