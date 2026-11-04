"""KAN-191: log central de errores de los aplicativos (gafas, movil y portal)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "integration-app-errors-token-9c4e1f7a2b8d3056e7a9c1b4d6f80912"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("AURA_CREDENTIAL_PEPPER", "test-pepper")
    main.repository = main.InMemoryRepository()
    return TestClient(main.app)


def _report(**overrides) -> dict:
    payload = {
        "app": "faro-movil",
        "version": "0.1-mvp",
        "message": "NullPointerException en MobileVoiceController",
        "context": "screen=conversation action=start",
        "traceback_text": "java.lang.NullPointerException\n\tat MobileVoiceController.start(MobileVoiceController.kt:88)",
    }
    payload.update(overrides)
    return payload


def _device_credential(client: TestClient) -> str:
    invite = client.post("/v1/pairing-invites", headers=HEADERS, json={"role": "caregiver"})
    assert invite.status_code == 201
    claim = client.post("/v1/pairing/claim", json={"code": invite.json()["code"]})
    assert claim.status_code == 200
    return claim.json()["device_credential"]


def test_register_error_persists_and_is_listed(client: TestClient) -> None:
    response = client.post("/v1/app-errors", headers=HEADERS, json=_report())
    assert response.status_code == 201
    body = response.json()
    assert body["app"] == "faro-movil"
    assert body["version"] == "0.1-mvp"
    assert body["message"].startswith("NullPointerException")
    assert len(body["fingerprint"]) == 16
    assert body["ticket_key"] is None

    listing = client.get("/v1/app-errors", headers=HEADERS)
    assert listing.status_code == 200
    items = listing.json()
    assert len(items) == 1
    assert items[0]["id"] == body["id"]
    assert items[0]["traceback"].startswith("java.lang.NullPointerException")
    assert items[0]["context"] == "screen=conversation action=start"


def test_same_failure_with_new_ids_and_numbers_keeps_fingerprint(client: TestClient) -> None:
    first = client.post("/v1/app-errors", headers=HEADERS, json=_report()).json()
    second = client.post(
        "/v1/app-errors",
        headers=HEADERS,
        json=_report(
            context="screen=conversation request=7f3c9a7e-1b6d-8042-c4e8-a9f0d2b7c6aa",
            traceback_text="java.lang.NullPointerException\n\tat MobileVoiceController.start(MobileVoiceController.kt:142)",
        ),
    ).json()
    assert first["fingerprint"] == second["fingerprint"]
    assert first["id"] != second["id"]


def test_anonymous_requests_are_rejected(client: TestClient) -> None:
    assert client.post("/v1/app-errors", json=_report()).status_code == 401
    assert client.get("/v1/app-errors").status_code == 401


def test_device_credential_can_report_errors(client: TestClient) -> None:
    credential = _device_credential(client)
    response = client.post(
        "/v1/app-errors",
        headers={"Authorization": f"Bearer {credential}"},
        json=_report(app="camera-access", version="1.0"),
    )
    assert response.status_code == 201
    assert response.json()["app"] == "camera-access"


def test_invalid_payload_is_rejected(client: TestClient) -> None:
    assert client.post("/v1/app-errors", headers=HEADERS, json=_report(message="")).status_code == 422
    oversized = "x" * 20001
    assert (
        client.post("/v1/app-errors", headers=HEADERS, json=_report(traceback_text=oversized)).status_code
        == 422
    )


def test_listing_limit_and_app_filter(client: TestClient) -> None:
    client.post("/v1/app-errors", headers=HEADERS, json=_report(app="camera-access", version="1.0"))
    client.post("/v1/app-errors", headers=HEADERS, json=_report(app="faro-movil"))
    filtered = client.get("/v1/app-errors?app=camera-access", headers=HEADERS)
    assert filtered.status_code == 200
    assert [item["app"] for item in filtered.json()] == ["camera-access"]
    assert client.get("/v1/app-errors?limit=0", headers=HEADERS).status_code == 422
    assert client.get("/v1/app-errors?limit=201", headers=HEADERS).status_code == 422


def test_fingerprint_is_stable_across_processes() -> None:
    trace = "java.lang.IllegalStateException at CameraViewModel.kt:42"
    expected = main.app_error_fingerprint("camera-access", "IllegalStateException", trace)
    assert expected == main.app_error_fingerprint(" Camera-Access ", "IllegalStateException", trace)
    assert len(expected) == 16
    assert expected != main.app_error_fingerprint("camera-access", "Otro error", trace)
