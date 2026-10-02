from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from hashlib import sha256
from typing import Any, Iterator
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Index, String, Text, create_engine, func, select, text, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from dhaga_os.config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _content_hash(row: Any, fields: tuple[str, ...]) -> str:
    payload = {field: getattr(row, field, None) for field in fields}
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _revision_stamp(row: Any) -> str:
    value = row.updated_at
    return value.replace(tzinfo=timezone.utc).isoformat() if value else ""


def _check_revision(record: dict[str, Any], row: Any) -> None:
    if record.get("_revision") and record["_revision"] != _revision_stamp(row):
        raise ValueError("A teammate changed this saved work. Reopen the latest saved version before editing or approving it.")


def _write_existing(session: Session, row: Any, fields: tuple[str, ...], old_status: str, old_updated: datetime) -> None:
    """Atomically refuse stale writes, including on SQLite where row locks are unavailable."""
    values = {field: getattr(row, field) for field in fields}
    values["updated_at"] = utcnow()
    entity_type = type(row)
    row_id = row.id
    # Clear ORM dirtiness before the conditional UPDATE so a later flush cannot
    # issue an unconditional stale write after an operator has approved the row.
    with session.no_autoflush:
        session.expire(row)
        result = session.execute(
            update(entity_type).where(
                entity_type.id == row_id,
                entity_type.status == old_status,
                entity_type.updated_at == old_updated,
            ).values(**values).execution_options(synchronize_session=False)
        )
    if result.rowcount != 1:
        raise ValueError("A teammate saved or approved this work first. Reopen the latest saved version before continuing.")


LISTING_WRITE_FIELDS = (
    "source_filename", "vendor_sku", "raw_payload", "normalized_payload", "generated_copy",
    "compliance_passed", "compliance_notes", "issues", "status", "approved_by",
)
SUPPORT_WRITE_FIELDS = (
    "ticket_text", "parsed_query", "order_id", "carrier_facts", "policy_references", "draft_reply",
    "factual_verification_passed", "verification_notes", "requires_human_escalation", "escalation_reason", "status", "approved_by",
)


class Base(DeclarativeBase):
    pass


class ListingRecord(Base):
    __tablename__ = "listing_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_filename: Mapped[str] = mapped_column(String(255), default="")
    vendor_sku: Mapped[str] = mapped_column(String(128), default="", index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    normalized_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    generated_copy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    compliance_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    compliance_notes: Mapped[str] = mapped_column(Text, default="")
    issues: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SupportCase(Base):
    __tablename__ = "support_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticket_text: Mapped[str] = mapped_column(Text)
    parsed_query: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    order_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    carrier_facts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    policy_references: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    draft_reply: Mapped[str] = mapped_column(Text, default="")
    factual_verification_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    verification_notes: Mapped[str] = mapped_column(Text, default="")
    requires_human_escalation: Mapped[bool] = mapped_column(Boolean, default=False)
    escalation_reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_entity_created", "entity_type", "entity_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(128), default="operator")
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@lru_cache(maxsize=1)
def get_engine():
    settings = get_settings()
    if settings.is_vercel and not settings.database_url:
        raise RuntimeError(
            "DATABASE_URL is required on Vercel. Add a managed PostgreSQL connection string in project settings."
        )
    if settings.database_url:
        return create_engine(settings.database_url, pool_pre_ping=True, pool_recycle=300)
    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{settings.sqlite_path}",
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )


@lru_cache(maxsize=1)
def get_session_factory():
    return sessionmaker(bind=get_engine(), expire_on_commit=False, class_=Session)


@lru_cache(maxsize=1)
def initialize_database() -> None:
    Base.metadata.create_all(get_engine())


@contextmanager
def session_scope(*, write: bool = False) -> Iterator[Session]:
    session = get_session_factory()()
    try:
        if write and get_engine().dialect.name == "sqlite":
            # SQLite lacks row/advisory locks. Acquire its writer transaction
            # before reading mutable rows so approval and edits are serialized.
            session.execute(text("BEGIN IMMEDIATE"))
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def is_database_persistent() -> bool:
    return bool(get_settings().database_url)


def _listing_payload(row: ListingRecord) -> dict[str, Any]:
    normalized = row.normalized_payload or {}
    return {
        **normalized,
        "row_key": row.id,
        "source_filename": row.source_filename,
        "source_line_number": normalized.get("source_line_number"),
        "vendor_sku_raw": row.vendor_sku,
        "product_name": normalized.get("product_name", ""),
        "product_category": normalized.get("product_category", ""),
        "raw_color_input": normalized.get("raw_color_input", ""),
        "standard_color": normalized.get("standard_color", ""),
        "inferred_color": normalized.get("inferred_color", ""),
        "color_inference_reason": normalized.get("color_inference_reason", ""),
        "fabric_composition": normalized.get("fabric_composition", ""),
        "vendor_fabric_source": normalized.get("vendor_fabric_source", normalized.get("fabric_composition", "")),
        "fit_silhouette": normalized.get("fit_silhouette", ""),
        "wash_care": normalized.get("wash_care", ""),
        "vendor_care_source": normalized.get("vendor_care_source", normalized.get("wash_care", "")),
        "size_values_raw": normalized.get("size_values_raw", ""),
        "size_values": normalized.get("size_values", ""),
        "price": normalized.get("price", ""),
        "occasion_tags": normalized.get("occasion_tags", []),
        "raw_payload": row.raw_payload or {},
        "normalized_payload": normalized,
        "issues": row.issues or [],
        "generated_copy": row.generated_copy or {},
        "compliance_passed": row.compliance_passed,
        "compliance_notes": row.compliance_notes,
        "model_mode": normalized.get("model_mode", "saved draft"),
        "model_warnings": normalized.get("model_warnings", []),
        "status": row.status,
        "approved_by": row.approved_by or "",
        "_revision": _revision_stamp(row),
    }


def get_listing_rows(record_ids: list[str]) -> list[dict[str, Any]]:
    """Recover saved versions, including approvals, in the requested import order."""
    if not record_ids:
        return []
    with session_scope() as session:
        rows = session.scalars(select(ListingRecord).where(ListingRecord.id.in_(record_ids))).all()
        by_id = {row.id: row for row in rows}
        return [_listing_payload(by_id[key]) for key in dict.fromkeys(record_ids) if key in by_id]


def workspace_counts() -> dict[str, int]:
    """Exact workspace totals, independent of the paged review lists."""
    with session_scope() as session:
        return {
            "listing_total": session.scalar(select(func.count()).select_from(ListingRecord)) or 0,
            "listing_pending": session.scalar(select(func.count()).select_from(ListingRecord).where(ListingRecord.status != "approved")) or 0,
            "listing_approved": session.scalar(select(func.count()).select_from(ListingRecord).where(ListingRecord.status == "approved")) or 0,
            "support_total": session.scalar(select(func.count()).select_from(SupportCase)) or 0,
            "support_pending": session.scalar(select(func.count()).select_from(SupportCase).where(SupportCase.status != "approved_for_handoff")) or 0,
            "support_approved": session.scalar(select(func.count()).select_from(SupportCase).where(SupportCase.status == "approved_for_handoff")) or 0,
            "support_needs_review": session.scalar(select(func.count()).select_from(SupportCase).where(SupportCase.requires_human_escalation.is_(True), SupportCase.status != "approved_for_handoff")) or 0,
        }


def unapproved_listing_rows(limit: int | None = 100) -> list[dict[str, Any]]:
    """Return saved catalog work that is still a draft or needs an operator review."""
    with session_scope() as session:
        rows = session.scalars(
            select(ListingRecord)
            .where(ListingRecord.status != "approved")
            .order_by(ListingRecord.updated_at.desc())
            .limit(limit)
        ).all()
        return [_listing_payload(row) for row in rows]


def recent_support_cases(limit: int | None = 50) -> list[dict[str, Any]]:
    """Return recent saved cases so a Streamlit session can recover after a refresh."""
    with session_scope() as session:
        rows = session.scalars(
            select(SupportCase).order_by(SupportCase.updated_at.desc()).limit(limit)
        ).all()
        return [
            {
                "case_id": row.id,
                "ticket_text": row.ticket_text,
                "parsed_query": row.parsed_query or {},
                "order_id": row.order_id,
                "carrier_facts": row.carrier_facts or None,
                "policy_references": row.policy_references or [],
                "draft_reply": row.draft_reply,
                "factual_verification_passed": row.factual_verification_passed,
                "verification_notes": row.verification_notes,
                "requires_human_escalation": row.requires_human_escalation,
                "escalation_reason": row.escalation_reason,
                "status": row.status,
                "model_warnings": [],
                "saved": True,
                "_revision": _revision_stamp(row),
            }
            for row in rows
        ]


def save_listing_draft(record: dict[str, Any]) -> None:
    with session_scope(write=True) as session:
        row = session.get(ListingRecord, record["row_key"], with_for_update=True)
        created = row is None
        if created:
            row = ListingRecord(id=record["row_key"])
            session.add(row)
        elif row.status == "approved":
            raise ValueError("This listing is already approved. Reopen the saved work before continuing.")
        if not created:
            _check_revision(record, row)
        old_status, old_updated = row.status, row.updated_at
        if record.get("status") == "approved":
            raise ValueError("Approve the listing through its review action before adding it to exports.")
        if record.get("status", "draft") not in {"draft", "needs_review", "blocked"}:
            raise ValueError("This listing has an unsupported draft status. Reload it before saving.")
        before = _content_hash(row, LISTING_WRITE_FIELDS)
        _apply_listing_record(row, record)
        after = _content_hash(row, LISTING_WRITE_FIELDS)
        if not created and before != after:
            _write_existing(session, row, LISTING_WRITE_FIELDS, old_status, old_updated)
        if created or before != after:
            session.add(AuditEvent(entity_type="listing", entity_id=row.id, action="draft_created" if created else "draft_updated", detail={"content_hash": after}))
        session.flush()
        record["_revision"] = _revision_stamp(row)


def _apply_listing_record(row: ListingRecord, record: dict[str, Any]) -> None:
    row.source_filename = record.get("source_filename", "")
    row.vendor_sku = record.get("vendor_sku_raw", "")
    row.raw_payload = record.get("raw_payload", {})
    row.normalized_payload = {
        **record.get("normalized_payload", {}),
        **{key: record[key] for key in ("source_line_number", "inferred_color", "color_inference_reason", "model_mode", "model_warnings") if key in record},
    }
    row.generated_copy = record.get("generated_copy") or {}
    row.compliance_passed = record.get("compliance_passed")
    row.compliance_notes = record.get("compliance_notes", "")
    row.issues = record.get("issues", [])
    row.status = record.get("status", "draft")


def approve_listing(
    record_id: str,
    copy: dict[str, Any],
    actor: str = "operator",
    record: dict[str, Any] | None = None,
) -> None:
    with session_scope(write=True) as session:
        row = session.get(ListingRecord, record_id, with_for_update=True)
        if row is None:
            raise ValueError("This listing draft is not saved in the staging database.")
        if row.status == "approved":
            if row.generated_copy == copy and (record is None or all(
                row.normalized_payload.get(key) == value for key, value in record.get("normalized_payload", {}).items()
            )):
                return
            raise ValueError("This listing is already approved. Reload the saved listing before editing it.")
        if record is not None and record.get("row_key") != record_id:
            raise ValueError("The listing being reviewed does not match the saved draft.")
        if record is not None:
            _check_revision(record, row)
        old_status, old_updated = row.status, row.updated_at
        if record is not None:
            if record.get("raw_payload", {}) != (row.raw_payload or {}):
                raise ValueError("The supplier source changed. Import the corrected sheet before approval.")
            _apply_listing_record(row, record)
        if not str(row.vendor_sku or "").strip():
            raise ValueError("Add the vendor SKU before approving this listing.")
        if not str(row.normalized_payload.get("product_name") or "").strip():
            raise ValueError("Add the product name before approving this listing.")
        if not str(row.normalized_payload.get("fabric_composition") or "").strip():
            raise ValueError("Add the fabric or material before approving this listing.")
        if not str(row.normalized_payload.get("standard_color") or "").strip():
            raise ValueError("Choose a standard color before approving this listing.")
        if row.compliance_passed is not True:
            raise ValueError("The listing copy must pass the factual check before approval.")
        if row.issues:
            raise ValueError("Resolve the listed data issues before approving this listing.")
        from dhaga_os.catalog import _deterministic_copy_check, refresh_catalog_validation
        from dhaga_os.models import MasterColor

        if row.normalized_payload.get("standard_color") not in {color.value for color in MasterColor}:
            raise ValueError("Choose a color from the standard palette before approval.")
        if row.normalized_payload.get("model_audit_required") and not (
            row.normalized_payload.get("model_audit_passed") or row.normalized_payload.get("human_source_verified")
        ):
            raise ValueError("Compare every AI-written listing detail with the supplier sheet before approval.")
        final_record = {**row.normalized_payload, "row_key": row.id, "vendor_sku_raw": row.vendor_sku}
        final_record.update(generated_copy=copy, issues=row.issues, normalized_payload=dict(row.normalized_payload))
        refresh_catalog_validation(final_record)
        if final_record["issues"]:
            raise ValueError("Resolve the listing details before approval: " + "; ".join(final_record["issues"]))
        passed, notes = _deterministic_copy_check(final_record, copy)
        if not passed:
            raise ValueError("The final listing copy failed its factual check: " + notes)
        if copy.get("row_key") and copy["row_key"] != record_id:
            raise ValueError("The listing text belongs to a different product.")
        with session.no_autoflush:
            if get_engine().dialect.name == "postgresql":
                # Serialize approvals of the same normalized supplier code,
                # including records from different uploads, without rewriting
                # existing records or requiring a new database schema.
                lock_key = int.from_bytes(sha256(row.vendor_sku.strip().casefold().encode()).digest()[:8], "big", signed=True)
                session.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})
            duplicate = session.scalar(
                select(ListingRecord.id).where(
                    ListingRecord.id != row.id,
                    ListingRecord.status == "approved",
                    func.lower(func.trim(ListingRecord.vendor_sku)) == row.vendor_sku.strip().casefold(),
                ).limit(1)
            )
        if duplicate:
            raise ValueError("This supplier code already has an approved listing. Use its saved listing instead of approving a duplicate.")
        row.generated_copy = copy
        row.compliance_passed = True
        row.compliance_notes = notes
        row.status = "approved"
        row.approved_by = actor
        row.updated_at = utcnow()
        _write_existing(session, row, LISTING_WRITE_FIELDS, old_status, old_updated)
        session.add(
            AuditEvent(
                entity_type="listing",
                entity_id=record_id,
                action="approved_for_staging",
                actor=actor,
                detail={"sku": row.vendor_sku, "content_hash": _content_hash(row, ("normalized_payload", "generated_copy"))},
            )
        )
        session.flush()
        if record is not None:
            record["_revision"] = _revision_stamp(row)


def save_support_case(record: dict[str, Any]) -> None:
    with session_scope(write=True) as session:
        row = session.get(SupportCase, record["case_id"], with_for_update=True)
        created = row is None
        if created:
            row = SupportCase(id=record["case_id"], ticket_text=record["ticket_text"])
            session.add(row)
        elif row.status == "approved_for_handoff":
            raise ValueError("This reply is already approved. Reopen the saved work before continuing.")
        if not created:
            _check_revision(record, row)
        old_status, old_updated = row.status, row.updated_at
        if record.get("status") == "approved_for_handoff":
            raise ValueError("Approve the reply through its review action before adding it to exports.")
        if record.get("status", "draft") not in {"draft", "draft_ready", "needs_review", "needs_identifier", "blocked", "not_found", "sync_failed"}:
            raise ValueError("This case has an unsupported draft status. Reload it before saving.")
        if not created and ((record.get("carrier_facts") or {}) != (row.carrier_facts or {}) or record.get("order_id") != row.order_id):
            raise ValueError("The checked order changed. Check it again to create a new case.")
        before = _content_hash(row, SUPPORT_WRITE_FIELDS)
        _apply_support_case(row, record)
        after = _content_hash(row, SUPPORT_WRITE_FIELDS)
        if not created and before != after:
            _write_existing(session, row, SUPPORT_WRITE_FIELDS, old_status, old_updated)
        if created or before != after:
            session.add(AuditEvent(entity_type="support_case", entity_id=row.id, action="draft_created" if created else "draft_updated", detail={"content_hash": after}))
        session.flush()
        record["_revision"] = _revision_stamp(row)


def _apply_support_case(row: SupportCase, record: dict[str, Any]) -> None:
    row.ticket_text = record.get("ticket_text", "")
    row.parsed_query = record.get("parsed_query", {})
    row.order_id = record.get("order_id")
    row.carrier_facts = record.get("carrier_facts") or {}
    row.policy_references = record.get("policy_references", [])
    row.draft_reply = record.get("draft_reply", "")
    row.factual_verification_passed = record.get("factual_verification_passed")
    row.verification_notes = record.get("verification_notes", "")
    row.requires_human_escalation = record.get("requires_human_escalation", False)
    row.escalation_reason = record.get("escalation_reason", "")
    row.status = record.get("status", "draft")


def approve_support_case(
    case_id: str,
    reply: str,
    actor: str = "operator",
    record: dict[str, Any] | None = None,
) -> None:
    with session_scope(write=True) as session:
        row = session.get(SupportCase, case_id, with_for_update=True)
        if row is None:
            raise ValueError("This support draft is not saved in the staging database.")
        if row.status == "approved_for_handoff":
            if row.draft_reply == reply and (record is None or (
                (record.get("carrier_facts") or {}) == (row.carrier_facts or {})
                and record.get("order_id") == row.order_id
                and record.get("ticket_text") == row.ticket_text
            )):
                return
            raise ValueError("This reply is already approved. Reload the saved case before editing it.")
        if record is not None and record.get("case_id") != case_id:
            raise ValueError("The reply being reviewed does not match the saved case.")
        if record is not None:
            _check_revision(record, row)
        old_status, old_updated = row.status, row.updated_at
        if record is not None:
            if (record.get("carrier_facts") or {}) != (row.carrier_facts or {}):
                raise ValueError("The checked order details changed. Check the order again before approval.")
            if record.get("order_id") != row.order_id:
                raise ValueError("The order number changed. Check the order again before approval.")
            _apply_support_case(row, record)
        if not reply.strip():
            raise ValueError("Add a reply or handoff note before approving this case.")
        if row.status not in {"draft_ready", "needs_review", "needs_identifier"}:
            raise ValueError("This case is blocked from approval. Resolve its status first.")
        if row.carrier_facts:
            if row.carrier_facts.get("sync_status") != "OK":
                raise ValueError("Carrier data is unavailable. Keep this case in manual review.")
            if row.factual_verification_passed is not True:
                raise ValueError("The reply must pass the carrier fact check before approval.")
        elif row.status != "needs_identifier":
            raise ValueError("This case has no verified order record. Keep it in manual review.")
        from dhaga_os.cx import _deterministic_reply_check

        passed, notes = _deterministic_reply_check(reply, row.carrier_facts or {})
        if not passed:
            raise ValueError("The final reply failed its fact check: " + notes)
        row.draft_reply = reply
        row.verification_notes = notes
        row.factual_verification_passed = True if row.carrier_facts else None
        row.status = "approved_for_handoff"
        row.approved_by = actor
        row.updated_at = utcnow()
        _write_existing(session, row, SUPPORT_WRITE_FIELDS, old_status, old_updated)
        session.add(
            AuditEvent(
                entity_type="support_case",
                entity_id=case_id,
                action="approved_for_handoff",
                actor=actor,
                detail={"order_id": row.order_id, "content_hash": _content_hash(row, ("carrier_facts", "draft_reply"))},
            )
        )
        session.flush()
        if record is not None:
            record["_revision"] = _revision_stamp(row)


def approved_export_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    with session_scope() as session:
        listings = session.scalars(
            select(ListingRecord).where(ListingRecord.status == "approved").order_by(ListingRecord.updated_at.desc())
        ).all()
        cases = session.scalars(
            select(SupportCase).where(SupportCase.status == "approved_for_handoff").order_by(SupportCase.updated_at.desc())
        ).all()
        listing_rows = [
            {
                "listing_id": row.id,
                "sku": row.vendor_sku,
                "product": row.normalized_payload.get("product_name", ""),
                "category": row.normalized_payload.get("product_category", ""),
                "status": row.status,
                "title_hinglish": row.generated_copy.get("title_hinglish", ""),
                "description_hinglish": row.generated_copy.get("description_hinglish", ""),
                "standard_color": row.normalized_payload.get("standard_color", ""),
                "fabric_composition": row.normalized_payload.get("fabric_composition", ""),
                "fit_silhouette": row.normalized_payload.get("fit_silhouette", ""),
                "wash_care": row.normalized_payload.get("wash_care", ""),
                "sizes": row.normalized_payload.get("size_values", ""),
                "price": row.normalized_payload.get("price", ""),
                "key_highlights": " | ".join(str(value) for value in row.generated_copy.get("key_highlights", [])),
                "occasion_tags": " | ".join(str(value) for value in row.normalized_payload.get("occasion_tags", [])),
                "search_keywords": " | ".join(str(value) for value in row.generated_copy.get("search_keywords", [])),
                "source_filename": row.source_filename,
                "source_line_number": row.normalized_payload.get("source_line_number", ""),
                "compliance_passed": row.compliance_passed,
                "approved_by": row.approved_by or "",
                "approved_at_utc": row.updated_at.replace(tzinfo=timezone.utc).isoformat(),
            }
            for row in listings
        ]
        case_rows = [
            {
                "case_id": row.id,
                "order_id": row.order_id or "",
                "intent": row.parsed_query.get("detected_intent", ""),
                "draft_reply": row.draft_reply,
                "status": row.status,
                "agent_follow_up_required": row.requires_human_escalation,
                "follow_up_reason": row.escalation_reason,
                "facts_checked": row.factual_verification_passed,
                "carrier": row.carrier_facts.get("carrier_name", ""),
                "carrier_status": row.carrier_facts.get("current_status", ""),
                "carrier_location": row.carrier_facts.get("current_location", ""),
                "carrier_expected_date": row.carrier_facts.get("promised_delivery_date", ""),
                "policy_references": " | ".join(str(policy.get("policy_id", "")) for policy in row.policy_references),
                "approved_by": row.approved_by or "",
                "approved_at_utc": row.updated_at.replace(tzinfo=timezone.utc).isoformat(),
            }
            for row in cases
        ]
        return listing_rows, case_rows
