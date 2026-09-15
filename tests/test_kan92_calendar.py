"""KAN-92 — Casos de uso / pruebas del calendario con recordatorios."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "integration-calendar-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
INICIO = "2026-09-16T10:00:00+02:00"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_CREDENTIAL_PEPPER", "test-pepper")
    main.repository.calendar_events.clear()
    return TestClient(main.app)


def create_event(
    client: TestClient, title: str = "Visita del médico", category: str = "appointment",
) -> dict:
    response = client.post("/v1/calendar-events", headers=HEADERS, json={
        "title": title, "category": category, "start_at": INICIO, "reminder_minutes_before": 15,
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_endpoints_require_authentication(client: TestClient) -> None:
    assert client.post("/v1/calendar-events", json={"title": "x", "start_at": INICIO}).status_code == 401
    assert client.get("/v1/calendar-events").status_code == 401
    assert client.post("/v1/calendar-tick").status_code == 401


def test_crud(client: TestClient) -> None:
    event = create_event(client)
    assert client.get("/v1/calendar-events", headers=HEADERS).json()[0]["id"] == event["id"]
    patched = client.patch(
        f"/v1/calendar-events/{event['id']}", headers=HEADERS, json={"enabled": False},
    ).json()
    assert patched["enabled"] is False
    assert client.delete(f"/v1/calendar-events/{event['id']}", headers=HEADERS).status_code == 204
    assert client.get("/v1/calendar-events", headers=HEADERS).json() == []


def test_validation_rejects_invalid_events(client: TestClient) -> None:
    assert client.post(
        "/v1/calendar-events", headers=HEADERS, json={"title": "", "start_at": INICIO},
    ).status_code == 422
    assert client.post(
        "/v1/calendar-events", headers=HEADERS,
        json={"title": "x", "start_at": INICIO, "category": "otra"},
    ).status_code == 422


def test_reminder_is_created_once(client: TestClient) -> None:
    create_event(client)
    antes = client.post(
        "/v1/calendar-tick", headers=HEADERS, params={"at": "2026-09-16T09:30:00+02:00"},
    ).json()
    assert antes["reminders"] == []
    en_punto = client.post(
        "/v1/calendar-tick", headers=HEADERS, params={"at": "2026-09-16T09:45:00+02:00"},
    ).json()
    assert len(en_punto["reminders"]) == 1
    assert "Visita del médico" in en_punto["reminders"][0]["message"]
    otra_vez = client.post(
        "/v1/calendar-tick", headers=HEADERS, params={"at": "2026-09-16T09:50:00+02:00"},
    ).json()
    assert otra_vez["reminders"] == []
    events = client.get("/v1/events", headers=HEADERS, params={"kind": "routine"}).json()
    assert any("Recordatorio de agenda" in event["summary"] for event in events)


def test_disabled_event_does_not_remind(client: TestClient) -> None:
    event = create_event(client)
    client.patch(f"/v1/calendar-events/{event['id']}", headers=HEADERS, json={"enabled": False})
    resultado = client.post(
        "/v1/calendar-tick", headers=HEADERS, params={"at": "2026-09-16T09:45:00+02:00"},
    ).json()
    assert resultado["reminders"] == []


def test_unknown_event_is_rejected(client: TestClient) -> None:
    unknown = "00000000-0000-4000-8000-000000000000"
    assert client.patch(
        f"/v1/calendar-events/{unknown}", headers=HEADERS, json={"enabled": False},
    ).status_code == 404
