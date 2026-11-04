"""KAN-204 - el aviso por desorientacion sale con ubicacion aunque el movil no mande GPS."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402
from app.environmental_listening import is_lost_request  # noqa: E402

TOKEN = "kan204-token-5f3c9a7e1b6d8042c4e8a9f0d2b7c6"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
HOME_LAT = 42.6609203
HOME_LON = -8.5689992


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("AURA_REVIEW_MEDIA_DIR", str(tmp_path / "review-images"))
    monkeypatch.setenv("AURA_REVIEW_SECRET", "test-review-secret")
    main.repository = main.InMemoryRepository()
    main._LAST_DEVICE_LOCATION.clear()
    yield TestClient(main.app)
    monkeypatch.delenv("AURA_EVENT_DB", raising=False)
    monkeypatch.delenv("AURA_DATA_FILE", raising=False)
    main.repository = main.InMemoryRepository()
    main._LAST_DEVICE_LOCATION.clear()


def _seed_home(client: TestClient) -> None:
    response = client.put("/v1/patient-profile", headers=HEADERS, json={
        "preferred_name": "Leonardo",
        "home_address": {
            "street_address": "Soutelo, 21",
            "postal_code": "36679",
            "locality": "Cuntis",
            "province": "Pontevedra",
            "latitude": HOME_LAT,
            "longitude": HOME_LON,
        },
    })
    assert response.status_code == 200, response.text


def _seed_contacts(client: TestClient) -> None:
    for name, phone, priority in (
        ("Javier Ortega (prueba)", "+34645395448", 1),
        ("Bibiana", "+34644610954", 2),
    ):
        response = client.post("/v1/care-contacts", headers=HEADERS, json={
            "display_name": name, "phone_e164": phone, "role": "family",
            "whatsapp_consent": True, "priority": priority, "alerts_enabled": True,
        })
        assert response.status_code == 201, response.text


def _capture_send(monkeypatch: pytest.MonkeyPatch) -> list:
    sent: list = []

    def fake_send(contacts, alert, image=None):  # noqa: ANN001
        sent.append((list(contacts), alert))
        return [(contacts[0], main.AlertDelivery(message_id="wamid-kan204"))], []

    monkeypatch.setattr(main, "send_alert_to_contacts", fake_send)
    return sent


def test_lost_alert_includes_home_when_no_gps(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_home(client)
    _seed_contacts(client)
    sent = _capture_send(monkeypatch)

    response = client.post("/v1/emergency-alerts", headers=HEADERS, json={
        "kind": "lost", "spoken_message": "El paciente dice: \u00abEstoy perdido\u00bb",
        "explicit_help_request": True,
    })
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "lost"
    assert body["latitude"] == pytest.approx(HOME_LAT)
    assert body["longitude"] == pytest.approx(HOME_LON)
    assert body["location_source"] == "last_known"
    assert sent and sent[0][1].latitude == pytest.approx(HOME_LAT)
    assert "maps.google.com" in main.build_alert_message(sent[0][1])
    phones = {contact.phone_e164 for contact in sent[0][0]}
    assert "+34645395448" in phones

    events = client.get("/v1/events?limit=10", headers=HEADERS).json()
    matching = [event for event in events if (event.get("metadata") or {}).get("alert_id") == body["id"]]
    assert matching, "the alert must be recorded in the event log"
    metadata = matching[0]["metadata"]
    assert metadata["location_included"] is True
    assert metadata["location_source"] == "last_known"
    assert matching[0]["latitude"] == pytest.approx(HOME_LAT)


def test_recent_gps_wins_over_home(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_home(client)
    _seed_contacts(client)
    _capture_send(monkeypatch)
    located = client.post("/v1/location/answer", headers=HEADERS, json={
        "latitude": 42.2406, "longitude": -8.7207, "accuracy_meters": 18,
    })
    assert located.status_code == 200, located.text

    response = client.post("/v1/emergency-alerts", headers=HEADERS, json={
        "kind": "lost", "spoken_message": "Estoy perdido", "explicit_help_request": True,
    })
    assert response.status_code == 201, response.text
    assert response.json()["latitude"] == 42.2406
    assert response.json()["location_source"] == "gps"


def test_lost_phrases_are_detected() -> None:
    for phrase in (
        "Estoy perdido", "Estoy perdida", "Me he perdido", "No sé dónde estoy",
        "No sé dónde me encuentro", "Estoy desorientado", "Non sei onde estou",
        "No encuentro el camino", "No sé volver a casa",
    ):
        assert is_lost_request(phrase), phrase
    assert not is_lost_request("He perdido las llaves")
    assert not is_lost_request("Voy a hacer la comida")
