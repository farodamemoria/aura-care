"""KAN-35 — Endpoint de audio ambiental (WAV) de extremo a extremo."""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402
from app.environmental_listening import EnvironmentalListeningEngine, ListeningConfig  # noqa: E402

TOKEN = "integration-acoustic-audio-token-9a2f4c6e8b1d3570a5c4e2f9b7d1a3c6"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "audio/wav"}
JSON_HEADERS = {"Authorization": f"Bearer {TOKEN}"}
AUDIO_DIR = Path(__file__).resolve().parent / "fixtures" / "audio"


@pytest.fixture(scope="session")
def fixtures(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    spec = importlib.util.spec_from_file_location("kan35_fixtures_http", AUDIO_DIR / "generate_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.build_fixtures(tmp_path_factory.mktemp("kan35-http"))


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_CREDENTIAL_PEPPER", "test-pepper")
    main.repository.care_contacts.clear()
    main.repository.last_auto_alert.clear()
    main.acoustic_listening = EnvironmentalListeningEngine(ListeningConfig())
    return TestClient(main.app)


def upload(client: TestClient, path: Path, occurred_at: datetime | None = None) -> dict:
    params = {"occurred_at": occurred_at.isoformat()} if occurred_at else None
    response = client.post("/v1/acoustic-audio", headers=HEADERS, content=path.read_bytes(), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_audio_endpoint_requires_authentication(client: TestClient, fixtures: dict[str, Path]) -> None:
    response = client.post("/v1/acoustic-audio", content=fixtures["cough_repeated"].read_bytes())
    assert response.status_code == 401


def test_repeated_cough_wav_asks_once_and_records_the_episode(
    client: TestClient, fixtures: dict[str, Path]
) -> None:
    body = upload(client, fixtures["cough_repeated"], datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc))
    assert len(body["events"]) >= 3
    assert [item["outcome"]["action"] for item in body["results"]][-1] == "ask"
    assert body["results"][-1]["outcome"]["question"] == "¿Estás bien?"
    episodes = client.get("/v1/acoustic-episodes", headers=JSON_HEADERS).json()
    assert episodes["active"]["signal"] == "cough"
    events = client.get("/v1/events", headers=JSON_HEADERS, params={"kind": "episode"}).json()
    assert any("Posible tos" in event["summary"] for event in events)


def test_white_noise_wav_does_not_alert(client: TestClient, fixtures: dict[str, Path]) -> None:
    body = upload(client, fixtures["white_noise"], datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc))
    assert body["events"] == [] and body["results"] == []
    assert client.get("/v1/acoustic-episodes", headers=JSON_HEADERS).json()["history"] == []


def test_real_room_wav_does_not_alert(client: TestClient) -> None:
    body = upload(client, AUDIO_DIR / "ambiente-sala-real.wav",
                  datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc))
    assert body["events"] == []
    assert client.get("/v1/acoustic-episodes", headers=JSON_HEADERS).json()["active"] is None


def test_reassuring_answer_after_audio_stops_without_alert(client: TestClient, fixtures: dict[str, Path]) -> None:
    upload(client, fixtures["cough_repeated"], datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc))
    outcome = client.post("/v1/acoustic-events/response", headers=JSON_HEADERS,
                          json={"text": "Estoy bien, gracias"}).json()
    assert outcome["action"] == "closed" and outcome["alerted"] is False


def test_fall_wav_escalates_when_the_patient_does_not_answer(
    client: TestClient, fixtures: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    upload(client, fixtures["fall"], datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc))
    first = client.post("/v1/acoustic-events/tick", headers=JSON_HEADERS).json()
    assert first["action"] == "ask" and first["reason"] == "retry"
    later = datetime.now(timezone.utc) + timedelta(seconds=120)
    monkeypatch.setattr(main, "now", lambda: later)
    second = client.post("/v1/acoustic-events/tick", headers=JSON_HEADERS).json()
    assert second["action"] == "escalate"
    assert second["escalation"]["reason"] == "no_response"
    assert second["escalation"]["signal"] == "fall"


def test_audio_endpoint_rejects_invalid_wav(client: TestClient) -> None:
    response = client.post("/v1/acoustic-audio", headers=HEADERS, content=b"no soy un wav")
    assert response.status_code == 400

