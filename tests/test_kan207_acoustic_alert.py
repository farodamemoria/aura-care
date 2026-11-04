"""KAN-207 - la alerta por tos sale con tipologia, descripcion y ubicacion.

Regresion real: un aviso acustico escalado por el motor de escucha se enviaba
directamente a los contactos sin pasar por `/v1/emergency-alerts`, por lo que
salia con `kind=hazard` generico, sin la descripcion del evento y con
`latitude/longitude = null`. Estas pruebas cubren el flujo completo
(`/v1/acoustic-audio` -> motor -> escalado -> WhatsApp) con un WAV real.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402
from app.environmental_listening import (  # noqa: E402
    EnvironmentalListeningEngine,
    ListeningConfig,
)

TOKEN = "kan207-token-3f7c9a1e5b8d2046c4a9e7f0b2d6c8"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "audio/wav"}
JSON_HEADERS = {"Authorization": f"Bearer {TOKEN}"}
AUDIO_DIR = Path(__file__).resolve().parent / "fixtures" / "audio"
HOME_LAT = 42.6609203
HOME_LON = -8.5689992


@pytest.fixture(scope="session")
def fixtures(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    spec = importlib.util.spec_from_file_location("kan207_fixtures_http", AUDIO_DIR / "generate_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.build_fixtures(tmp_path_factory.mktemp("kan207-http"))


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("AURA_REVIEW_MEDIA_DIR", str(tmp_path / "review-images"))
    monkeypatch.setenv("AURA_REVIEW_SECRET", "test-review-secret")
    main.repository = main.InMemoryRepository()
    main.repository.clear_last_device_location()
    main._LAST_DEVICE_LOCATION.clear()
    main.acoustic_listening = EnvironmentalListeningEngine(ListeningConfig())
    yield TestClient(main.app)
    monkeypatch.delenv("AURA_EVENT_DB", raising=False)
    monkeypatch.delenv("AURA_DATA_FILE", raising=False)
    main.repository = main.InMemoryRepository()
    main._LAST_DEVICE_LOCATION.clear()
    main.acoustic_listening = EnvironmentalListeningEngine(ListeningConfig())


def _seed_home(client: TestClient) -> None:
    response = client.put("/v1/patient-profile", headers=JSON_HEADERS, json={
        "preferred_name": "Leonardo",
        "home_address": {
            "street_address": "Soutelo, 21", "postal_code": "36679", "locality": "Cuntis",
            "province": "Pontevedra", "latitude": HOME_LAT, "longitude": HOME_LON,
        },
    })
    assert response.status_code == 200, response.text


def _seed_contacts(client: TestClient) -> None:
    for name, phone, priority in (
        ("Javier Ortega (prueba)", "+34645395448", 1),
        ("Bibiana", "+34644610954", 2),
    ):
        response = client.post("/v1/care-contacts", headers=JSON_HEADERS, json={
            "display_name": name, "phone_e164": phone, "role": "family",
            "whatsapp_consent": True, "priority": priority, "alerts_enabled": True,
        })
        assert response.status_code == 201, response.text


def _capture_send(monkeypatch: pytest.MonkeyPatch) -> list:
    sent: list = []

    def fake_send(contacts, alert, image=None):  # noqa: ANN001
        sent.append((list(contacts), alert))
        return [(contacts[0], main.AlertDelivery(message_id="wamid-kan207"))], []

    monkeypatch.setattr(main, "send_alert_to_contacts", fake_send)
    return sent


def _upload(client: TestClient, path: Path, occurred_at: datetime) -> dict:
    response = client.post(
        "/v1/acoustic-audio", headers=HEADERS, content=path.read_bytes(),
        params={"occurred_at": occurred_at.isoformat()},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_real_cough_wav_alert_has_type_description_and_location(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, fixtures: dict[str, Path]
) -> None:
    _seed_home(client)
    _seed_contacts(client)
    sent = _capture_send(monkeypatch)

    body = _upload(client, fixtures["cough_repeated"], datetime(2026, 11, 4, 15, 4, tzinfo=timezone.utc))
    assert [item["outcome"]["action"] for item in body["results"]][-1] == "ask"

    outcome = client.post("/v1/acoustic-events/response", headers=JSON_HEADERS,
                          json={"text": "Ayuda, no me siento bien"}).json()
    assert outcome["action"] == "escalate"
    assert sent, "la alerta acustica debe enviarse a la red de cuidados"

    _, alert = sent[0]
    assert alert.kind == "hazard"
    assert alert.alert_type == "tos"
    assert "tos" in alert.spoken_message
    assert "detecciones" in alert.spoken_message
    assert alert.latitude == pytest.approx(HOME_LAT)
    assert alert.longitude == pytest.approx(HOME_LON)
    assert alert.location_source == "last_known"

    message = main.build_alert_message(alert)
    assert "Tipo: tos" in message
    assert "posible tos" in message
    assert "maps.google.com" in message

    events = client.get("/v1/events?limit=20", headers=JSON_HEADERS).json()
    escalated = [event for event in events
                 if (event.get("metadata") or {}).get("acoustic_stage") == "escalated"]
    assert escalated, "el escalado debe quedar registrado en la linea de tiempo"
    metadata = escalated[0]["metadata"]
    assert metadata["alert_type"] == "tos"
    assert metadata["alert_id"]
    assert metadata["location_included"] is True
    assert escalated[0]["latitude"] == pytest.approx(HOME_LAT)

    stored = main.repository.emergency_alerts
    assert len(stored) == 1
    saved = next(iter(stored.values()))
    assert saved.alert_type == "tos"
    assert saved.latitude == pytest.approx(HOME_LAT)


def test_no_response_after_real_cough_escalates_with_location(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, fixtures: dict[str, Path]
) -> None:
    _seed_home(client)
    _seed_contacts(client)
    sent = _capture_send(monkeypatch)
    _upload(client, fixtures["cough_repeated"], datetime(2026, 11, 4, 15, 4, tzinfo=timezone.utc))

    first = client.post("/v1/acoustic-events/tick", headers=JSON_HEADERS).json()
    assert first["action"] == "ask" and first["reason"] == "retry"
    later = datetime.now(timezone.utc) + timedelta(seconds=120)
    monkeypatch.setattr(main, "now", lambda: later)
    second = client.post("/v1/acoustic-events/tick", headers=JSON_HEADERS).json()
    assert second["action"] == "escalate"
    assert second["escalation"]["reason"] == "no_response"
    assert second["escalation"]["alert_type"] == "tos"
    assert second["escalation"]["description"]
    assert sent and sent[0][1].alert_type == "tos"
    assert "no responde" in sent[0][1].spoken_message
    assert sent[0][1].latitude == pytest.approx(HOME_LAT)


def test_gps_reciente_tiene_prioridad_sobre_el_domicilio(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_home(client)
    _seed_contacts(client)
    sent = _capture_send(monkeypatch)
    located = client.post("/v1/location/answer", headers=JSON_HEADERS, json={
        "latitude": 42.2406, "longitude": -8.7207, "accuracy_meters": 18,
    })
    assert located.status_code == 200, located.text

    for index in range(3):
        client.post("/v1/acoustic-events", headers=JSON_HEADERS, json={
            "signal": "cough", "confidence": 0.95,
        })
    outcome = client.post("/v1/acoustic-events/response", headers=JSON_HEADERS,
                          json={"text": "Ayuda"}).json()
    assert outcome["action"] == "escalate"
    alert = sent[0][1]
    assert alert.latitude == pytest.approx(42.2406)
    assert alert.longitude == pytest.approx(-8.7207)
    assert alert.location_source == "gps"


def test_whatsapp_template_uses_the_alert_type_and_description(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = main.MetaWhatsAppProvider("0", "token", "faro_emergency_alert")
    payloads: list[bytes] = []

    def fake_post(payload: bytes) -> dict:
        payloads.append(payload)
        return {"messages": [{"id": "wamid.kan207"}]}

    monkeypatch.setattr(provider, "_post_json", fake_post)
    alert = main.EmergencyAlertCreate(
        kind="hazard", alert_type="tos",
        spoken_message="posible tos (3 detecciones); el paciente pide ayuda.",
        explicit_help_request=False, latitude=HOME_LAT, longitude=HOME_LON,
    )

    class Contact:
        phone_e164 = "+34600000000"
        emergency_share_scope = "full"

    delivery = provider.send(Contact(), alert)
    assert delivery.message_id == "wamid.kan207"
    template = next(json.loads(payload) for payload in payloads
                    if json.loads(payload).get("type") == "template")
    parameters = template["template"]["components"][0]["parameters"]
    assert parameters[0]["text"] == "tos"
    assert "posible tos" in parameters[1]["text"]
    assert "3 detecciones" in parameters[1]["text"]
    assert "maps.google.com" in parameters[1]["text"]
