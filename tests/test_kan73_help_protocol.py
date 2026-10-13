"""KAN-73 - protocolo para pedir ayuda a terceros y contactar con el familiar prioritario."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "kan73-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("AURA_REVIEW_MEDIA_DIR", str(tmp_path / "review-images"))
    monkeypatch.setenv("AURA_REVIEW_SECRET", "test-review-secret")
    main.repository = main.InMemoryRepository()
    return TestClient(main.app)


def _add_contact(client: TestClient, name: str, phone: str, priority: int, enabled: bool = True) -> None:
    response = client.post("/v1/care-contacts", headers=HEADERS, json={
        "display_name": name, "phone_e164": phone, "role": "family",
        "whatsapp_consent": True, "priority": priority, "alerts_enabled": enabled,
    })
    assert response.status_code == 201, response.text


def test_protocolo_requiere_auth(client: TestClient) -> None:
    assert client.get("/v1/help-protocol").status_code == 401


def test_sin_contactos_devuelve_guia(client: TestClient) -> None:
    body = client.get("/v1/help-protocol", headers=HEADERS).json()
    assert body["contact"] is None
    assert "red de cuidados" in body["guidance"]


def test_elige_el_contacto_prioritario_y_su_alternativa(client: TestClient) -> None:
    _add_contact(client, "Bibiana", "+34600111222", priority=1)
    _add_contact(client, "Jose", "+34600333444", priority=2)
    body = client.get("/v1/help-protocol", headers=HEADERS).json()
    assert body["contact"]["display_name"] == "Bibiana"
    assert body["contact"]["phone_e164"] == "+34600111222"
    assert body["alternate"]["display_name"] == "Jose"


def test_ignora_contactos_sin_avisos_activos(client: TestClient) -> None:
    _add_contact(client, "SinAvisos", "+34600555666", priority=1, enabled=False)
    _add_contact(client, "Activa", "+34600777888", priority=2)
    body = client.get("/v1/help-protocol", headers=HEADERS).json()
    assert body["contact"]["display_name"] == "Activa"
    assert body["alternate"] is None


def test_frases_incluyen_nombre_telefono_y_direccion(client: TestClient) -> None:
    client.put("/v1/patient-profile", headers=HEADERS, json={
        "preferred_name": "Leonardo",
        "home_address": {"street_address": "Soutelo 21", "locality": "Cuntis"},
    })
    _add_contact(client, "Bibiana", "+34600111222", priority=1)
    body = client.get("/v1/help-protocol", headers=HEADERS).json()
    assert body["patient_name"] == "Leonardo"
    assert "Bibiana" in body["phrase_gl"] and "+34600111222" in body["phrase_gl"]
    assert "Soutelo 21" in body["phrase_gl"]
    assert "Bibiana" in body["phrase_es"] and "Soutelo 21" in body["phrase_es"]


def test_nombre_deletreado(client: TestClient) -> None:
    _add_contact(client, "Bibiana", "+34600111222", priority=1)
    body = client.get("/v1/help-protocol", headers=HEADERS).json()
    assert body["contact"]["spelled_name"] == "B, I, B, I, A, N, A"
