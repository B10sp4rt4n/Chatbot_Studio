from __future__ import annotations

from datetime import datetime, timezone
from pydantic import BaseModel, Field

from chatbot_studio.contracts import EventDraft, EventEnvelope
from chatbot_studio.recordia.canonical import sha256_hex
from chatbot_studio.recordia.trajectory import trajectory_errors


class VerificationReport(BaseModel):
    valid: bool
    checked_events: int = Field(ge=0)
    errors: list[str] = Field(default_factory=list)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def seal_event(
    draft: EventDraft,
    sequence_no: int,
    previous_hash: str,
    recorded_at: datetime | None = None,
) -> EventEnvelope:
    final_recorded_at = recorded_at or utc_now()
    if final_recorded_at < draft.occurred_at:
        final_recorded_at = draft.occurred_at
    payload_hash = sha256_hex(draft.payload)
    unsigned = {
        **draft.model_dump(),
        "sequence_no": sequence_no,
        "recorded_at": final_recorded_at,
        "previous_hash": previous_hash,
        "payload_hash": payload_hash,
        "record_hash": "0" * 64,
        "hash_algorithm": "SHA-256",
        "canonicalization": "CS-CANONICAL-JSON-v1",
    }
    provisional = EventEnvelope.model_validate(unsigned)
    record_hash = sha256_hex(provisional.model_dump(exclude={"record_hash"}))
    return provisional.model_copy(update={"record_hash": record_hash})


def verify_event(event: EventEnvelope) -> VerificationReport:
    errors: list[str] = []
    calculated_payload_hash = sha256_hex(event.payload)
    calculated_record_hash = sha256_hex(event.model_dump(exclude={"record_hash"}))
    if calculated_payload_hash != event.payload_hash:
        errors.append(f"{event.event_id}: payload_hash inválido")
    if calculated_record_hash != event.record_hash:
        errors.append(f"{event.event_id}: record_hash inválido")
    if event.recorded_at < event.occurred_at:
        errors.append(f"{event.event_id}: orden temporal inválido")
    return VerificationReport(valid=not errors, checked_events=1, errors=errors)


def verify_chain(events: list[EventEnvelope]) -> VerificationReport:
    ordered = sorted(events, key=lambda event: event.sequence_no)
    errors: list[str] = []
    if not ordered:
        return VerificationReport(valid=True, checked_events=0)

    expected_tenant = ordered[0].tenant_id
    previous_hash = "GENESIS"
    expected_sequence = 1
    interactions: dict[str, list[EventEnvelope]] = {}

    for event in ordered:
        event_report = verify_event(event)
        errors.extend(event_report.errors)
        if event.tenant_id != expected_tenant:
            errors.append(f"{event.event_id}: tenant distinto dentro de la cadena")
        if event.sequence_no != expected_sequence:
            errors.append(
                f"{event.event_id}: secuencia {event.sequence_no}, se esperaba {expected_sequence}"
            )
            expected_sequence = event.sequence_no
        if event.previous_hash != previous_hash:
            errors.append(f"{event.event_id}: previous_hash no coincide")
        previous_hash = event.record_hash
        expected_sequence += 1
        interactions.setdefault(event.interaction_id, []).append(event)

    for interaction_events in interactions.values():
        errors.extend(trajectory_errors(interaction_events))
    return VerificationReport(valid=not errors, checked_events=len(ordered), errors=errors)
