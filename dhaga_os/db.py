from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Iterator
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Index, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from dhaga_os.config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
def session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def is_database_persistent() -> bool:
    return bool(get_settings().database_url)


def unapproved_listing_rows(limit: int = 100) -> list[dict[str, Any]]:
    """Return saved catalog work that is still a draft or needs an operator review."""
    with session_scope() as session:
        rows = session.scalars(
            select(ListingRecord)
            .where(ListingRecord.status != "approved")
            .order_by(ListingRecord.updated_at.desc())
            .limit(limit)
        ).all()
        result = []
        for row in rows:
            normalized = row.normalized_payload or {}
            result.append(
                {
                    "row_key": row.id,
                    "source_filename": row.source_filename,
                    "vendor_sku_raw": row.vendor_sku,
                    "product_name": normalized.get("product_name", ""),
                    "product_category": normalized.get("product_category", ""),
                    "raw_color_input": normalized.get("raw_color_input", ""),
                    "standard_color": normalized.get("standard_color", ""),
                    "inferred_color": "",
                    "color_inference_reason": "",
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
                    "model_mode": "saved draft",
                    "model_warnings": [],
                    "status": row.status,
                }
            )
        return result


def recent_support_cases(limit: int = 50) -> list[dict[str, Any]]:
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
            }
            for row in rows
        ]


def save_listing_draft(record: dict[str, Any]) -> None:
    with session_scope() as session:
        row = session.get(ListingRecord, record["row_key"])
        if row is None:
            row = ListingRecord(id=record["row_key"])
            session.add(row)
        row.source_filename = record.get("source_filename", "")
        row.vendor_sku = record.get("vendor_sku_raw", "")
        row.raw_payload = record.get("raw_payload", {})
        row.normalized_payload = record.get("normalized_payload", {})
        row.generated_copy = record.get("generated_copy") or {}
        row.compliance_passed = record.get("compliance_passed")
        row.compliance_notes = record.get("compliance_notes", "")
        row.issues = record.get("issues", [])
        row.status = record.get("status", "draft")


def _apply_listing_record(row: ListingRecord, record: dict[str, Any]) -> None:
    row.source_filename = record.get("source_filename", "")
    row.vendor_sku = record.get("vendor_sku_raw", "")
    row.raw_payload = record.get("raw_payload", {})
    row.normalized_payload = record.get("normalized_payload", {})
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
    with session_scope() as session:
        row = session.get(ListingRecord, record_id)
        if row is None:
            raise ValueError("This listing draft is not saved in the staging database.")
        if record is not None:
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
        row.generated_copy = copy
        row.status = "approved"
        row.approved_by = actor
        row.updated_at = utcnow()
        session.add(
            AuditEvent(
                entity_type="listing",
                entity_id=record_id,
                action="approved_for_staging",
                actor=actor,
                detail={"sku": row.vendor_sku},
            )
        )


def save_support_case(record: dict[str, Any]) -> None:
    with session_scope() as session:
        row = session.get(SupportCase, record["case_id"])
        if row is None:
            row = SupportCase(id=record["case_id"], ticket_text=record["ticket_text"])
            session.add(row)
        row.ticket_text = record["ticket_text"]
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
    with session_scope() as session:
        row = session.get(SupportCase, case_id)
        if row is None:
            raise ValueError("This support draft is not saved in the staging database.")
        if record is not None:
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
        row.draft_reply = reply
        row.status = "approved_for_handoff"
        row.approved_by = actor
        row.updated_at = utcnow()
        session.add(
            AuditEvent(
                entity_type="support_case",
                entity_id=case_id,
                action="approved_for_handoff",
                actor=actor,
                detail={"order_id": row.order_id},
            )
        )


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
                "sku": row.vendor_sku,
                "product": row.normalized_payload.get("product_name", ""),
                "status": row.status,
                "title_hinglish": row.generated_copy.get("title_hinglish", ""),
                "description_hinglish": row.generated_copy.get("description_hinglish", ""),
                "standard_color": row.normalized_payload.get("standard_color", ""),
                "fabric_composition": row.normalized_payload.get("fabric_composition", ""),
                "sizes": row.normalized_payload.get("size_values", ""),
                "compliance_passed": row.compliance_passed,
                "approved_by": row.approved_by or "",
            }
            for row in listings
        ]
        case_rows = [
            {
                "order_id": row.order_id or "",
                "intent": row.parsed_query.get("detected_intent", ""),
                "draft_reply": row.draft_reply,
                "status": row.status,
                "agent_follow_up_required": row.requires_human_escalation,
                "follow_up_reason": row.escalation_reason,
                "facts_checked": row.factual_verification_passed,
                "approved_by": row.approved_by or "",
            }
            for row in cases
        ]
        return listing_rows, case_rows
