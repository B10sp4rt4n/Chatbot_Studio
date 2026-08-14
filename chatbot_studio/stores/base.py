from __future__ import annotations

from typing import Protocol

from chatbot_studio.contracts import EventDraft, EventEnvelope
from chatbot_studio.recordia import VerificationReport


class EventStore(Protocol):
    def append(self, draft: EventDraft) -> EventEnvelope: ...

    def get(self, tenant_id: str, event_id: str) -> EventEnvelope | None: ...

    def list_interaction(self, tenant_id: str, interaction_id: str) -> list[EventEnvelope]: ...

    def list_tenant(self, tenant_id: str) -> list[EventEnvelope]: ...

    def verify_tenant_chain(self, tenant_id: str) -> VerificationReport: ...
