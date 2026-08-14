from __future__ import annotations

from typing import Any

from chatbot_studio.contracts import EventEnvelope, EventType


TIMELINE_FIELDS = {
    EventType.INTERACTION_RECEIVED: "occurred_at",
    EventType.IDENTITY_VERIFIED: "identity_verified_at",
    EventType.CONTENT_INSPECTED: "inspected_at",
    EventType.POLICY_DECIDED: "decided_at",
    EventType.AWARENESS_PRESENTED: "awareness_presented_at",
    EventType.USER_ACKNOWLEDGED: "user_acknowledged_at",
    EventType.REVIEW_APPROVED: "review_approved_at",
    EventType.REVIEW_REJECTED: "review_rejected_at",
    EventType.PROVIDER_REQUESTED: "sent_to_provider_at",
    EventType.PROVIDER_RESPONDED: "response_received_at",
    EventType.INTERACTION_RECORDED: "recorded_at",
    EventType.EVIDENCE_VAULTED: "vaulted_at",
}


def build_interaction_package(events: list[EventEnvelope]) -> dict[str, Any]:
    if not events:
        raise ValueError("No hay eventos para reconstruir")
    ordered = sorted(events, key=lambda event: event.sequence_no)
    tenant_id = ordered[0].tenant_id
    interaction_id = ordered[0].interaction_id
    if any(event.tenant_id != tenant_id or event.interaction_id != interaction_id for event in ordered):
        raise ValueError("Los eventos no pertenecen a la misma trayectoria")

    timeline: dict[str, str | None] = {field: None for field in TIMELINE_FIELDS.values()}
    sections: dict[str, Any] = {
        "identity": None,
        "needleai": None,
        "aup": None,
        "awareness": None,
        "provider": {"request": None, "response": None},
        "hotvault": None,
    }
    for event in ordered:
        timestamp = event.recorded_at if event.event_type == EventType.INTERACTION_RECORDED else event.occurred_at
        timeline[TIMELINE_FIELDS[event.event_type]] = timestamp.isoformat().replace("+00:00", "Z")
        if event.event_type == EventType.IDENTITY_VERIFIED:
            sections["identity"] = event.payload
        elif event.event_type == EventType.CONTENT_INSPECTED:
            sections["needleai"] = event.payload
        elif event.event_type == EventType.POLICY_DECIDED:
            sections["aup"] = event.payload
        elif event.event_type in {EventType.AWARENESS_PRESENTED, EventType.USER_ACKNOWLEDGED}:
            sections["awareness"] = {**(sections["awareness"] or {}), event.event_type.value.lower(): event.payload}
        elif event.event_type == EventType.PROVIDER_REQUESTED:
            sections["provider"]["request"] = event.payload
        elif event.event_type == EventType.PROVIDER_RESPONDED:
            sections["provider"]["response"] = event.payload
        elif event.event_type == EventType.EVIDENCE_VAULTED:
            sections["hotvault"] = event.payload

    return {
        "schema_version": "chatbot-studio.interaction.v0.1",
        "interaction_id": interaction_id,
        "tenant_id": tenant_id,
        "user_id": ordered[0].user_id,
        "session_id": ordered[0].session_id,
        **sections,
        "timeline": timeline,
        "recordia": {
            "first_sequence_no": ordered[0].sequence_no,
            "last_sequence_no": ordered[-1].sequence_no,
            "first_record_hash": ordered[0].record_hash,
            "last_record_hash": ordered[-1].record_hash,
            "events": len(ordered),
        },
    }
