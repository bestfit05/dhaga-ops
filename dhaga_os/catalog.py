from __future__ import annotations

import io
import csv
import json
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pandas as pd

from dhaga_os.config import ROOT_DIR, get_settings
from dhaga_os.llm import ModelUnavailable
from dhaga_os.model_gateway import ModelTask, generate_for_task
from dhaga_os.models import CatalogAttributeBatch, CatalogAuditBatch, CatalogColorInferenceBatch, CatalogCopyBatch, MasterColor

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
    # Standards-compliant parsing gets first priority: quoted fields can span
    # lines containing any number of commas. Recovery is only for broken files.
    complete_rows: list[tuple[int, list[str]]] = []
    complete_errors: list[dict[str, Any]] = []
    reader = csv.reader(io.StringIO("\n".join(physical_lines[header_index + 1:])), delimiter=delimiter, strict=True)
    previous_line = 0
    try:
        for row in reader:
            line_number = header_index + 2 + previous_line
            previous_line = reader.line_num
            if not any(value.strip() for value in row):
                continue
            if len(row) != len(headers):
                complete_errors.append({"line": line_number, "issue": f"This row has {len(row)} fields; the header has {len(headers)}."})
            else:
                complete_rows.append((line_number, row))
        return headers, complete_rows, complete_errors
    except csv.Error:
        pass
    index = header_index + 1
    while index < len(physical_lines):
        line_number = index + 1
        line = physical_lines[index]
        index += 1
        if not line.strip():
            continue
        try:
            row = next(csv.reader([line], delimiter=delimiter, strict=True))
        except csv.Error as exc:
            # A quoted description may contain newlines. Keep its starting line
            # for operator feedback, while recovering after an unclosed quote.
            if "unexpected end of data" not in str(exc):
                errors.append({"line": line_number, "issue": "This row has unmatched or malformed quotes."})
                continue
            row = None
            combined = line
            while index < len(physical_lines):
                continuation = physical_lines[index]
                try:
                    standalone = next(csv.reader([continuation], delimiter=delimiter, strict=True))
                except csv.Error:
                    standalone = []
                if len(standalone) >= len(headers) and any(value.strip() for value in standalone):
                    break
                index += 1
                combined += "\n" + continuation
                try:
                    row = next(csv.reader(io.StringIO(combined), delimiter=delimiter, strict=True))
                    break
                except csv.Error as continuation_error:
                    if "unexpected end of data" not in str(continuation_error):
                        break
            if row is None:
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


def _validate_upload_headers(source_headers: list[str]) -> None:
    cleaned = [_clean_header(header) for header in source_headers]
    if any(not header for header in cleaned):
        raise ValueError("Every column needs a name. Remove empty header columns and upload again.")
    if len(set(cleaned)) != len(cleaned):
        raise ValueError("The sheet has duplicate column names. Give each column one unique name and upload again.")


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
            frame = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl", header=None, nrows=502, dtype=object, keep_default_na=False)
            if frame.empty:
                raise ValueError("The selected Excel sheet is empty.")
            source_headers = [_cell(header) for header in frame.iloc[0].tolist()]
            _validate_upload_headers(source_headers)
            frame = frame.iloc[1:].copy()
            frame.columns = source_headers
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
    _validate_upload_headers(source_headers)

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
    # Exact reuploads recover the same saved work instead of multiplying drafts.
    import_key = stable_key_prefix or f"vendor-upload:{sha256(file_bytes).hexdigest()}"
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
            issues.append("Add the supplier code before approval.")
        if not normalized.get("product_name"):
            issues.append("Add the product name before approval.")
        if not normalized.get("fabric_composition"):
            issues.append("Add the fabric or material before approval.")
        if not raw_color:
            issues.append("Choose a product color before approval.")
        elif not color:
            issues.append("Choose the product color that best matches this supplier shade.")

        record = {
            "row_key": str(uuid5(NAMESPACE_URL, f"{import_key}:{line_number}")),
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
            "status": "blocked" if any(issue.startswith(("Add the supplier code", "Add the product name", "Add the fabric")) for issue in issues) else "needs_review" if issues else "draft",
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
    sku_counts = Counter(row["vendor_sku_raw"].casefold() for row in records if row["vendor_sku_raw"])
    for record in records:
        if sku_counts[record["vendor_sku_raw"].casefold()] > 1:
            record["issues"].append("This supplier code appears more than once in the sheet. Give each product a unique code before approval.")
            record["normalized_payload"]["duplicate_supplier_code"] = record["vendor_sku_raw"]
            record["status"] = "blocked"
    if not records and not row_errors:
        raise ValueError("The sheet has a header but no data rows.")
    return records, row_errors


def read_vendor_upload(file_bytes: bytes, filename: str) -> list[dict[str, Any]]:
    """Compatibility wrapper for callers that expect valid rows only."""
    records, _ = read_vendor_upload_detailed(file_bytes, filename)
    return records


NORMALIZED_FIELDS = (
    "vendor_sku_raw", "product_name", "product_category", "raw_color_input", "standard_color",
    "fabric_composition", "vendor_fabric_source", "fit_silhouette", "wash_care", "vendor_care_source",
    "size_values_raw", "size_values", "price", "occasion_tags",
)
REQUIRED_ISSUE_PREFIXES = (
    "Add the supplier", "Add the product name", "Add the fabric", "Choose the product color",
    "Choose the standard color", "Choose a standard color", "Unknown vendor shade", "Color missing",
    "Missing vendor SKU", "Missing product name", "Mandatory missing", "Enter a valid price",
)


def refresh_catalog_validation(record: dict[str, Any]) -> dict[str, Any]:
    """Refresh editable data, required-field issues and final-copy checks in place.

    Call after changing row fields and generated_copy. Supplier source fields stay
    separate from edited attributes. The returned object is the same record.
    """
    issues = [
        issue for issue in record.get("issues", [])
        if not str(issue).startswith(REQUIRED_ISSUE_PREFIXES)
    ]
    duplicate_source = record.get("normalized_payload", {}).get("duplicate_supplier_code")
    if duplicate_source and _cell(record.get("vendor_sku_raw")).casefold() != str(duplicate_source).casefold():
        issues = [issue for issue in issues if not issue.startswith("This supplier code appears more than once")]
    required = (
        ("vendor_sku_raw", "Add the supplier code before approval."),
        ("product_name", "Add the product name before approval."),
        ("fabric_composition", "Add the fabric or material before approval."),
    )
    for field, issue in required:
        record[field] = _cell(record.get(field))
        if not record[field]:
            issues.append(issue)
    if record.get("standard_color") not in {color.value for color in MasterColor}:
        issues.append("Choose the product color before approval.")
    record["size_values"] = normalize_size_values(record.get("size_values", ""))
    price = _cell(record.get("price"))
    if price:
        try:
            number = Decimal(re.sub(r"[₹,\s]", "", price))
            if not number.is_finite() or number < 0:
                raise InvalidOperation
        except InvalidOperation:
            issues.append("Enter a valid price of zero or more before approval.")
    record["issues"] = list(dict.fromkeys(issues))
    record.setdefault("normalized_payload", {}).update(
        {key: record.get(key, [] if key == "occasion_tags" else "") for key in NORMALIZED_FIELDS}
    )
    if record.get("generated_copy"):
        passed, notes = _deterministic_copy_check(record, record["generated_copy"])
    else:
        passed, notes = False, "Prepare and review the listing text before approval."
    audit_pending = record["normalized_payload"].get("model_audit_required") and not (
        record["normalized_payload"].get("model_audit_passed")
        or record["normalized_payload"].get("human_source_verified")
    )
    if audit_pending:
        passed = False
        notes += " The AI facts review did not pass; compare every detail with the supplier sheet."
    record["compliance_passed"] = passed
    record["compliance_notes"] = notes
    missing = any(not record.get(field) for field, _ in required)
    record["status"] = "blocked" if missing else "needs_review" if issues or not passed else "draft"
    return record


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
    highlights = [f"Kapda: {fabric}"]
    if record.get("fit_silhouette"):
        highlights.append(f"Fit: {record['fit_silhouette']}")
    if occasion:
        highlights.append(f"Kis mauke ke liye: {', '.join(occasion)}")
    return {
        "row_key": record["row_key"],
        "title_hinglish": title,
        "description_hinglish": description,
        "key_highlights": highlights,
        "search_keywords": [*occasion, color or "fashion", name],
    }


def _deterministic_copy_check(record: dict[str, Any], copy: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(copy, dict):
        return False, "Prepare the listing text before approval."
    title = _cell(copy.get("title_hinglish"))
    description = _cell(copy.get("description_hinglish"))
    highlights = copy.get("key_highlights", [])
    if not title or not description or not isinstance(highlights, list) or not any(_cell(item) for item in highlights):
        return False, "Add a title, description and at least one highlight before approval."
    if len(title) > 70:
        return False, "Shorten the product title to 70 characters or fewer."
    source_fabric = str(record.get("vendor_fabric_source", record.get("fabric_composition")) or "").casefold()
    source_care = str(record.get("vendor_care_source", record.get("wash_care")) or "").casefold()
    generated = " ".join(
        [copy.get("title_hinglish", ""), copy.get("description_hinglish", ""), *copy.get("key_highlights", [])]
    ).casefold()
    violations: list[str] = []
    if ("pure" in generated or "100%" in generated) and "pure" not in source_fabric and "100%" not in source_fabric:
        violations.append("The copy claims a pure fabric, but the supplier has not confirmed that composition.")
    for claim in ("organic", "sustainable", "eco friendly", "antibacterial", "waterproof", "shrink proof", "fade resistant"):
        if claim in generated and claim not in source_fabric:
            violations.append(f"The copy adds the unsupported product claim ‘{claim}’.")
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
    return True, "The fabric, care and color checks passed. Review the listing text before approval."


def process_catalog_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize attributes, draft copy, and audit the batch with explicit model boundaries."""
    settings = get_settings()
    usable = [
        record
        for record in records
        if not any(
            issue.startswith(("Add the fabric", "Add the supplier code", "Add the product name"))
            for issue in record["issues"]
        )
    ]
    model_warnings: list[str] = []

    if settings.live_models_enabled and usable:
        unknown_shades = [row for row in usable if row.get("raw_color_input") and not row.get("standard_color")]
        if unknown_shades:
            try:
                inference = generate_for_task(
                    ModelTask.COLOR_SUGGESTION,
                    context={"unknown_color": True},
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
                if inference:
                    inference_by_key = {item.row_key: item for item in inference.items}
                    for row in unknown_shades:
                        inferred = inference_by_key.get(row["row_key"])
                        if inferred:
                            row["inferred_color"] = inferred.inferred_color.value
                            row["color_inference_reason"] = inferred.reason
            except ModelUnavailable as exc:
                model_warnings.append(str(exc))

        attribute_candidates = [
            row for row in usable
            if any(not row.get(field) for field in ("product_category", "fit_silhouette", "wash_care", "occasion_tags"))
            and any(len(str(value or "").strip()) >= 35 for value in row.get("raw_payload", {}).values())
        ]
        if attribute_candidates:
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
                    for row in attribute_candidates
                ]
                extracted = generate_for_task(
                    ModelTask.ATTRIBUTE_EXTRACTION,
                    context={
                        "missing_fields": True,
                        "useful_free_text": True,
                    },
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
                if extracted:
                    by_key = {item.row_key: item for item in extracted.items}
                    for row in attribute_candidates:
                        attr = by_key.get(row["row_key"])
                        if attr:
                            for field in ("product_category", "fabric_composition", "fit_silhouette", "wash_care"):
                                value = getattr(attr, field).strip()
                                if value and not row.get(field):
                                    row[field] = value
                            if attr.occasion_tags and not row.get("occasion_tags"):
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
            generated = generate_for_task(
                ModelTask.LISTING_COPY,
                context={"ready_products": len(ready)},
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
            if generated:
                live_copy_by_key = {item.row_key: item.model_dump(mode="json") for item in generated.items}
                missing_copy_keys = {row["row_key"] for row in ready} - live_copy_by_key.keys()
                if missing_copy_keys:
                    model_warnings.append("AI copy was missing for some products; a local template was used instead.")
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
            audit = generate_for_task(
                ModelTask.LISTING_REVIEW,
                context={"model_written_products": len(audit_input)},
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
            if audit:
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
        row["normalized_payload"]["model_audit_required"] = row["row_key"] in live_copy_by_key
        row["normalized_payload"]["model_audit_passed"] = bool(
            audits_by_key.get(row["row_key"]) and audits_by_key[row["row_key"]].factual_compliance_pass
        )
        deterministic_pass, deterministic_note = _deterministic_copy_check(row, copy)
        audit = audits_by_key.get(row["row_key"])
        if audit is not None:
            row["compliance_passed"] = deterministic_pass and audit.factual_compliance_pass
            if not deterministic_pass:
                row["compliance_notes"] = deterministic_note
            elif audit.factual_compliance_pass:
                row["compliance_notes"] = "The standard checks and an extra facts check passed."
            else:
                row["compliance_notes"] = audit.compliance_notes or "The listing text may include details missing from the supplier sheet. Check it before approval."
        else:
            row["compliance_passed"] = deterministic_pass and row["row_key"] not in live_copy_by_key
            if not deterministic_pass:
                row["compliance_notes"] = deterministic_note
            elif row["row_key"] in live_copy_by_key:
                row["compliance_notes"] = "The standard checks passed, but an extra facts check did not finish. Check every detail before approval."
            else:
                row["compliance_notes"] = "The fabric, care and color checks passed. Review the listing text before approval."
        audit_missing = row["row_key"] in live_copy_by_key and row["row_key"] not in audits_by_key
        row["status"] = "needs_review" if row["issues"] or not row["compliance_passed"] or audit_missing else "draft"
        row["normalized_payload"].update(
            {key: row[key] for key in ("product_category", "fabric_composition", "fit_silhouette", "wash_care", "occasion_tags")}
        )
    return records


def sample_vendor_csv() -> bytes:
    return (ROOT_DIR / "data" / "demo_vendor.csv").read_bytes()
