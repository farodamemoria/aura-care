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
