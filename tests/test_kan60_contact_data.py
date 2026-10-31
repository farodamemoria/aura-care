"""KAN-60 - datos completos de domicilio y contactos del paciente y la red de cuidados."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "kan60-token-5f3c9a7e1b6d8042c4e8a9f0d2b7c6"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    main.repository = main.InMemoryRepository()
    return TestClient(main.app)


def _profile_payload(**overrides):
    payload = {
        "preferred_name": "Leonardo",
        "full_name": "Leonardo Zuklevicius Mayo",
        "phone_e164": "+34600000000",
        "home_address": {
            "street_address": "Lugar Soutelo, 21",
            "postal_code": "36679",
            "locality": "Cuntis",
            "province": "Pontevedra",
            "country": "España",
            "access_notes": "Portón verde",
            "latitude": 42.6609,
            "longitude": -8.5689,
        },
        "safe_points": [
            {"street_address": "Centro de día", "locality": "Cuntis", "country": "España"},
        ],
        "address_verified_at": "2026-10-29T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def test_guarda_domicilio_completo_y_puntos_seguros(client: TestClient) -> None:
    response = client.put("/v1/patient-profile", headers=HEADERS, json=_profile_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["home_address"]["latitude"] == 42.6609
    assert body["address_verified_at"]
    assert len(body["safe_points"]) == 1
    stored = client.get("/v1/patient-profile", headers=HEADERS).json()
    assert stored["home_address"]["street_address"] == "Lugar Soutelo, 21"
    assert stored["home_address"]["access_notes"] == "Portón verde"


def test_admite_direccion_incompleta_sin_coordenadas(client: TestClient) -> None:
    payload = _profile_payload(home_address={"street_address": "Calle Mayor 1", "locality": "Cuntis"})
    response = client.put("/v1/patient-profile", headers=HEADERS, json=payload)
    assert response.status_code == 200
    assert response.json()["home_address"]["latitude"] is None


def test_contacto_con_direccion_telefono_alternativo_y_canal(client: TestClient) -> None:
    created = client.post("/v1/care-contacts", headers=HEADERS, json={
        "display_name": "Bibiana",
        "phone_e164": "+34644610954",
        "alternate_phone_e164": "+34644610955",
        "role": "family",
        "whatsapp_consent": True,
        "priority": 1,
        "preferred_channel": "call",
        "availability_notes": "Tardes",
        "address": {"street_address": "Rúa do Sol 3", "locality": "Cuntis", "country": "España"},
    })
    assert created.status_code == 201
    body = created.json()
    assert body["preferred_channel"] == "call"
    assert body["address"]["street_address"] == "Rúa do Sol 3"
    assert body["alternate_phone_e164"] == "+34644610955"

    patched = client.patch(f"/v1/care-contacts/{body['id']}", headers=HEADERS, json={
        "address": {"street_address": "Nueva 9", "locality": "Cuntis"},
        "preferred_channel": "sms",
    })
    assert patched.status_code == 200
    assert patched.json()["address"]["street_address"] == "Nueva 9"
    assert patched.json()["preferred_channel"] == "sms"


def test_canal_invalido_es_rechazado(client: TestClient) -> None:
    response = client.post("/v1/care-contacts", headers=HEADERS, json={
        "display_name": "José María", "phone_e164": "+34634443441",
        "role": "caregiver", "whatsapp_consent": True, "preferred_channel": "telegram",
    })
    assert response.status_code == 422


def test_varios_cuidadores_y_prioridad(client: TestClient) -> None:
    for index, name in enumerate(("Bibiana", "José María")):
        client.post("/v1/care-contacts", headers=HEADERS, json={
            "display_name": name, "phone_e164": f"+3460000000{index}", "role": "family",
            "whatsapp_consent": True, "priority": index + 1,
        })
    contacts = client.get("/v1/care-contacts", headers=HEADERS).json()
    names = [item["display_name"] for item in contacts]
    assert "Bibiana" in names and "José María" in names

def test_cambio_de_domicilio_actualiza_verificacion_y_auditoria(client: TestClient) -> None:
    first = client.put("/v1/patient-profile", headers=HEADERS, json=_profile_payload()).json()
    assert first["address_verified_at"]
    moved = _profile_payload(home_address={
        "street_address": "Rúa Nova 9", "postal_code": "36679", "locality": "Cuntis",
        "province": "Pontevedra", "country": "España",
        "latitude": 42.6610, "longitude": -8.5690,
    })
    moved.pop("address_verified_at", None)
    second = client.put("/v1/patient-profile", headers=HEADERS, json=moved).json()
    assert second["home_address"]["street_address"] == "Rúa Nova 9"
    assert second["address_verified_at"] and second["address_verified_at"] != first["address_verified_at"]
    events = client.get("/v1/events", headers=HEADERS, params={"kind": "caregiver_action"}).json()
    audit = [event for event in events if event["metadata"].get("patient_profile")]
    assert audit, "debe registrarse la modificacion de la ficha"
    latest = audit[0]
    assert "home_address" in latest["metadata"]["changed_fields"]
    assert latest["metadata"]["address_changed"] is True
    assert latest["metadata"]["actor"]
    assert latest["metadata"]["address_verified_at"]


def test_quitar_coordenadas_limpia_la_verificacion(client: TestClient) -> None:
    client.put("/v1/patient-profile", headers=HEADERS, json=_profile_payload())
    without = _profile_payload(home_address={"street_address": "Sin coordenadas", "locality": "Cuntis"})
    body = client.put("/v1/patient-profile", headers=HEADERS, json=without).json()
    assert body["home_address"]["latitude"] is None
    assert body["address_verified_at"] is None


def test_puntos_seguros_limitados_a_diez(client: TestClient) -> None:
    payload = _profile_payload(safe_points=[{"street_address": f"Punto seguro {index}"} for index in range(11)])
    assert client.put("/v1/patient-profile", headers=HEADERS, json=payload).status_code == 422


def test_alerta_usa_contactos_activos_y_datos_autorizados(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client.put("/v1/patient-profile", headers=HEADERS, json=_profile_payload())
    client.post("/v1/care-contacts", headers=HEADERS, json={
        "display_name": "Bibiana", "phone_e164": "+34644610954", "role": "family",
        "whatsapp_consent": True, "priority": 1, "preferred_channel": "call",
        "emergency_share_scope": "basic", "address": {"street_address": "Casa de Bibiana"},
    })
    client.post("/v1/care-contacts", headers=HEADERS, json={
        "display_name": "José María", "phone_e164": "+34634443441", "role": "caregiver",
        "whatsapp_consent": True, "priority": 2, "alerts_enabled": False,
        "emergency_share_scope": "full",
    })
    captured: list = []

    def fake_send(contacts, alert, image=None):  # noqa: ANN001
        captured.extend(contacts)
        return [(contact, main.AlertDelivery(message_id="wamid-kan60")) for contact in contacts], []

    monkeypatch.setattr(main, "send_alert_to_contacts", fake_send)
    response = client.post("/v1/emergency-alerts", headers=HEADERS, json={
        "kind": "lost", "spoken_message": "No sé dónde estoy", "explicit_help_request": True,
    })
    assert response.status_code == 201, response.text
    assert [contact.display_name for contact in captured] == ["Bibiana"]
    events = client.get("/v1/events", headers=HEADERS, params={"kind": "location"}).json()
    metadata = events[0]["metadata"]
    assert metadata["recipient_channels"] == "call"
    assert metadata["recipient_share_scopes"] == "basic"
    assert "Lugar Soutelo" in metadata["patient_home_address"]
    assert "Casa de Bibiana" not in metadata["patient_home_address"]


def test_alerta_sin_gps_incluye_el_domicilio_del_paciente(client: TestClient) -> None:
    client.put("/v1/patient-profile", headers=HEADERS, json=_profile_payload())
    contact = next(iter(client.get("/v1/care-contacts", headers=HEADERS).json()), None)
    if contact is None:
        client.post("/v1/care-contacts", headers=HEADERS, json={
            "display_name": "Bibiana", "phone_e164": "+34644610954",
            "whatsapp_consent": True, "priority": 1,
        })
    stored = main.repository.care_contacts
    contact_model = next(iter(stored.values()))
    provider = main.MetaWhatsAppProvider("0", "token", "faro_emergency_alert")
    payloads: list[dict] = []

    def fake_post(payload: bytes) -> dict:
        payloads.append(json.loads(payload))
        return {"messages": [{"id": "wamid-kan60"}]}

    provider._post_json = fake_post  # type: ignore[assignment]
    alert = main.EmergencyAlertCreate(
        kind="lost", spoken_message="No sé dónde estoy", explicit_help_request=True,
    )
    provider.send(contact_model, alert)
    assert payloads, "el proveedor debe enviar el aviso"
    body = json.dumps(payloads[0], ensure_ascii=False)
    assert "Domicilio del paciente" in body
    assert "Lugar Soutelo" in body
    assert "Casa de Bibiana" not in body


def test_registros_antiguos_sin_campos_nuevos_siguen_cargando() -> None:
    legacy_contact = {
        "id": "6f0a3a54-8e5c-4a3f-9c9f-2a1b3c4d5e6f",
        "created_at": "2026-08-01T09:00:00Z",
        "display_name": "José María", "phone_e164": "+34634443441",
        "role": "caregiver", "whatsapp_consent": True,
        "priority": 2, "alerts_enabled": True,
    }
    contact = main.CareContact.model_validate(legacy_contact)
    assert contact.preferred_channel == "whatsapp"
    assert contact.emergency_share_scope == "full"
    assert contact.emergency_notes == ""
    assert contact.address.street_address == ""

    legacy_profile = main.CaredPersonProfile.model_validate({"preferred_name": "Viviana"})
    assert legacy_profile.home_address.street_address == ""
    assert legacy_profile.home_address.latitude is None
    assert legacy_profile.safe_points == []
    assert legacy_profile.address_verified_at is None


def test_portal_muestra_campos_de_contacto_y_puntos_seguros(client: TestClient) -> None:
    page = client.get("/")
    assert page.status_code == 200
    for marker in (
        "Puntos seguros autorizados", 'name="home_safe_points"',
        'name="preferred_channel"', 'name="emergency_share_scope"',
    ):
        assert marker in page.text
    script = client.get("/assets/app.js?v=48")
    assert script.status_code == 200
    assert "safe_points: safePoints" in script.text
    assert "emergency_share_scope" in script.text

def _alert_payload_for(contact, alert) -> str:
    provider = main.MetaWhatsAppProvider("0", "token", "faro_emergency_alert")
    payloads: list[dict] = []

    def fake_post(payload: bytes) -> dict:
        payloads.append(json.loads(payload))
        return {"messages": [{"id": "wamid-kan60"}]}

    provider._post_json = fake_post  # type: ignore[assignment]
    provider.send(contact, alert)
    assert payloads
    return json.dumps(payloads[0], ensure_ascii=False)


def test_aviso_respeta_datos_autorizados_por_contacto(client: TestClient) -> None:
    client.put("/v1/patient-profile", headers=HEADERS, json=_profile_payload())
    base = {"display_name": "Bibiana", "phone_e164": "+34644610954", "whatsapp_consent": True, "priority": 1}
    contacts = {
        scope: main.CareContact(id=main.uuid4(), created_at=main.now(), emergency_share_scope=scope, **base)
        for scope in ("full", "location", "basic")
    }
    lost = main.EmergencyAlertCreate(kind="lost", spoken_message="No sé dónde estoy", explicit_help_request=True)
    full = _alert_payload_for(contacts["full"], lost)
    basic = _alert_payload_for(contacts["basic"], lost)
    assert "Domicilio del paciente" in full and "Lugar Soutelo" in full
    assert "Lugar Soutelo" not in basic

    located = main.EmergencyAlertCreate(
        kind="lost", spoken_message="No sé dónde estoy", explicit_help_request=True,
        latitude=42.2406, longitude=-8.7207,
    )
    location = _alert_payload_for(contacts["location"], located)
    basic_located = _alert_payload_for(contacts["basic"], located)
    assert "maps.google" in location and "Lugar Soutelo" not in location
    assert "maps.google" not in basic_located and "Lugar Soutelo" not in basic_located
