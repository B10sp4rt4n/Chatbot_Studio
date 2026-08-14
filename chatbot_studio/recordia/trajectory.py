from __future__ import annotations

from collections import Counter

from chatbot_studio.contracts import Decision, EventEnvelope, EventType


class TrajectoryError(ValueError):
    pass


SINGLETON_EVENTS = {
    EventType.INTERACTION_RECEIVED,
    EventType.IDENTITY_VERIFIED,
    EventType.CONTENT_INSPECTED,
    EventType.POLICY_DECIDED,
    EventType.AWARENESS_PRESENTED,
    EventType.USER_ACKNOWLEDGED,
    EventType.REVIEW_APPROVED,
    EventType.REVIEW_REJECTED,
    EventType.PROVIDER_REQUESTED,
    EventType.PROVIDER_RESPONDED,
    EventType.INTERACTION_RECORDED,
    EventType.EVIDENCE_VAULTED,
}


def trajectory_errors(events: list[EventEnvelope]) -> list[str]:
    if not events:
        return []

    ordered = sorted(events, key=lambda event: event.sequence_no)
    errors: list[str] = []
    expected_tenant = ordered[0].tenant_id
    expected_interaction = ordered[0].interaction_id
    counts = Counter(event.event_type for event in ordered)

    if ordered[0].event_type != EventType.INTERACTION_RECEIVED:
        errors.append("La trayectoria debe iniciar con INTERACTION_RECEIVED")
    for event_type in SINGLETON_EVENTS:
        if counts[event_type] > 1:
            errors.append(f"{event_type.value} no puede repetirse en la misma interacción")

    seen: set[EventType] = set()
    decision: Decision | None = None
    review_resolution: EventType | None = None
    provider_requested = False
    provider_responded = False
    finalized = False
    last_occurred_at = ordered[0].occurred_at

    for event in ordered:
        if event.tenant_id != expected_tenant:
            errors.append(f"{event.event_id}: referencia a tenant distinto")
        if event.interaction_id != expected_interaction:
            errors.append(f"{event.event_id}: interacción distinta dentro de la trayectoria")
        if event.occurred_at < last_occurred_at:
            errors.append(f"{event.event_id}: occurred_at rompe el orden temporal")
        last_occurred_at = max(last_occurred_at, event.occurred_at)

        event_type = event.event_type
        if finalized and event_type != EventType.EVIDENCE_VAULTED:
            errors.append(f"{event.event_id}: sólo EVIDENCE_VAULTED puede seguir al cierre")

        if event_type == EventType.IDENTITY_VERIFIED and EventType.INTERACTION_RECEIVED not in seen:
            errors.append("IDENTITY_VERIFIED requiere INTERACTION_RECEIVED")
        elif event_type == EventType.CONTENT_INSPECTED and EventType.IDENTITY_VERIFIED not in seen:
            errors.append("CONTENT_INSPECTED requiere IDENTITY_VERIFIED")
        elif event_type == EventType.POLICY_DECIDED:
            if EventType.CONTENT_INSPECTED not in seen:
                errors.append("POLICY_DECIDED requiere CONTENT_INSPECTED")
            try:
                decision = Decision(event.payload.get("decision"))
            except (TypeError, ValueError):
                errors.append("POLICY_DECIDED requiere una decisión AUP válida")
        elif event_type == EventType.AWARENESS_PRESENTED and EventType.POLICY_DECIDED not in seen:
            errors.append("AWARENESS_PRESENTED requiere POLICY_DECIDED")
        elif event_type == EventType.USER_ACKNOWLEDGED and EventType.AWARENESS_PRESENTED not in seen:
            errors.append("USER_ACKNOWLEDGED requiere AWARENESS_PRESENTED")
        elif event_type in {EventType.REVIEW_APPROVED, EventType.REVIEW_REJECTED}:
            if decision != Decision.REVIEW:
                errors.append(f"{event_type.value} requiere decisión REVIEW")
            if review_resolution is not None:
                errors.append("La revisión ya tenía una resolución")
            review_resolution = event_type
        elif event_type == EventType.PROVIDER_REQUESTED:
            allowed = decision in {Decision.ALLOW, Decision.TOKENIZE}
            allowed_after_review = decision == Decision.REVIEW and review_resolution == EventType.REVIEW_APPROVED
            if not (allowed or allowed_after_review):
                errors.append("PROVIDER_REQUESTED no está autorizado por la decisión AUP")
            provider_requested = True
        elif event_type == EventType.PROVIDER_RESPONDED:
            if not provider_requested:
                errors.append("PROVIDER_RESPONDED requiere PROVIDER_REQUESTED")
            provider_responded = True
        elif event_type == EventType.INTERACTION_RECORDED:
            if decision is None:
                errors.append("INTERACTION_RECORDED requiere POLICY_DECIDED")
            if decision in {Decision.TOKENIZE, Decision.REVIEW, Decision.BLOCK} and EventType.AWARENESS_PRESENTED not in seen:
                errors.append("Una intervención AUP debe presentar awareness antes del cierre")
            if provider_requested and not provider_responded and event.payload.get("provider_status") != "error":
                errors.append("La solicitud al proveedor no tiene respuesta ni error registrado")
            finalized = True
        elif event_type == EventType.EVIDENCE_VAULTED:
            if not finalized:
                errors.append("EVIDENCE_VAULTED requiere INTERACTION_RECORDED")
            if not event.payload.get("parent_event_id") or not event.payload.get("parent_record_hash"):
                errors.append("EVIDENCE_VAULTED requiere referencia al registro preservado")

        seen.add(event_type)

    if decision == Decision.BLOCK and provider_requested:
        errors.append("Una interacción BLOCK no puede enviarse al proveedor")
    if review_resolution == EventType.REVIEW_REJECTED and provider_requested:
        errors.append("Una revisión rechazada no puede enviarse al proveedor")
    return errors


def ensure_trajectory_valid(events: list[EventEnvelope]) -> None:
    errors = trajectory_errors(events)
    if errors:
        raise TrajectoryError("; ".join(errors))
