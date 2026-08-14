from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

try:
    from fastapi.testclient import TestClient

    from chatbot_studio.api.app import create_app

    API_AVAILABLE = True
except ModuleNotFoundError:
    API_AVAILABLE = False


@unittest.skipUnless(API_AVAILABLE, "FastAPI/httpx no están instalados en este runtime")
class ApiContractTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        app = create_app(Path(self.temp_directory.name) / "api.sqlite3")
        self.client = TestClient(app)

    def tearDown(self):
        self.temp_directory.cleanup()

    def test_health_and_first_event(self):
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["contract"], "chatbot-studio.event.v0.1")

        response = self.client.post(
            "/v1/events",
            json={
                "event_id": "evt_api_received_0001",
                "event_type": "INTERACTION_RECEIVED",
                "tenant_id": "tenant-api",
                "user_id": "user-api",
                "session_id": "session-api",
                "interaction_id": "interaction-api",
                "occurred_at": datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc).isoformat(),
                "actor": {"actor_type": "user", "actor_id": "user-api"},
                "payload": {"channel": "web"},
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["previous_hash"], "GENESIS")

    def test_tenant_scope_hides_foreign_event(self):
        response = self.client.get(
            "/v1/events/evt-does-not-exist", params={"tenant_id": "tenant-other"}
        )
        self.assertEqual(response.status_code, 404)
