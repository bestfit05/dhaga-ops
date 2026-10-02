from __future__ import annotations

import io
import csv
import json
import re
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import pandas as pd

from dhaga_os.config import ROOT_DIR, get_settings
from dhaga_os.llm import ModelUnavailable, generate_json
from dhaga_os.models import CatalogAttributeBatch, CatalogAuditBatch, CatalogColorInferenceBatch, CatalogCopyBatch

MAX_UPLOAD_BYTES = 5 * 1024 * 1024

ALIASES = {
    "vendor_sku_raw": ("sku", "vendor sku", "vendor_sku", "product id", "product_id", "item code", "style code", "style no"),
    "product_name": ("product name", "name", "product", "item name", "style name", "title", "description"),
    "product_category": ("category", "product category", "type", "garment type"),
    "raw_color_input": ("color", "colour", "vendor color", "vendor colour", "shade", "color name", "colour name"),
    "fabric_composition": ("fabric", "fabric composition", "material", "textile", "composition"),
    "fit_silhouette": ("fit", "silhouette", "shape", "fit silhouette"),
    "wash_care": ("care", "wash care", "wash instructions", "care instructions"),
    "size_values": ("size", "sizes", "size chart", "size range"),
    "price": ("price", "mrp", "selling price", "amount"),
    "occasion_text": ("occasion", "occasion tags", "use case", "wear"),
}

FABRIC_TERMS = (
    "cotton", "rayon", "viscose", "polyester", "georgette", "chiffon", "silk", "linen",
    "chanderi", "satin", "velvet", "wool", "acrylic", "nylon", "modal", "poplin", "slub",
)
CARE_TERMS = (
    "machine wash", "hand wash", "dry clean", "cold wash", "do not bleach", "iron", "tumble dry",
)


def _clean_header(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()


def _cell(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.casefold() in {"nan", "none", "n/a", "na", "null", "-"} else text


def _json_safe(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _cell(value) for key, value in row.items()}


def _load_color_aliases() -> dict[str, str]:
    path = ROOT_DIR / "data" / "color_aliases.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, str] = {}
    for master, aliases in data.items():
        for alias in [master, *aliases]:
            result[_clean_header(alias)] = master
    return result


COLOR_ALIASES = _load_color_aliases()


def normalize_color(raw_color: str) -> str | None:
    """Map known spellings to the controlled palette; keep unfamiliar shades for review."""
    cleaned = _clean_header(raw_color)
    return COLOR_ALIASES.get(cleaned) if cleaned else None


SIZE_ORDER = ("XS", "S", "M", "L", "XL", "XXL")
SIZE_ALIASES = {
    "xs": "XS", "xsmall": "XS", "extra small": "XS", "extrasmall": "XS",
    "s": "S", "small": "S",
    "m": "M", "medium": "M", "med": "M",
    "l": "L", "large": "L",
    "xl": "XL", "xlarge": "XL", "extra large": "XL", "extralarge": "XL",
    "xxl": "XXL", "2xl": "XXL", "2xlarge": "XXL", "xxlarge": "XXL", "2x": "XXL",
}


def normalize_size_values(raw_sizes: str) -> str:
    """Normalize common alpha-size names and ranges; leave non-alpha vendor sizes intact."""
    raw = _cell(raw_sizes)
    if not raw:
        return ""
    range_match = re.fullmatch(r"\s*(.+?)\s*[-–]\s*(.+?)\s*", raw)
    if range_match:
        endpoints = []
        for endpoint in range_match.groups():
            cleaned = re.sub(r"\s+", " ", endpoint.casefold()).strip()
            compact = re.sub(r"[^a-z0-9]+", "", cleaned)
            endpoints.append(SIZE_ALIASES.get(cleaned) or SIZE_ALIASES.get(compact))
        if all(endpoints):
            i, j = (SIZE_ORDER.index(endpoint) for endpoint in endpoints)
            if i <= j:
                return ", ".join(SIZE_ORDER[i : j + 1])

    parts = [part.strip() for part in re.split(r"[,;|/]", raw) if part.strip()]
    normalized: list[str] = []
    for part in parts:
        key = re.sub(r"\s+", " ", part.casefold()).strip()
        compact = re.sub(r"[^a-z0-9]+", "", key)
        value = SIZE_ALIASES.get(key) or SIZE_ALIASES.get(compact) or part
        if value not in normalized:
            normalized.append(value)
    alpha = [value for value in SIZE_ORDER if value in normalized]
    other = [value for value in normalized if value not in SIZE_ORDER]
    return ", ".join([*alpha, *other])


def _parse_csv_rows(file_bytes: bytes) -> tuple[list[str], list[tuple[int, list[str]]], list[dict[str, Any]]]:
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("The CSV must use UTF-8 text encoding. Save it as CSV UTF-8 and upload it again.") from exc
    physical_lines = text.splitlines()
    non_empty = [line for line in physical_lines if line.strip()]
    if not non_empty:
        raise ValueError("The selected CSV is empty.")
    try:
        delimiter = csv.Sniffer().sniff("\n".join(non_empty[:8]), delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = ","

    header_index = next(index for index, line in enumerate(physical_lines) if line.strip())
    try:
        headers = next(csv.reader([physical_lines[header_index]], delimiter=delimiter, strict=True))
    except csv.Error as exc:
        raise ValueError("The CSV header row could not be read. Check its quotes and column names.") from exc
    headers = [header.strip() for header in headers]
    if not any(headers):
        raise ValueError("The CSV needs a header row with column names.")

    rows: list[tuple[int, list[str]]] = []
    errors: list[dict[str, Any]] = []
    for line_number, line in enumerate(physical_lines[header_index + 1 :], start=header_index + 2):
        if not line.strip():
            continue
        try:
            row = next(csv.reader([line], delimiter=delimiter, strict=True))
        except csv.Error:
            errors.append({"line": line_number, "issue": "This row has unmatched or malformed quotes."})
            continue
        if not any(value.strip() for value in row):
            continue
        if len(row) != len(headers):
            errors.append(
                {
                    "line": line_number,
                    "issue": f"This row has {len(row)} fields; the header has {len(headers)}.",
                }
            )
            continue
        rows.append((line_number, row))
    return headers, rows, errors


def read_vendor_upload_detailed(
    file_bytes: bytes, filename: str, stable_key_prefix: str | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read a vendor sheet, keeping valid rows and returning parse errors separately."""
    if not file_bytes:
        raise ValueError("The selected file is empty.")
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise ValueError("Upload a vendor sheet smaller than 5 MB.")
    suffix = Path(filename).suffix.casefold()
    try:
        if suffix == ".csv":
            source_headers, csv_rows, row_errors = _parse_csv_rows(file_bytes)
            source_records = [
                (line_number, {header: value for header, value in zip(source_headers, values)})
                for line_number, values in csv_rows
            ]
        elif suffix in {".xlsx", ".xlsm"}:
            frame = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl")
            source_headers = [str(header) for header in frame.columns]
            source_records = [
                (line_number, row)
                for line_number, row in enumerate(frame.to_dict(orient="records"), start=2)
            ]
            row_errors = []
        else:
            raise ValueError("Upload a CSV or modern Excel .xlsx file.")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("The sheet could not be read. Check its header row and cell formatting.") from exc
    if len(source_records) > 500:
        raise ValueError("The MVP accepts up to 500 rows per upload. Split larger vendor sheets into batches.")

    header_map: dict[str, str] = {}
    mapped_targets: dict[str, str] = {}
    for source_header in source_headers:
        cleaned = _clean_header(source_header)
        for target, candidates in ALIASES.items():
            if cleaned in {_clean_header(candidate) for candidate in candidates}:
                if target in mapped_targets:
                    raise ValueError(
                        f"The sheet has more than one column for {target.replace('_', ' ')}. "
                        "Keep one column for each field and upload it again."
                    )
                header_map[str(source_header)] = target
                mapped_targets[target] = str(source_header)
                break
    if not header_map:
        raise ValueError("No recognized vendor columns found. Include at least SKU, product name, color, and fabric headers.")

    records: list[dict[str, Any]] = []
    for line_number, source_row in source_records:
        raw_payload = _json_safe(source_row)
        normalized: dict[str, str] = {}
        for source_header, target in header_map.items():
            value = _cell(source_row.get(source_header))
            if value:
                normalized[target] = value
        raw_color = normalized.get("raw_color_input", "")
        color = normalize_color(raw_color)
        raw_sizes = normalized.get("size_values", "")
        occasions = [tag.strip() for tag in re.split(r"[;,|/]", normalized.get("occasion_text", "")) if tag.strip()]
        issues: list[str] = []
        if not normalized.get("vendor_sku_raw"):
            issues.append("Add the supplier SKU before approval.")
        if not normalized.get("product_name"):
            issues.append("Add the product name before approval.")
        if not normalized.get("fabric_composition"):
            issues.append("Add the fabric or material before approval.")
        if not raw_color:
            issues.append("Choose a standard color before approval.")
        elif not color:
            issues.append("Choose the standard color that best matches this supplier shade.")

        record = {
            "row_key": (
                str(uuid5(NAMESPACE_URL, f"{stable_key_prefix}:{Path(filename).name}:{line_number}"))
                if stable_key_prefix
                else str(uuid4())
            ),
            "source_filename": Path(filename).name,
            "source_line_number": line_number,
            "vendor_sku_raw": normalized.get("vendor_sku_raw", ""),
            "product_name": normalized.get("product_name", ""),
            "product_category": normalized.get("product_category", ""),
            "raw_color_input": raw_color,
            "standard_color": color or "",
            "inferred_color": "",
            "color_inference_reason": "",
            "fabric_composition": normalized.get("fabric_composition", ""),
            "vendor_fabric_source": normalized.get("fabric_composition", ""),
            "fit_silhouette": normalized.get("fit_silhouette", ""),
            "wash_care": normalized.get("wash_care", ""),
            "vendor_care_source": normalized.get("wash_care", ""),
            "size_values_raw": raw_sizes,
            "size_values": normalize_size_values(raw_sizes),
            "price": normalized.get("price", ""),
            "occasion_tags": occasions,
            "raw_payload": raw_payload,
            "issues": issues,
            "generated_copy": None,
            "compliance_passed": None,
            "compliance_notes": "",
            "model_mode": "demo-rule-based" if not get_settings().live_models_enabled else "live",
            "model_warnings": [],
            "status": "blocked" if any(issue.startswith(("Add the supplier SKU", "Add the product name", "Add the fabric")) for issue in issues) else "needs_review" if issues else "draft",
        }
        record["normalized_payload"] = {
            key: record[key]
            for key in (
                "vendor_sku_raw", "product_name", "product_category", "raw_color_input", "standard_color",
                "fabric_composition", "vendor_fabric_source", "fit_silhouette", "wash_care", "vendor_care_source",
                "size_values_raw", "size_values", "price", "occasion_tags",
            )
        }
        records.append(record)
    if not records and not row_errors:
        raise ValueError("The sheet has a header but no data rows.")
    return records, row_errors


def read_vendor_upload(file_bytes: bytes, filename: str) -> list[dict[str, Any]]:
    """Compatibility wrapper for callers that expect valid rows only."""
    records, _ = read_vendor_upload_detailed(file_bytes, filename)
    return records


def _deterministic_copy(record: dict[str, Any]) -> dict[str, Any]:
    name = record.get("product_name") or record.get("product_category") or "Everyday style"
    color = record.get("standard_color")
    fabric = record.get("fabric_composition")
    occasion = record.get("occasion_tags", [])
    occasion_value = occasion[0] if occasion else "daily wear"
    occasion_key = _clean_header(occasion_value)
    occasion_phrases = {
        "mehndi": "Mehndi ke liye",
        "festive": "Tyohar ke liye",
        "festival": "Tyohar ke liye",
        "wedding guest": "Shaadi ke liye",
        "wedding": "Shaadi ke liye",
        "office": "Office ke liye",
        "work": "Kaam ke liye",
        "daily wear": "Roz pehenne ke liye",
        "everyday": "Roz pehenne ke liye",
        "casual": "Casual look ke liye",
        "party": "Party ke liye",
        "brunch": "Brunch ke liye",
        "travel": "Safar ke liye",
        "lounge": "Aaram ke waqt ke liye",
    }
    occasion_phrase = occasion_phrases.get(occasion_key, f"{occasion_value} ke liye" if occasion_value else "Roz pehenne ke liye")
    title = f"{occasion_phrase}: {name}"[:70]
    color_phrase = f"{color} rang" if color else "Is rang"
    description = f"{name} ka {color_phrase} aur {fabric} fabric. {occasion_phrase} pehen sakte hain."
    highlights = [
        f"Kapda: {fabric}",
        f"Fit: {record.get('fit_silhouette') or 'Confirm fit details'}",
        f"Kis mauke ke liye: {', '.join(occasion) if occasion else 'roz ke liye'}",
    ]
    return {
        "row_key": record["row_key"],
        "title_hinglish": title,
        "description_hinglish": description,
        "key_highlights": highlights,
        "search_keywords": [*occasion, color or "fashion", name],
    }


def _deterministic_copy_check(record: dict[str, Any], copy: dict[str, Any]) -> tuple[bool, str]:
    source_fabric = (record.get("vendor_fabric_source") or record.get("fabric_composition") or "").casefold()
    source_care = (record.get("vendor_care_source") or record.get("wash_care") or "").casefold()
    generated = " ".join(
        [copy.get("title_hinglish", ""), copy.get("description_hinglish", ""), *copy.get("key_highlights", [])]
    ).casefold()
    violations: list[str] = []
    for term in FABRIC_TERMS:
        if re.search(rf"\b{re.escape(term)}\b", generated) and not re.search(rf"\b{re.escape(term)}\b", source_fabric):
            source_label = record.get("vendor_fabric_source") or "no fabric listed"
            violations.append(f"The copy says ‘{term}’, but the supplier's fabric entry is ‘{source_label or 'blank'}’.")
    for term in CARE_TERMS:
        if term in generated and term not in source_care:
            violations.append(f"The copy adds ‘{term}’, but that care instruction is not in the supplier sheet.")
    expected_color = record.get("standard_color") or normalize_color(record.get("raw_color_input", ""))
    if expected_color:
        product_name = str(record.get("product_name") or "").casefold()
        color_copy = generated.replace(product_name, "") if product_name else generated
        matches: list[tuple[int, int, int, str]] = []
        for alias, master in COLOR_ALIASES.items():
            for match in re.finditer(rf"\b{re.escape(alias)}\b", color_copy):
                matches.append((match.start(), match.end(), len(alias), master))
        for start, end, length, master in matches:
            if any(
                other_start <= start
                and other_end >= end
                and other_length > length
                and other_master == expected_color
                for other_start, other_end, other_length, other_master in matches
            ):
                continue
            if master != expected_color:
                violations.append(f"The copy says ‘{master}’, but the selected standard color is ‘{expected_color}’.")
                break
    if violations:
        return False, "; ".join(violations)
    return True, "The basic fabric, care and color checks passed. Review the copy before approval."


def process_catalog_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize attributes, draft copy, and audit the batch with explicit model boundaries."""
    settings = get_settings()
    usable = [
        record
        for record in records
        if not any(
            issue.startswith(("Add the fabric", "Add the supplier SKU", "Add the product name"))
            for issue in record["issues"]
        )
    ]
    model_warnings: list[str] = []

    if settings.live_models_enabled and usable:
        unknown_shades = [row for row in usable if row.get("raw_color_input") and not row.get("standard_color")]
        if unknown_shades:
            try:
                inference = generate_json(
                    model=settings.gemini_fast_model,
                    temperature=0.1,
                    response_model=CatalogColorInferenceBatch,
                    prompt=(
                        "Suggest the closest master color for each unfamiliar regional vendor shade. "
                        "This is a tentative suggestion: preserve row_key and explain uncertainty briefly. "
                        "Never make the suggestion look verified; the operator must confirm it. Input:\n"
                        + json.dumps(
                            [{"row_key": row["row_key"], "raw_color_input": row["raw_color_input"]} for row in unknown_shades],
                            ensure_ascii=False,
                        )
                    ),
                )
                inference_by_key = {item.row_key: item for item in inference.items}
                for row in unknown_shades:
                    inferred = inference_by_key.get(row["row_key"])
                    if inferred:
                        row["inferred_color"] = inferred.inferred_color.value
                        row["color_inference_reason"] = inferred.reason
            except ModelUnavailable as exc:
                model_warnings.append(str(exc))
        try:
            attribute_input = [
                {
                    "row_key": row["row_key"],
                    "vendor_sku_raw": row["vendor_sku_raw"],
                    "product_name": row["product_name"],
                    "product_category": row["product_category"],
                    "fabric_composition": row["fabric_composition"],
                    "fit_silhouette": row["fit_silhouette"],
                    "wash_care": row["wash_care"],
                    "raw_vendor_fields": row["raw_payload"],
                }
                for row in usable
            ]
            extracted = generate_json(
                model=settings.gemini_fast_model,
                temperature=0.0,
                response_model=CatalogAttributeBatch,
                prompt=(
                    "Normalize garment attributes for each vendor item. Preserve the vendor's stated facts; "
                    "do not infer fiber, care, size, or fit facts that are absent. Keep row_key unchanged. "
                    "Return empty strings or an empty occasion_tags array when a fact is missing. Input:\n"
                    + json.dumps(attribute_input, ensure_ascii=False)
                ),
            )
            by_key = {item.row_key: item for item in extracted.items}
            for row in usable:
                attr = by_key.get(row["row_key"])
                if attr:
                    for field in ("product_category", "fabric_composition", "fit_silhouette", "wash_care"):
                        value = getattr(attr, field).strip()
                        if value and not row.get(field):
                            row[field] = value
                    if attr.occasion_tags:
                        row["occasion_tags"] = attr.occasion_tags
                    row["normalized_payload"].update(
                        {key: row[key] for key in ("product_category", "fabric_composition", "fit_silhouette", "wash_care", "occasion_tags")}
                    )
        except ModelUnavailable as exc:
            model_warnings.append(str(exc))

    ready = [row for row in usable if row.get("fabric_composition")]
    live_copy_by_key: dict[str, dict[str, Any]] = {}
    if settings.live_models_enabled and ready:
        try:
            copy_input = [
                {
                    "row_key": row["row_key"],
                    "product_name": row["product_name"],
                    "category": row["product_category"],
                    "standard_color": row["standard_color"],
                    "vendor_fabric": row["fabric_composition"],
                    "fit": row["fit_silhouette"],
                    "care": row["wash_care"],
                    "occasion_tags": row["occasion_tags"],
                    "vendor_source": row["raw_payload"],
                }
                for row in ready
            ]
            generated = generate_json(
                model=settings.gemini_creative_model,
                temperature=0.7,
                response_model=CatalogCopyBatch,
                prompt=(
                    "Write concise occasion-led Hinglish product copy for Indian mobile shoppers. "
                    "Use only the facts in each item. Do not add fiber, care, color, size, or performance "
                    "claims. Keep row_key unchanged and make each title shorter than 70 characters. Items:\n"
                    + json.dumps(copy_input, ensure_ascii=False)
                ),
            )
            live_copy_by_key = {item.row_key: item.model_dump(mode="json") for item in generated.items}
            missing_copy_keys = {row["row_key"] for row in ready} - live_copy_by_key.keys()
            if missing_copy_keys:
                model_warnings.append("The creative model omitted one or more rows; local template copy used for those rows.")
        except ModelUnavailable as exc:
            model_warnings.append(str(exc))

    audits_by_key = {}
    if settings.live_models_enabled and live_copy_by_key:
        audit_input = [
            {
                "row_key": row["row_key"],
                "vendor_source": row["raw_payload"],
                "normalized_attributes": row["normalized_payload"],
                "generated_copy": live_copy_by_key[row["row_key"]],
            }
            for row in ready
            if row["row_key"] in live_copy_by_key
        ]
        try:
            audit = generate_json(
                model=settings.gemini_fast_model,
                temperature=0.1,
                response_model=CatalogAuditBatch,
                prompt=(
                    "Audit product copy against the original vendor source. Set factual_compliance_pass=false "
                    "if a fabric, care, size, or factual product claim is unsupported. Do not treat generated "
                    "copy as evidence. Keep row_key unchanged. Items:\n"
                    + json.dumps(audit_input, ensure_ascii=False)
                ),
            )
            audits_by_key = {item.row_key: item for item in audit.items}
        except ModelUnavailable as exc:
            model_warnings.append(str(exc))

    for row in records:
        row["model_warnings"] = model_warnings.copy()
        if row not in usable:
            row["status"] = "blocked"
            continue
        copy = live_copy_by_key.get(row["row_key"]) or _deterministic_copy(row)
        row["generated_copy"] = copy
        deterministic_pass, deterministic_note = _deterministic_copy_check(row, copy)
        audit = audits_by_key.get(row["row_key"])
        if audit is not None:
            row["compliance_passed"] = deterministic_pass and audit.factual_compliance_pass
            if not deterministic_pass:
                row["compliance_notes"] = deterministic_note
            elif audit.factual_compliance_pass:
                row["compliance_notes"] = "The basic copy checks and the additional factual review passed."
            else:
                row["compliance_notes"] = audit.compliance_notes or "The copy may include details missing from the supplier sheet. Check it before approval."
        else:
            row["compliance_passed"] = deterministic_pass
            if not deterministic_pass:
                row["compliance_notes"] = deterministic_note
            elif settings.live_models_enabled:
                row["compliance_notes"] = "The basic copy checks passed, but the additional review did not finish. Check every detail before approval."
            else:
                row["compliance_notes"] = "The basic fabric, care and color checks passed. Review the copy before approval."
        audit_missing = settings.live_models_enabled and row["row_key"] not in audits_by_key
        row["status"] = "needs_review" if row["issues"] or not row["compliance_passed"] or audit_missing else "draft"
        row["normalized_payload"].update(
            {key: row[key] for key in ("product_category", "fabric_composition", "fit_silhouette", "wash_care", "occasion_tags")}
        )
    return records


def sample_vendor_csv() -> bytes:
    return (ROOT_DIR / "data" / "demo_vendor.csv").read_bytes()
