"""KAN-104 — Casos de uso / pruebas de la sección Agenda del portal Faro Familia."""

from __future__ import annotations

import sys
from datetime import datetime
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
    main.repository.care_contacts.clear()
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


def test_portal_has_recurrence_fields() -> None:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert 'name="recurrence"' in html
    assert 'name="recurrence_interval"' in html
    assert 'name="recurrence_until"' in html
    assert 'name="recurrence_weekdays"' in html


def test_daily_recurrence_advances(client: TestClient) -> None:
    created = client.post("/v1/calendar-events", headers=HEADERS, json={
        "title": "Pastilla diaria", "category": "medication", "start_at": "2026-09-20T18:30:00+02:00",
        "reminder_minutes_before": 15, "recurrence": "daily", "recurrence_interval": 1,
    }).json()
    assert created["recurrence"] == "daily"
    first = client.post("/v1/calendar-tick", headers=HEADERS, params={"at": "2026-09-20T18:20:00+02:00"}).json()
    assert len(first["reminders"]) == 1
    listing = client.get("/v1/calendar-events", headers=HEADERS).json()
    assert listing[0]["start_at"].startswith("2026-09-21T18:30")
    second = client.post("/v1/calendar-tick", headers=HEADERS, params={"at": "2026-09-21T18:20:00+02:00"}).json()
    assert len(second["reminders"]) == 1


def test_recurrence_until_stops(client: TestClient) -> None:
    client.post("/v1/calendar-events", headers=HEADERS, json={
        "title": "Solo durante hoy", "start_at": "2026-09-20T18:30:00+02:00",
        "reminder_minutes_before": 15, "recurrence": "daily", "recurrence_until": "2026-09-20",
    })
    first = client.post("/v1/calendar-tick", headers=HEADERS, params={"at": "2026-09-20T18:20:00+02:00"}).json()
    assert len(first["reminders"]) == 1
    again = client.post("/v1/calendar-tick", headers=HEADERS, params={"at": "2026-09-21T18:20:00+02:00"}).json()
    assert again["reminders"] == []


def test_weekly_recurrence_with_weekdays(client: TestClient) -> None:
    client.post("/v1/calendar-events", headers=HEADERS, json={
        "title": "Fisio", "category": "appointment", "start_at": "2026-09-21T09:00:00+02:00",
        "reminder_minutes_before": 0, "recurrence": "weekly", "recurrence_weekdays": [0],
    })
    first = client.post("/v1/calendar-tick", headers=HEADERS, params={"at": "2026-09-21T09:00:00+02:00"}).json()
    assert len(first["reminders"]) == 1
    listing = client.get("/v1/calendar-events", headers=HEADERS).json()
    assert listing[0]["start_at"].startswith("2026-09-28T09:00")


def test_family_reminder_sends_whatsapp_but_patient_does_not(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client.post("/v1/care-contacts", headers=HEADERS, json={
        "display_name": "Hija", "phone_e164": "+34600111222", "whatsapp_consent": True,
        "priority": 1, "alerts_enabled": True,
    })
    calls: list = []

    def fake_send(contacts, alert, image=None):  # noqa: ANN001
        calls.append(alert)
        return [(contacts[0], main.AlertDelivery(message_id="wamid-test"))], []

    monkeypatch.setattr(main, "send_alert_to_contacts", fake_send)
    client.post("/v1/calendar-events", headers=HEADERS, json={
        "title": "Llamar a la cuidadora", "start_at": "2026-09-20T18:30:00+02:00",
        "reminder_minutes_before": 15, "for_patient": False,
    })
    client.post("/v1/calendar-events", headers=HEADERS, json={
        "title": "Pastilla del paciente", "start_at": "2026-09-20T18:30:00+02:00",
        "reminder_minutes_before": 15, "for_patient": True,
    })
    result = client.post("/v1/calendar-tick", headers=HEADERS, params={"at": "2026-09-20T18:20:00+02:00"}).json()
    assert len(result["reminders"]) == 2
    flags = {item["for_patient"] for item in result["reminders"]}
    assert flags == {True, False}
    assert len(calls) == 1
    assert calls[0].kind == "reminder"
    assert "Llamar a la cuidadora" in calls[0].spoken_message


def test_run_calendar_tick_and_optin_scheduler(client: TestClient) -> None:
    client.post("/v1/calendar-events", headers=HEADERS, json={
        "title": "Aviso paciente", "start_at": "2026-09-20T18:30:00+02:00", "reminder_minutes_before": 15,
    })
    result = main.run_calendar_tick(datetime.fromisoformat("2026-09-20T18:20:00+02:00"))
    assert len(result.reminders) == 1
    assert callable(main.start_tick_scheduler)
