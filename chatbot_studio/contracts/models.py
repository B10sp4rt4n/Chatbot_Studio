from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SCHEMA_VERSION = "chatbot-studio.event.v0.1"
CANONICALIZATION_VERSION = "CS-CANONICAL-JSON-v1"
HASH_PATTERN = r"^(GENESIS|[0-9a-f]{64})$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"


class EventType(StrEnum):
    INTERACTION_RECEIVED = "INTERACTION_RECEIVED"
    IDENTITY_VERIFIED = "IDENTITY_VERIFIED"
    CONTENT_INSPECTED = "CONTENT_INSPECTED"
    POLICY_DECIDED = "POLICY_DECIDED"
    AWARENESS_PRESENTED = "AWARENESS_PRESENTED"
    USER_ACKNOWLEDGED = "USER_ACKNOWLEDGED"
    REVIEW_APPROVED = "REVIEW_APPROVED"
    REVIEW_REJECTED = "REVIEW_REJECTED"
    PROVIDER_REQUESTED = "PROVIDER_REQUESTED"
    PROVIDER_RESPONDED = "PROVIDER_RESPONDED"
    INTERACTION_RECORDED = "INTERACTION_RECORDED"
    EVIDENCE_VAULTED = "EVIDENCE_VAULTED"


class Decision(StrEnum):
    ALLOW = "ALLOW"
    TOKENIZE = "TOKENIZE"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


class UserState(StrEnum):
    NORMAL = "NORMAL"
    GUIDED = "GUIDED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    SUSPENDED = "SUSPENDED"


class Actor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_type: Literal["user", "system", "service", "approver"]
    actor_id: str = Field(min_length=1, max_length=160)
    role: str | None = Field(default=None, max_length=160)


class EventDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    schema_version: Literal["chatbot-studio.event.v0.1"] = SCHEMA_VERSION
    event_id: str = Field(default_factory=lambda: f"evt_{uuid4().hex}", min_length=8, max_length=96)
    event_type: EventType
    tenant_id: str = Field(min_length=1, max_length=160)
    user_id: str = Field(min_length=1, max_length=160)
    session_id: str = Field(min_length=1, max_length=160)
    interaction_id: str = Field(min_length=1, max_length=160)
    occurred_at: datetime
    actor: Actor
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at debe incluir zona horaria")
        return value


class EventEnvelope(EventDraft):
    sequence_no: int = Field(ge=1)
    recorded_at: datetime
    previous_hash: str = Field(pattern=HASH_PATTERN)
    payload_hash: str = Field(pattern=SHA256_PATTERN)
    record_hash: str = Field(pattern=SHA256_PATTERN)
    hash_algorithm: Literal["SHA-256"] = "SHA-256"
    canonicalization: Literal["CS-CANONICAL-JSON-v1"] = CANONICALIZATION_VERSION

    @field_validator("recorded_at")
    @classmethod
    def require_recorded_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recorded_at debe incluir zona horaria")
        return value

    @model_validator(mode="after")
    def validate_temporal_order(self) -> EventEnvelope:
        if self.recorded_at < self.occurred_at:
            raise ValueError("recorded_at no puede ser anterior a occurred_at")
        return self
