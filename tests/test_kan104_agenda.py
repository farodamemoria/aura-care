"""KAN-104 — Casos de uso / pruebas de la sección Agenda del portal Faro Familia."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "integration-agenda-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
INICIO = "2026-09-20T18:30:00+02:00"
NUEVA = "2026-09-21T09:00:00+02:00"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    main.repository.calendar_events.clear()
    return TestClient(main.app)


def test_portal_has_agenda_section() -> None:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert 'data-view="agenda-view"' in html
    assert 'id="agenda-form"' in html
    assert 'id="agenda-events"' in html
    assert "/assets/agenda.css" in html


def test_portal_script_uses_calendar_endpoints() -> None:
    script = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    assert "/v1/calendar-events" in script
    assert "renderAgenda" in script
    sw = (ROOT / "web" / "assets" / "sw.js").read_text(encoding="utf-8")
    assert "/assets/agenda.css" in sw


def test_create_and_list_event(client: TestClient) -> None:
    created = client.post("/v1/calendar-events", headers=HEADERS, json={
        "title": "Pastilla de la tensión", "category": "medication",
        "start_at": INICIO, "reminder_minutes_before": 10,
    })
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["title"] == "Pastilla de la tensión"
    assert body["category"] == "medication"
    listing = client.get("/v1/calendar-events", headers=HEADERS).json()
    assert [event["id"] for event in listing] == [body["id"]]


def test_event_categories_are_validated(client: TestClient) -> None:
    ok = client.post("/v1/calendar-events", headers=HEADERS, json={
        "title": "Rutina", "category": "routine", "start_at": INICIO,
    })
    assert ok.status_code == 201
    bad = client.post("/v1/calendar-events", headers=HEADERS, json={
        "title": "Rutina", "category": "inventada", "start_at": INICIO,
    })
    assert bad.status_code == 422


def test_edit_time_and_disable(client: TestClient) -> None:
    event = client.post("/v1/calendar-events", headers=HEADERS, json={
        "title": "Visita al médico", "category": "appointment", "start_at": INICIO,
    }).json()
    edited = client.patch(
        f"/v1/calendar-events/{event['id']}", headers=HEADERS, json={"start_at": NUEVA},
    ).json()
    assert edited["start_at"].startswith("2026-09-21T09:00")
    paused = client.patch(
        f"/v1/calendar-events/{event['id']}", headers=HEADERS, json={"enabled": False},
    ).json()
    assert paused["enabled"] is False
    assert client.get("/v1/calendar-events", headers=HEADERS).json() == []


def test_delete_event(client: TestClient) -> None:
    event = client.post("/v1/calendar-events", headers=HEADERS, json={
        "title": "Rutina de la mañana", "start_at": INICIO,
    }).json()
    assert client.delete(f"/v1/calendar-events/{event['id']}", headers=HEADERS).status_code == 204
    assert client.get("/v1/calendar-events", headers=HEADERS).json() == []


def test_agenda_requires_authentication(client: TestClient) -> None:
    assert client.get("/v1/calendar-events").status_code == 401
    assert client.post("/v1/calendar-events", json={"title": "x", "start_at": INICIO}).status_code == 401
