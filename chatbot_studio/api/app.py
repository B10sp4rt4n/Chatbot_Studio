from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query

from chatbot_studio.contracts import EventDraft
from chatbot_studio.projections import build_interaction_package
from chatbot_studio.recordia.trajectory import TrajectoryError
from chatbot_studio.stores import SQLiteEventStore


def create_app(database_path: str | Path | None = None) -> FastAPI:
    path = database_path or os.getenv("CHATBOT_STUDIO_EVENT_DB", "chatbot_studio_events.sqlite3")
    store = SQLiteEventStore(path)
    application = FastAPI(
        title="Chatbot Studio Governance API",
        version="0.1.0",
        description="Eventos temporales inmutables para gobierno del uso empresarial de IA.",
    )
    application.state.event_store = store

    @application.get("/health")
    def health() -> dict:
        return {"ok": True, "contract": "chatbot-studio.event.v0.1"}

    @application.post("/v1/events", status_code=201)
    def append_event(draft: EventDraft) -> dict:
        try:
            return store.append(draft).model_dump(mode="json")
        except (ValueError, TrajectoryError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @application.get("/v1/events/{event_id}")
    def get_event(event_id: str, tenant_id: str = Query(min_length=1)) -> dict:
        event = store.get(tenant_id, event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Evento no encontrado en el tenant")
        return event.model_dump(mode="json")

    @application.get("/v1/interactions/{interaction_id}")
    def get_interaction(interaction_id: str, tenant_id: str = Query(min_length=1)) -> dict:
        events = store.list_interaction(tenant_id, interaction_id)
        if not events:
            raise HTTPException(status_code=404, detail="Interacción no encontrada en el tenant")
        return build_interaction_package(events)

    @application.get("/v1/users/{user_id}/usage")
    def get_user_usage(user_id: str, tenant_id: str = Query(min_length=1)) -> dict:
        return store.user_usage(tenant_id, user_id)

    @application.get("/v1/tenants/{tenant_id}/metrics")
    def get_tenant_metrics(tenant_id: str) -> dict:
        return store.tenant_metrics(tenant_id)

    @application.post("/v1/tenants/{tenant_id}/verify-chain")
    def verify_tenant_chain(tenant_id: str) -> dict:
        return store.verify_tenant_chain(tenant_id).model_dump()

    return application


app = create_app()
