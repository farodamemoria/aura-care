"""KAN-205 - Faro no puede obtener la ubicacion del paciente.

Cubre las causas reales encontradas en produccion:

* un fix valido pero con mas de 5 minutos devolvia `refresh_required` (callejon sin salida:
  nadie reintenta y Faro acaba diciendo que no puede);
* la ultima ubicacion vivia solo en memoria y se perdia en cada reinicio/despliegue;
* el pipeline no tenia forma de consultar la ultima posicion persistida;
* `/v1/pairing/claim` quedo detras de la contrasena maestra (KAN-203) y un movil nuevo no
  puede emparejarse, por lo que tampoco puede enviar ubicacion.
"""

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

TOKEN = "kan205-token-5f3c9a7e1b6d8042c4e8a9f0d2b7c6"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
HOME_LAT = 42.6609203
HOME_LON = -8.5689992
AWAY_LAT = 42.2406
AWAY_LON = -8.7207


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("AURA_REVIEW_MEDIA_DIR", str(tmp_path / "review-images"))
    monkeypatch.setenv("AURA_REVIEW_SECRET", "test-review-secret")
    monkeypatch.setattr(main, "reverse_geocode", lambda latitude, longitude: None)
    main.repository = main.InMemoryRepository()
    main._LAST_DEVICE_LOCATION.clear()
    yield TestClient(main.app)
    main.repository.clear_last_device_location()
    main._LAST_DEVICE_LOCATION.clear()
    monkeypatch.delenv("AURA_EVENT_DB", raising=False)
    monkeypatch.delenv("AURA_DATA_FILE", raising=False)
    main.repository = main.InMemoryRepository()


def _seed_home(client: TestClient) -> None:
    response = client.put("/v1/patient-profile", headers=HEADERS, json={
        "preferred_name": "Leonardo",
        "home_address": {
            "street_address": "Soutelo, 21", "postal_code": "36679", "locality": "Cuntis",
            "province": "Pontevedra", "latitude": HOME_LAT, "longitude": HOME_LON,
        },
    })
    assert response.status_code == 200, response.text


def _iso(moment) -> str:
    return moment.isoformat()


def test_fresh_fix_is_answered_and_persisted(client: TestClient) -> None:
    _seed_home(client)
    response = client.post("/v1/location/answer", headers=HEADERS, json={
        "latitude": HOME_LAT, "longitude": HOME_LON, "accuracy_meters": 8,
        "recorded_at": _iso(main.now()),
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "at_home"
    assert body["location_source"] == "gps"
    assert body["age_seconds"] is not None and body["age_seconds"] < 60

    last = client.get("/v1/location/last", headers=HEADERS)
    assert last.status_code == 200, last.text
    stored = last.json()
    assert stored["available"] is True
    assert stored["latitude"] == pytest.approx(HOME_LAT)
    assert stored["longitude"] == pytest.approx(HOME_LON)


def test_ten_minute_fix_answers_with_last_known_instead_of_refresh_required(client: TestClient) -> None:
    _seed_home(client)
    recorded = main.now() - timedelta(minutes=10)
    response = client.post("/v1/location/answer", headers=HEADERS, json={
        "latitude": HOME_LAT, "longitude": HOME_LON, "accuracy_meters": 8,
        "recorded_at": _iso(recorded),
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] != "refresh_required"
    assert body["status"] == "last_known"
    assert "hace 10 minutos" in body["message"]
    assert "casa" in body["message"]


def test_old_fix_uses_persisted_newer_position(client: TestClient) -> None:
    _seed_home(client)
    fresh = client.post("/v1/location/answer", headers=HEADERS, json={
        "latitude": AWAY_LAT, "longitude": AWAY_LON, "accuracy_meters": 10,
        "recorded_at": _iso(main.now()),
    })
    assert fresh.status_code == 200, fresh.text

    old = client.post("/v1/location/answer", headers=HEADERS, json={
        "latitude": HOME_LAT, "longitude": HOME_LON, "accuracy_meters": 10,
        "recorded_at": _iso(main.now() - timedelta(minutes=30)),
    })
    assert old.status_code == 200, old.text
    body = old.json()
    assert body["status"] == "last_known"
    assert "Según tu última ubicación" in body["message"]

    stored = client.get("/v1/location/last", headers=HEADERS).json()
    assert stored["latitude"] == pytest.approx(AWAY_LAT)
    assert stored["longitude"] == pytest.approx(AWAY_LON)


def test_stale_fix_without_any_stored_position_is_honest(client: TestClient) -> None:
    _seed_home(client)
    response = client.post("/v1/location/answer", headers=HEADERS, json={
        "latitude": AWAY_LAT, "longitude": AWAY_LON, "accuracy_meters": 8,
        "recorded_at": _iso(main.now() - timedelta(minutes=40)),
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "last_known_stale"
    assert "No consigo una ubicación reciente" in body["message"]
    assert "hace 40 minutos" in body["message"]
    assert client.get("/v1/location/last", headers=HEADERS).json()["available"] is False


def test_last_position_survives_a_repository_restart(client: TestClient) -> None:
    _seed_home(client)
    located = client.post("/v1/location/answer", headers=HEADERS, json={
        "latitude": HOME_LAT, "longitude": HOME_LON, "accuracy_meters": 6,
        "recorded_at": _iso(main.now()),
    })
    assert located.status_code == 200, located.text

    main._LAST_DEVICE_LOCATION.clear()
    main.repository = main.InMemoryRepository()
    restarted = client.get("/v1/location/last", headers=HEADERS)
    assert restarted.status_code == 200, restarted.text
    body = restarted.json()
    assert body["available"] is True
    assert body["latitude"] == pytest.approx(HOME_LAT)
    assert body["recorded_at"] is not None


def test_alerts_use_persisted_position_after_restart(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_home(client)
    contact = client.post("/v1/care-contacts", headers=HEADERS, json={
        "display_name": "Bibiana", "phone_e164": "+34644610954",
        "whatsapp_consent": True, "priority": 1, "alerts_enabled": True,
    })
    assert contact.status_code == 201, contact.text
    sent: list = []

    def fake_send(contacts, alert, image=None):  # noqa: ANN001
        sent.append(alert)
        return [(contacts[0], main.AlertDelivery(message_id="wamid-kan205"))], []

    monkeypatch.setattr(main, "send_alert_to_contacts", fake_send)
    located = client.post("/v1/location/answer", headers=HEADERS, json={
        "latitude": AWAY_LAT, "longitude": AWAY_LON, "accuracy_meters": 9,
        "recorded_at": _iso(main.now()),
    })
    assert located.status_code == 200, located.text

    main._LAST_DEVICE_LOCATION.clear()
    main.repository = main.InMemoryRepository()
    response = client.post("/v1/emergency-alerts", headers=HEADERS, json={
        "kind": "episode", "spoken_message": "Ayuda", "explicit_help_request": True,
    })
    assert response.status_code == 201, response.text
    assert response.json()["latitude"] == pytest.approx(AWAY_LAT)
    assert response.json()["location_source"] == "gps"
    assert sent and sent[0].latitude == pytest.approx(AWAY_LAT)


def test_old_gps_alert_is_marked_as_last_known(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_home(client)
    contact = client.post("/v1/care-contacts", headers=HEADERS, json={
        "display_name": "Bibiana", "phone_e164": "+34644610954",
        "whatsapp_consent": True, "priority": 1, "alerts_enabled": True,
    })
    assert contact.status_code == 201, contact.text
    monkeypatch.setattr(main, "send_alert_to_contacts", lambda contacts, alert, image=None: (
        [(contacts[0], main.AlertDelivery(message_id="wamid-kan205-old"))], []
    ))
    located = client.post("/v1/location/answer", headers=HEADERS, json={
        "latitude": AWAY_LAT, "longitude": AWAY_LON, "accuracy_meters": 9,
        "recorded_at": _iso(main.now() - timedelta(minutes=8)),
    })
    assert located.status_code == 200, located.text

    response = client.post("/v1/emergency-alerts", headers=HEADERS, json={
        "kind": "episode", "spoken_message": "Ayuda", "explicit_help_request": True,
    })
    assert response.status_code == 201, response.text
    assert response.json()["latitude"] == pytest.approx(AWAY_LAT)
    assert response.json()["location_source"] == "last_known"


def test_pairing_claim_is_public_for_new_phones() -> None:
    assert main.is_public_portal_path("/v1/pairing/claim") is True
    assert main.is_public_portal_path("/v1/people") is False


def test_invalid_location_payload_is_rejected(client: TestClient) -> None:
    response = client.post("/v1/location/answer", headers=HEADERS, json={
        "latitude": 120, "longitude": 0, "accuracy_meters": 8,
    })
    assert response.status_code == 422
