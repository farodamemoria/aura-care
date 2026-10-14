"""KAN-142 — Voz de Faro (ElevenLabs) en las respuestas habladas del chat familiar."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "integration-family-speech-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
FAKE_MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff" * 32


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_CREDENTIAL_PEPPER", "test-pepper")
    main._family_speech_cache.clear()
    return TestClient(main.app)


def test_family_speech_returns_faro_voice_audio(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake(text: str) -> bytes:
        calls.append(text)
        return FAKE_MP3

    monkeypatch.setattr(main, "elevenlabs_speech", fake)
    response = client.post("/v1/family/speech", headers=HEADERS, json={"text": "Hola, hoy Carmen ha paseado."})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == FAKE_MP3
    assert calls == ["Hola, hoy Carmen ha paseado."]
    again = client.post("/v1/family/speech", headers=HEADERS, json={"text": "Hola, hoy Carmen ha paseado."})
    assert again.status_code == 200
    assert calls == ["Hola, hoy Carmen ha paseado."]


def test_family_speech_degrades_to_client_voice(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "elevenlabs_speech", lambda text: None)
    response = client.post("/v1/family/speech", headers=HEADERS, json={"text": "Buenas tardes"})
    assert response.status_code == 502


def test_family_speech_upstream_error_falls_back(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(text: str) -> bytes:
        raise RuntimeError("network down")

    monkeypatch.setattr(main, "elevenlabs_speech", boom)
    response = client.post("/v1/family/speech", headers=HEADERS, json={"text": "¿Qué tal todo?"})
    assert response.status_code == 502


def test_family_speech_requires_auth(client: TestClient) -> None:
    response = client.post("/v1/family/speech", json={"text": "hola"})
    assert response.status_code == 401


def test_family_speech_rejects_empty_text(client: TestClient) -> None:
    response = client.post("/v1/family/speech", headers=HEADERS, json={"text": ""})
    assert response.status_code == 422
