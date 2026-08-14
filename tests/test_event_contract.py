from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from chatbot_studio.contracts import Actor, Decision, EventDraft, EventType
from chatbot_studio.projections import build_interaction_package
from chatbot_studio.recordia import verify_event
from chatbot_studio.recordia.trajectory import TrajectoryError
from chatbot_studio.stores import SQLiteEventStore


BASE = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


class EventContractTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "events.sqlite3"
        self.store = SQLiteEventStore(self.database_path)

    def tearDown(self):
        self.temp_directory.cleanup()

    def draft(self, event_type, second, payload=None, *, tenant="tenant-a", interaction="interaction-1"):
        return EventDraft(
            event_id=f"evt_{tenant}_{interaction}_{event_type.value.lower()}",
            event_type=event_type,
            tenant_id=tenant,
            user_id="user-1",
            session_id="session-1",
            interaction_id=interaction,
            occurred_at=BASE + timedelta(seconds=second),
            actor=Actor(actor_type="service", actor_id="chatbot-studio"),
            payload=payload or {},
        )

    def start_through_policy(self, decision, *, tenant="tenant-a", interaction="interaction-1"):
        events = [
            self.store.append(self.draft(EventType.INTERACTION_RECEIVED, 0, tenant=tenant, interaction=interaction)),
            self.store.append(self.draft(EventType.IDENTITY_VERIFIED, 1, {"state": "NORMAL"}, tenant=tenant, interaction=interaction)),
            self.store.append(self.draft(EventType.CONTENT_INSPECTED, 2, {"risk": 14}, tenant=tenant, interaction=interaction)),
            self.store.append(self.draft(EventType.POLICY_DECIDED, 3, {"decision": decision.value}, tenant=tenant, interaction=interaction)),
        ]
        return events

    def test_allow_flow_is_chained_and_reconstructable(self):
        events = self.start_through_policy(Decision.ALLOW)
        events.append(self.store.append(self.draft(EventType.PROVIDER_REQUESTED, 4, {"provider": "OpenAI"})))
        events.append(self.store.append(self.draft(EventType.PROVIDER_RESPONDED, 5, {"status": "complete"})))
        events.append(self.store.append(self.draft(EventType.INTERACTION_RECORDED, 6, {"outcome": "completed"})))

        report = self.store.verify_tenant_chain("tenant-a")
        package = build_interaction_package(events)

        self.assertTrue(report.valid, report.errors)
        self.assertEqual(events[0].previous_hash, "GENESIS")
        self.assertEqual(events[1].previous_hash, events[0].record_hash)
        self.assertEqual(package["timeline"]["decided_at"], events[3].occurred_at.isoformat().replace("+00:00", "Z"))
        self.assertEqual(package["recordia"]["last_record_hash"], events[-1].record_hash)

    def test_tokenize_requires_awareness_and_never_loses_timestamps(self):
        events = self.start_through_policy(Decision.TOKENIZE)
        events.append(self.store.append(self.draft(EventType.AWARENESS_PRESENTED, 4, {"finding": "PII.EMAIL"})))
        events.append(self.store.append(self.draft(EventType.USER_ACKNOWLEDGED, 5, {"acknowledged": True})))
        events.append(self.store.append(self.draft(EventType.PROVIDER_REQUESTED, 6, {"prompt": "[TOKEN:EMAIL]"})))
        events.append(self.store.append(self.draft(EventType.PROVIDER_RESPONDED, 7, {"status": "complete"})))
        events.append(self.store.append(self.draft(EventType.INTERACTION_RECORDED, 8, {"outcome": "completed"})))

        package = build_interaction_package(events)
        self.assertIsNotNone(package["timeline"]["inspected_at"])
        self.assertIsNotNone(package["timeline"]["awareness_presented_at"])
        self.assertIsNotNone(package["timeline"]["user_acknowledged_at"])
        self.assertIsNotNone(package["timeline"]["sent_to_provider_at"])
        self.assertTrue(self.store.verify_tenant_chain("tenant-a").valid)

    def test_block_cannot_reach_provider_and_vault_is_separate_event(self):
        events = self.start_through_policy(Decision.BLOCK)
        events.append(self.store.append(self.draft(EventType.AWARENESS_PRESENTED, 4, {"finding": "SECRET.CREDENTIAL"})))
        events.append(self.store.append(self.draft(EventType.USER_ACKNOWLEDGED, 5, {"acknowledged": True})))

        with self.assertRaises(TrajectoryError):
            self.store.append(self.draft(EventType.PROVIDER_REQUESTED, 6, {"provider": "OpenAI"}))

        recorded = self.store.append(self.draft(EventType.INTERACTION_RECORDED, 6, {"outcome": "blocked"}))
        vaulted = self.store.append(
            self.draft(
                EventType.EVIDENCE_VAULTED,
                7,
                {
                    "parent_event_id": recorded.event_id,
                    "parent_record_hash": recorded.record_hash,
                    "vault_reference": "hotvault://tenant-a/evidence-1",
                },
            )
        )
        package = build_interaction_package(self.store.list_interaction("tenant-a", "interaction-1"))

        self.assertEqual(vaulted.previous_hash, recorded.record_hash)
        self.assertEqual(package["hotvault"]["parent_record_hash"], recorded.record_hash)
        self.assertIsNone(package["timeline"]["sent_to_provider_at"])
        self.assertTrue(self.store.verify_tenant_chain("tenant-a").valid)

    def test_review_requires_human_approval_before_provider(self):
        self.start_through_policy(Decision.REVIEW)
        self.store.append(self.draft(EventType.AWARENESS_PRESENTED, 4, {"finding": "DATA.CONFIDENTIAL"}))
        with self.assertRaises(TrajectoryError):
            self.store.append(self.draft(EventType.PROVIDER_REQUESTED, 5, {"provider": "OpenAI"}))
        self.store.append(self.draft(EventType.REVIEW_APPROVED, 5, {"approver_id": "manager-1"}))
        requested = self.store.append(self.draft(EventType.PROVIDER_REQUESTED, 6, {"provider": "OpenAI"}))
        self.assertEqual(requested.event_type, EventType.PROVIDER_REQUESTED)

    def test_timestamp_tampering_breaks_record_hash(self):
        event = self.store.append(self.draft(EventType.INTERACTION_RECEIVED, 0))
        tampered = event.model_copy(update={"occurred_at": event.occurred_at + timedelta(milliseconds=1)})
        report = verify_event(tampered)
        self.assertFalse(report.valid)
        self.assertTrue(any("record_hash inválido" in error for error in report.errors))

    def test_sqlite_store_rejects_update_and_delete(self):
        event = self.store.append(self.draft(EventType.INTERACTION_RECEIVED, 0))
        with sqlite3.connect(self.database_path) as connection:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                connection.execute(
                    "UPDATE governance_events SET occurred_at = ? WHERE event_id = ?",
                    ("2030-01-01T00:00:00Z", event.event_id),
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                connection.execute("DELETE FROM governance_events WHERE event_id = ?", (event.event_id,))

    def test_cross_tenant_parent_reference_is_rejected(self):
        parent = self.store.append(self.draft(EventType.INTERACTION_RECEIVED, 0, tenant="tenant-a"))
        with self.assertRaisesRegex(ValueError, "Referencia entre tenants"):
            self.store.append(
                self.draft(
                    EventType.EVIDENCE_VAULTED,
                    1,
                    {"parent_event_id": parent.event_id, "parent_record_hash": parent.record_hash},
                    tenant="tenant-b",
                    interaction="interaction-b",
                )
            )

    def test_cross_interaction_parent_reference_is_rejected(self):
        self.start_through_policy(Decision.BLOCK, interaction="interaction-parent")
        self.store.append(
            self.draft(
                EventType.AWARENESS_PRESENTED,
                4,
                {"finding": "SECRET.CREDENTIAL"},
                interaction="interaction-parent",
            )
        )
        recorded = self.store.append(
            self.draft(
                EventType.INTERACTION_RECORDED,
                5,
                {"outcome": "blocked"},
                interaction="interaction-parent",
            )
        )
        with self.assertRaisesRegex(ValueError, "Referencia entre interacciones"):
            self.store.append(
                self.draft(
                    EventType.EVIDENCE_VAULTED,
                    6,
                    {"parent_event_id": recorded.event_id, "parent_record_hash": recorded.record_hash},
                    interaction="interaction-other",
                )
            )

    def test_duplicate_event_id_is_rejected(self):
        draft = self.draft(EventType.INTERACTION_RECEIVED, 0)
        self.store.append(draft)
        with self.assertRaisesRegex(ValueError, "event_id ya existe"):
            self.store.append(draft)

    def test_user_and_tenant_metrics_are_isolated(self):
        self.start_through_policy(Decision.ALLOW)
        usage = self.store.user_usage("tenant-a", "user-1")
        other_usage = self.store.user_usage("tenant-b", "user-1")
        metrics = self.store.tenant_metrics("tenant-a")
        self.assertEqual(usage["interactions"], 1)
        self.assertEqual(usage["decisions"], {"ALLOW": 1})
        self.assertEqual(other_usage["events"], 0)
        self.assertEqual(metrics["active_users"], 1)


if __name__ == "__main__":
    unittest.main()
