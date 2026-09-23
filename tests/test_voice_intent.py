"""Escenario 2 — peticiones de ayuda por voz («estoy perdido/a», es y gl)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402
from app.environmental_listening import is_lost_request  # noqa: E402

TOKEN = "voice-intent-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
WAV = b"RIFF" + b"\x00" * 40 + b"PCM-AUDIO" * 8


@pytest.mark.parametrize("text", [
    "estoy perdido", "Estoy perdida", "no sé dónde estoy", "no se donde estoy",
    "me he perdido", "estoy desorientado", "estoy desorientada", "no encuentro el camino",
    "no sé volver", "estou perdido", "estou perdida", "non sei onde estou",
    "perdinme", "non atopo o camiño", "non sei volver",
])
def test_lost_phrases_are_detected(text: str) -> None:
    assert is_lost_request(text)


@pytest.mark.parametrize("text", ["estoy bien", "vamos para casa", "hola Faro", "qué tal todo", ""])
def test_neutral_phrases_are_not_detected(text: str) -> None:
    assert not is_lost_request(text)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("AURA_CREDENTIAL_PEPPER", "test-pepper")
    main.repository = main.InMemoryRepository()
    return TestClient(main.app)


def test_voice_intent_triggers_alert_when_lost(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "transcribe_audio", lambda data, filename="command.wav": "estoy perdido, no sé dónde estoy")
    response = client.post(
        "/v1/voice/intent", headers=HEADERS,
        files={"audio": ("command.wav", WAV, "audio/wav")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is True
    assert "perdido" in body["transcript"]


def test_voice_intent_ignores_neutral_speech(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "transcribe_audio", lambda data, filename="command.wav": "estoy bien, gracias")
    response = client.post(
        "/v1/voice/intent", headers=HEADERS,
        files={"audio": ("command.wav", WAV, "audio/wav")},
    )
    assert response.json()["matched"] is False


def test_voice_intent_requires_auth(client: TestClient) -> None:
    response = client.post("/v1/voice/intent", files={"audio": ("command.wav", WAV, "audio/wav")})
    assert response.status_code == 401


def test_impact_uses_clear_summary_not_transcript(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        main, "transcribe_audio",
        lambda data, filename="command.wav": "Subtítulos realizados por la comunidad de Amara.org",
    )
    response = client.post(
        "/v1/voice/intent", headers=HEADERS,
        data={"peak": "9000", "loud_ms": "120"},
        files={"audio": ("command.wav", WAV, "audio/wav")},
    )
    assert response.status_code == 200
    assert response.json()["matched"] is True
    events = client.get("/v1/events?limit=5", headers=HEADERS).json()
    assert any(event["summary"] == "Posible caída o golpe fuerte detectado" for event in events)
    assert all("Amara" not in event["summary"] for event in events)


def test_clear_events_empties_history(client: TestClient) -> None:
    client.post("/v1/events", headers=HEADERS, json={"kind": "system", "summary": "Prueba", "source": "portal"})
    assert client.get("/v1/events", headers=HEADERS).json()
    response = client.delete("/v1/events", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["deleted"] >= 1
    assert client.get("/v1/events", headers=HEADERS).json() == []
    assert client.delete("/v1/events").status_code == 401


def test_reset_cooldowns_clears_recognition_state(client: TestClient) -> None:
    main.repository.last_outcome["local-care-circle:person:x"] = main.now()
    response = client.post("/v1/admin/reset-cooldowns", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["cleared"] == 1
    assert main.repository.last_outcome == {}
    assert client.post("/v1/admin/reset-cooldowns").status_code == 401
