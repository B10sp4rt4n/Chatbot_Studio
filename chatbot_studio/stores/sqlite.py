from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable

from chatbot_studio.contracts import EventDraft, EventEnvelope, EventType
from chatbot_studio.recordia import VerificationReport, seal_event, verify_chain
from chatbot_studio.recordia.chain import utc_now
from chatbot_studio.recordia.trajectory import ensure_trajectory_valid


class SQLiteEventStore:
    """Event store append-only para desarrollo, pruebas y demostraciones."""

    def __init__(self, database_path: str | Path = "chatbot_studio_events.sqlite3", clock: Callable[[], datetime] = utc_now):
        self.database_path = str(database_path)
        self.clock = clock
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS governance_events (
                    event_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    interaction_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL,
                    occurred_at TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    record_hash TEXT NOT NULL UNIQUE,
                    event_json TEXT NOT NULL,
                    UNIQUE (tenant_id, sequence_no)
                );
                CREATE INDEX IF NOT EXISTS idx_governance_events_interaction
                    ON governance_events (tenant_id, interaction_id, sequence_no);
                CREATE INDEX IF NOT EXISTS idx_governance_events_user
                    ON governance_events (tenant_id, user_id, sequence_no);
                CREATE INDEX IF NOT EXISTS idx_governance_events_type
                    ON governance_events (tenant_id, event_type);
                CREATE TRIGGER IF NOT EXISTS governance_events_no_update
                BEFORE UPDATE ON governance_events
                BEGIN
                    SELECT RAISE(ABORT, 'governance_events is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS governance_events_no_delete
                BEFORE DELETE ON governance_events
                BEGIN
                    SELECT RAISE(ABORT, 'governance_events is append-only');
                END;
                """
            )

    @staticmethod
    def _deserialize(row: sqlite3.Row) -> EventEnvelope:
        return EventEnvelope.model_validate_json(row["event_json"])

    @staticmethod
    def _serialize(event: EventEnvelope) -> str:
        return json.dumps(event.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))

    def _validate_parent_reference(self, connection: sqlite3.Connection, draft: EventDraft) -> None:
        parent_event_id = draft.payload.get("parent_event_id")
        if not parent_event_id:
            return
        row = connection.execute(
            "SELECT tenant_id, interaction_id, event_type, record_hash FROM governance_events WHERE event_id = ?",
            (parent_event_id,),
        ).fetchone()
        if row is None:
            raise ValueError("parent_event_id no existe")
        if row["tenant_id"] != draft.tenant_id:
            raise ValueError("Referencia entre tenants rechazada")
        if row["interaction_id"] != draft.interaction_id:
            raise ValueError("Referencia entre interacciones rechazada")
        parent_record_hash = draft.payload.get("parent_record_hash")
        if parent_record_hash and parent_record_hash != row["record_hash"]:
            raise ValueError("parent_record_hash no coincide")
        if draft.event_type == EventType.EVIDENCE_VAULTED and row["event_type"] != EventType.INTERACTION_RECORDED.value:
            raise ValueError("EVIDENCE_VAULTED sólo puede preservar INTERACTION_RECORDED")

    def append(self, draft: EventDraft) -> EventEnvelope:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            duplicate = connection.execute(
                "SELECT 1 FROM governance_events WHERE event_id = ?", (draft.event_id,)
            ).fetchone()
            if duplicate is not None:
                raise ValueError("event_id ya existe")
            self._validate_parent_reference(connection, draft)
            last_row = connection.execute(
                """
                SELECT sequence_no, record_hash
                FROM governance_events
                WHERE tenant_id = ?
                ORDER BY sequence_no DESC
                LIMIT 1
                """,
                (draft.tenant_id,),
            ).fetchone()
            sequence_no = 1 if last_row is None else int(last_row["sequence_no"]) + 1
            previous_hash = "GENESIS" if last_row is None else str(last_row["record_hash"])
            event = seal_event(
                draft,
                sequence_no=sequence_no,
                previous_hash=previous_hash,
                recorded_at=self.clock(),
            )
            existing_rows = connection.execute(
                """
                SELECT event_json
                FROM governance_events
                WHERE tenant_id = ? AND interaction_id = ?
                ORDER BY sequence_no ASC
                """,
                (draft.tenant_id, draft.interaction_id),
            ).fetchall()
            trajectory = [EventEnvelope.model_validate_json(row["event_json"]) for row in existing_rows]
            ensure_trajectory_valid([*trajectory, event])
            connection.execute(
                """
                INSERT INTO governance_events (
                    event_id, tenant_id, user_id, session_id, interaction_id,
                    event_type, sequence_no, occurred_at, recorded_at,
                    previous_hash, record_hash, event_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.tenant_id,
                    event.user_id,
                    event.session_id,
                    event.interaction_id,
                    event.event_type.value,
                    event.sequence_no,
                    event.occurred_at.isoformat(),
                    event.recorded_at.isoformat(),
                    event.previous_hash,
                    event.record_hash,
                    self._serialize(event),
                ),
            )
            connection.commit()
            return event
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get(self, tenant_id: str, event_id: str) -> EventEnvelope | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT event_json FROM governance_events WHERE tenant_id = ? AND event_id = ?",
                (tenant_id, event_id),
            ).fetchone()
        return None if row is None else EventEnvelope.model_validate_json(row["event_json"])

    def list_interaction(self, tenant_id: str, interaction_id: str) -> list[EventEnvelope]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_json FROM governance_events
                WHERE tenant_id = ? AND interaction_id = ?
                ORDER BY sequence_no ASC
                """,
                (tenant_id, interaction_id),
            ).fetchall()
        return [EventEnvelope.model_validate_json(row["event_json"]) for row in rows]

    def list_tenant(self, tenant_id: str) -> list[EventEnvelope]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_json FROM governance_events
                WHERE tenant_id = ?
                ORDER BY sequence_no ASC
                """,
                (tenant_id,),
            ).fetchall()
        return [EventEnvelope.model_validate_json(row["event_json"]) for row in rows]

    def verify_tenant_chain(self, tenant_id: str) -> VerificationReport:
        return verify_chain(self.list_tenant(tenant_id))

    def user_usage(self, tenant_id: str, user_id: str) -> dict:
        with self._connect() as connection:
            events = connection.execute(
                """
                SELECT event_type, event_json
                FROM governance_events
                WHERE tenant_id = ? AND user_id = ?
                ORDER BY sequence_no ASC
                """,
                (tenant_id, user_id),
            ).fetchall()
        decisions: dict[str, int] = {}
        interaction_ids: set[str] = set()
        for row in events:
            event = EventEnvelope.model_validate_json(row["event_json"])
            interaction_ids.add(event.interaction_id)
            if event.event_type == EventType.POLICY_DECIDED:
                decision = str(event.payload.get("decision", "UNKNOWN"))
                decisions[decision] = decisions.get(decision, 0) + 1
        return {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "interactions": len(interaction_ids),
            "events": len(events),
            "decisions": decisions,
        }

    def tenant_metrics(self, tenant_id: str) -> dict:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_type, event_json
                FROM governance_events
                WHERE tenant_id = ?
                ORDER BY sequence_no ASC
                """,
                (tenant_id,),
            ).fetchall()
        event_types: dict[str, int] = {}
        decisions: dict[str, int] = {}
        interactions: set[str] = set()
        users: set[str] = set()
        for row in rows:
            event = EventEnvelope.model_validate_json(row["event_json"])
            interactions.add(event.interaction_id)
            users.add(event.user_id)
            event_types[event.event_type.value] = event_types.get(event.event_type.value, 0) + 1
            if event.event_type == EventType.POLICY_DECIDED:
                decision = str(event.payload.get("decision", "UNKNOWN"))
                decisions[decision] = decisions.get(decision, 0) + 1
        return {
            "tenant_id": tenant_id,
            "events": len(rows),
            "interactions": len(interactions),
            "active_users": len(users),
            "event_types": event_types,
            "decisions": decisions,
        }
