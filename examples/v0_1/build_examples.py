"""Genera cuatro trayectorias v0.1 con hashes reales y las imprime como JSON."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from chatbot_studio.contracts import Actor, Decision, EventDraft, EventType
from chatbot_studio.stores import SQLiteEventStore


BASE = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


def append(store, interaction_id, event_type, second, payload, tenant_id="tenant-demo"):
    return store.append(
        EventDraft(
            event_id=f"evt_{interaction_id}_{event_type.value.lower()}",
            event_type=event_type,
            tenant_id=tenant_id,
            user_id="user-demo",
            session_id=f"session-{interaction_id}",
            interaction_id=interaction_id,
            occurred_at=BASE + timedelta(seconds=second),
            actor=Actor(actor_type="service", actor_id="chatbot-studio"),
            payload=payload,
        )
    )


def scenario(store, name, decision):
    events = [
        append(store, name, EventType.INTERACTION_RECEIVED, 0, {"channel": "web"}),
        append(store, name, EventType.IDENTITY_VERIFIED, 1, {"role": "employee", "state": "NORMAL"}),
        append(store, name, EventType.CONTENT_INSPECTED, 2, {"findings": [], "risk": 14}),
        append(store, name, EventType.POLICY_DECIDED, 3, {"decision": decision.value, "policy": "AUP-AI-GOV.v0.1"}),
    ]
    if decision != Decision.ALLOW:
        events.append(append(store, name, EventType.AWARENESS_PRESENTED, 4, {"reason": decision.value}))
    if decision in {Decision.ALLOW, Decision.TOKENIZE}:
        events.append(append(store, name, EventType.PROVIDER_REQUESTED, 5, {"provider": "OpenAI"}))
        events.append(append(store, name, EventType.PROVIDER_RESPONDED, 6, {"provider": "OpenAI", "status": "complete"}))
        events.append(append(store, name, EventType.INTERACTION_RECORDED, 7, {"outcome": "completed"}))
    elif decision == Decision.BLOCK:
        events.append(append(store, name, EventType.USER_ACKNOWLEDGED, 5, {"acknowledged": True}))
        recorded = append(store, name, EventType.INTERACTION_RECORDED, 6, {"outcome": "blocked"})
        events.append(recorded)
        events.append(
            append(
                store,
                name,
                EventType.EVIDENCE_VAULTED,
                7,
                {
                    "parent_event_id": recorded.event_id,
                    "parent_record_hash": recorded.record_hash,
                    "vault_reference": f"hotvault://demo/{name}",
                },
            )
        )
    return events


def main():
    with tempfile.TemporaryDirectory() as directory:
        store = SQLiteEventStore(Path(directory) / "examples.sqlite3")
        output = {
            decision.value.lower(): [event.model_dump(mode="json") for event in scenario(store, f"interaction-{decision.value.lower()}", decision)]
            for decision in Decision
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
