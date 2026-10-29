"""KAN-60 - datos completos de domicilio y contactos del paciente y la red de cuidados."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "kan60-token"
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
