"""KAN-144 — /v1/location/answer acepta credencial de dispositivo (app movil) ademas del token local."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "integration-device-location-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("AURA_CREDENTIAL_PEPPER", "test-pepper")
    main.repository = main.InMemoryRepository()
    return TestClient(main.app)


def _device_credential(client: TestClient) -> str:
    invite = client.post("/v1/pairing-invites", headers=HEADERS, json={"role": "caregiver"})
    assert invite.status_code == 201
    claim = client.post("/v1/pairing/claim", json={"code": invite.json()["code"]})
    assert claim.status_code == 200
    return claim.json()["device_credential"]


def test_location_answer_accepts_device_credential(client: TestClient) -> None:
    credential = _device_credential(client)
    response = client.post(
        "/v1/location/answer",
        headers={"Authorization": f"Bearer {credential}"},
        json={"latitude": 42.24, "longitude": -8.72, "accuracy_meters": 25},
    )
    assert response.status_code == 200
    assert response.json()["status"] in {"coordinates_available", "refresh_required", "at_home"}


def test_location_answer_still_accepts_local_token(client: TestClient) -> None:
    response = client.post(
        "/v1/location/answer", headers=HEADERS,
        json={"latitude": 42.24, "longitude": -8.72, "accuracy_meters": 25},
    )
    assert response.status_code == 200


def test_location_answer_rejects_unknown_credential(client: TestClient) -> None:
    response = client.post(
        "/v1/location/answer",
        headers={"Authorization": "Bearer credencial-invalida"},
        json={"latitude": 42.24, "longitude": -8.72},
    )
    assert response.status_code == 401
