"""KAN-41 — Casos de uso: precisión y actualización progresiva de la ubicación en alertas."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "integration-kan41-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    main.repository.location_sessions.clear()
    main.repository.care_contacts.clear()
    main.repository.emergency_alerts.clear()
    main.repository.last_emergency_at.clear()
    return TestClient(main.app)


def open_session(client: TestClient) -> dict:
    response = client.post("/v1/location-sessions", headers=HEADERS, json={"explicit_help_request": True})
    assert response.status_code == 201, response.text
    return response.json()


def test_session_keeps_better_accuracy(client: TestClient) -> None:
    session = open_session(client)
    start = datetime.now(timezone.utc)
    first = client.put(f"/v1/location-sessions/{session['id']}/location", headers=HEADERS, json={
        "latitude": 42.25, "longitude": -8.71, "accuracy_meters": 20, "source": "gps",
        "recorded_at": start.isoformat(),
    })
    assert first.status_code == 200, first.text
    assert first.json()["last_location"]["accuracy_meters"] == 20
    worse = client.put(f"/v1/location-sessions/{session['id']}/location", headers=HEADERS, json={
        "latitude": 42.26, "longitude": -8.72, "accuracy_meters": 300, "source": "network",
        "recorded_at": (start + timedelta(seconds=20)).isoformat(),
    })
    assert worse.status_code == 200, worse.text
    assert worse.json()["last_location"]["accuracy_meters"] == 20


def test_fresher_reading_replaces_even_if_less_accurate(client: TestClient) -> None:
    session = open_session(client)
    start = datetime.now(timezone.utc)
    client.put(f"/v1/location-sessions/{session['id']}/location", headers=HEADERS, json={
        "latitude": 42.25, "longitude": -8.71, "accuracy_meters": 20, "source": "gps",
        "recorded_at": start.isoformat(),
    })
    fresher = client.put(f"/v1/location-sessions/{session['id']}/location", headers=HEADERS, json={
        "latitude": 42.30, "longitude": -8.75, "accuracy_meters": 300, "source": "network",
        "recorded_at": (start + timedelta(minutes=5)).isoformat(),
    })
    assert fresher.json()["last_location"]["accuracy_meters"] == 300


def test_share_payload_exposes_source_accuracy_and_time(client: TestClient) -> None:
    session = open_session(client)
    recorded = datetime.now(timezone.utc)
    client.put(f"/v1/location-sessions/{session['id']}/location", headers=HEADERS, json={
        "latitude": 42.25, "longitude": -8.71, "accuracy_meters": 18, "source": "gps",
        "recorded_at": recorded.isoformat(),
    })
    shared = client.get(f"/v1/location-share/{session['share_token']}")
    assert shared.status_code == 200, shared.text
    point = shared.json()["last_location"]
    assert point["source"] == "gps"
    assert point["accuracy_meters"] == 18
    assert point["recorded_at"].startswith(recorded.strftime("%Y-%m-%dT%H:%M"))
    page = client.get(f"/track/{session['share_token']}")
    assert page.status_code == 200, page.text
    assert "APPROX=50" in page.text
    assert "Última posición conocida" in page.text


def test_approximate_location_is_labelled_in_alert_message() -> None:
    approximate = main.EmergencyAlertCreate(
        kind="episode", spoken_message="Necesito ayuda", explicit_help_request=True,
        latitude=42.25, longitude=-8.71, location_accuracy_meters=120, location_source="network",
    )
    message = main.build_alert_message(approximate)
    assert "precisión aproximada" in message
    assert "network" in message
    precise = main.EmergencyAlertCreate(
        kind="episode", spoken_message="Necesito ayuda", explicit_help_request=True,
        latitude=42.25, longitude=-8.71, location_accuracy_meters=15, location_source="gps",
    )
    precise_message = main.build_alert_message(precise)
    assert "aproximada" not in precise_message
    assert "precisión: ±15 m, gps" in precise_message


def test_stale_location_is_presented_as_last_known() -> None:
    stale = main.EmergencyAlertCreate(
        kind="lost", spoken_message="No encuentro a mamá", explicit_help_request=True,
        latitude=42.25, longitude=-8.71, location_accuracy_meters=10, location_source="gps",
        location_recorded_at=main.now() - timedelta(minutes=15),
    )
    message = main.build_alert_message(stale)
    assert "última posición conocida" in message
    assert "hace 15 min" in message


def test_alert_without_any_location_never_blocks() -> None:
    alert = main.EmergencyAlertCreate(
        kind="episode", spoken_message="Me caí", explicit_help_request=True,
    )
    message = main.build_alert_message(alert)
    assert "mapa" not in message
    assert "Me caí" in message


def test_emergency_alert_event_keeps_location_audit_fields(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    contact = client.post("/v1/care-contacts", headers=HEADERS, json={
        "display_name": "Hija", "phone_e164": "+34600111222", "whatsapp_consent": True,
        "priority": 1, "alerts_enabled": True,
    })
    assert contact.status_code == 201, contact.text
    sent: list = []

    def fake_send(contacts, alert, image=None):  # noqa: ANN001
        sent.append(alert)
        return [(contacts[0], main.AlertDelivery(message_id="wamid-kan41"))], []

    monkeypatch.setattr(main, "send_alert_to_contacts", fake_send)
    recorded = main.now()
    response = client.post("/v1/emergency-alerts", headers=HEADERS, json={
        "kind": "episode", "spoken_message": "Caída en el baño", "explicit_help_request": True,
        "latitude": 42.25, "longitude": -8.71, "location_accuracy_meters": 120,
        "location_source": "network", "location_recorded_at": recorded.isoformat(),
    })
    assert response.status_code == 201, response.text
    assert sent and "precisión aproximada" in main.build_alert_message(sent[0])
    events = client.get("/v1/events", headers=HEADERS, params={"kind": "help_request"}).json()
    audit = [event for event in events if "location_accuracy_meters" in event["metadata"]]
    assert audit, "el evento de alerta debe conservar la precisión y la fuente"
    metadata = audit[0]["metadata"]
    assert metadata["location_accuracy_meters"] == 120
    assert metadata["location_source"] == "network"
    assert metadata["location_approximate"] is True
    assert metadata["location_recorded_at"].startswith(recorded.strftime("%Y-%m-%dT%H:%M"))
