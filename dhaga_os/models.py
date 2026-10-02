from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class MasterColor(str, Enum):
    RED = "Red"
    MAROON = "Maroon"
    RANI_PINK = "Rani Pink"
    PEACH = "Peach"
    PINK = "Pink"
    NAVY_BLUE = "Navy Blue"
    ROYAL_BLUE = "Royal Blue"
    BLUE = "Blue"
    MUSTARD_YELLOW = "Mustard Yellow"
    YELLOW = "Yellow"
    ORANGE = "Orange"
    BOTTLE_GREEN = "Bottle Green"
    MINT_GREEN = "Mint Green"
    GREEN = "Green"
    BLACK = "Black"
    WHITE = "White"
    BEIGE = "Beige"
    CREAM = "Cream"
    RUST = "Rust"
    MULTICOLOR = "Multicolor"
    PURPLE = "Purple"
    LAVENDER = "Lavender"
    GREY = "Grey"
    BROWN = "Brown"


class TicketIntent(str, Enum):
    WISMO = "WISMO"
    RETURN_REQUEST = "RETURN_REQUEST"
    CANCELLATION = "CANCELLATION"
    ESCALATION = "ESCALATION"
    OTHER = "OTHER"


class Sentiment(str, Enum):
    ANXIOUS = "ANXIOUS"
    ANGRY = "ANGRY"
    NEUTRAL = "NEUTRAL"
    POLITE = "POLITE"


class CatalogAttribute(BaseModel):
    row_key: str
    product_category: str = ""
    fabric_composition: str = ""
    fit_silhouette: str = ""
    wash_care: str = ""
    occasion_tags: list[str] = Field(default_factory=list)


class CatalogAttributeBatch(BaseModel):
    items: list[CatalogAttribute]


class CatalogColorInference(BaseModel):
    row_key: str
    inferred_color: MasterColor
    reason: str = ""


class CatalogColorInferenceBatch(BaseModel):
    items: list[CatalogColorInference]


class CatalogCopy(BaseModel):
    row_key: str
    title_hinglish: str
    description_hinglish: str
    key_highlights: list[str] = Field(min_length=1, max_length=5)
    search_keywords: list[str] = Field(default_factory=list)


class CatalogCopyBatch(BaseModel):
    items: list[CatalogCopy]


class CatalogAudit(BaseModel):
    row_key: str
    factual_compliance_pass: bool
    compliance_notes: str = ""


class CatalogAuditBatch(BaseModel):
    items: list[CatalogAudit]


class ParsedCustomerQuery(BaseModel):
    detected_intent: TicketIntent
    order_id: Optional[str] = None
    phone_number: Optional[str] = None
    sentiment: Sentiment = Sentiment.NEUTRAL
    language: str = "Hinglish"


class ParsedCustomerQueryBatch(BaseModel):
    result: ParsedCustomerQuery


class CXDraft(BaseModel):
    draft_reply_hinglish: str
    carrier_status_summary: str
    policy_reference: str = ""
    requires_human_escalation: bool = False
    escalation_reason: str = ""


class CXAudit(BaseModel):
    factual_verification_passed: bool
    notes: str = ""
