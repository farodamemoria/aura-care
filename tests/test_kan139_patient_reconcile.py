"""KAN-139 - auto-sanado de contadores de fotos del paciente (sin 404s)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "kan139-token-5f3c9a7e1b6d8042c4e8a9f0d2b7c6"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
JPEG = b"\xff\xd8\xff\xe0" + b"FACE-JPEG" * 8 + b"\xff\xd9"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("AURA_REVIEW_MEDIA_DIR", str(tmp_path / "review-images"))
    monkeypatch.setenv("AURA_REVIEW_SECRET", "test-review-secret")
    main.repository = main.InMemoryRepository()
    return TestClient(main.app)


def test_perfil_requiere_auth(client: TestClient) -> None:
    assert client.get("/v1/patient-profile").status_code == 401


def test_contadores_inflados_se_corrigen_sin_ficheros(client: TestClient) -> None:
    client.put("/v1/patient-profile", headers=HEADERS, json={
        "preferred_name": "Leonardo",
        "face_enrollment_samples": 5,
        "face_enrollment_complete": True,
        "profile_photo_available": True,
    })
    body = client.get("/v1/patient-profile", headers=HEADERS).json()
    assert body["face_enrollment_samples"] == 0
    assert body["face_enrollment_complete"] is False
    assert body["profile_photo_available"] is False
    again = client.get("/v1/patient-profile", headers=HEADERS).json()
    assert again["face_enrollment_samples"] == 0


def test_cuenta_muestras_reales_existentes(client: TestClient) -> None:
    client.put("/v1/patient-profile", headers=HEADERS, json={
        "preferred_name": "Leonardo",
        "face_enrollment_samples": 5,
        "face_enrollment_complete": True,
        "profile_photo_available": True,
    })
    assert main.repository.save_person_photos(main.PATIENT_FACE_ID, [JPEG] * 3) == 3
    body = client.get("/v1/patient-profile", headers=HEADERS).json()
    assert body["face_enrollment_samples"] == 3
    assert body["face_enrollment_complete"] is False
    assert body["profile_photo_available"] is True
