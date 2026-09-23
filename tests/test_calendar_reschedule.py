"""Al reprogramar un recordatorio debe poder volver a dispararse (reseteo de reminded_at)."""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "calendar-reschedule-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    main.repository = main.InMemoryRepository()
    return TestClient(main.app)


def test_reschedule_resets_reminded_at(client: TestClient) -> None:
    created = client.post(
        "/v1/calendar-events", headers=HEADERS,
        json={"title": "Pastilla", "category": "medication", "start_at": main.now().isoformat()},
    ).json()
    event_id = main.UUID(created["id"])
    event = main.repository.calendar_events[event_id]
    main.repository.calendar_events[event_id] = event.model_copy(update={"reminded_at": main.now()})

    new_start = (main.now() + timedelta(hours=2)).isoformat()
    patched = client.patch(
        f"/v1/calendar-events/{created['id']}", headers=HEADERS, json={"start_at": new_start}
    ).json()
    assert patched["reminded_at"] is None
