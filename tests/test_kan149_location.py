"""KAN-149 — la ubicacion reconoce casa (coords del perfil) y da el entorno tipo Maps."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "integration-kan149-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    return TestClient(main.app)


def _set_home() -> None:
    profile = main.repository.get_patient_profile()
    if profile is None:
        profile = main.CaredPersonProfile(preferred_name="Leonardo")
    profile.home_address = main.PostalAddress(
        street_address="Lugar Soutelo, 21", postal_code="36679", locality="Cuntis",
        province="Pontevedra", country="España", latitude=42.6609203, longitude=-8.5689992,
    )
    main.repository.save_patient_profile(profile)


def test_at_home_uses_profile_coordinates(client: TestClient) -> None:
    _set_home()
    response = client.post("/v1/location/answer", headers=HEADERS, json={
        "latitude": 42.6609203, "longitude": -8.5689992, "accuracy_meters": 15,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "at_home"
    assert "en casa" in body["message"]
    assert "Cuntis" in body["message"]


def test_away_reports_surroundings(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_home()
    monkeypatch.setattr(main, "reverse_geocode", lambda latitude, longitude: "Rúa de Vigo, Pontevedra")
    response = client.post("/v1/location/answer", headers=HEADERS, json={
        "latitude": 42.2406, "longitude": -8.7207, "accuracy_meters": 20,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "coordinates_available"
    assert "cerca de" in body["message"]
    assert "metros de casa" in body["message"]
