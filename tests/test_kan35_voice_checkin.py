"""KAN-35 - la respuesta hablada a «¿Estás bien?» llega al motor acústico.

Integra la transcripción de `/v1/voice/intent` con el episodio acústico activo:
una respuesta tranquilizadora cierra el episodio sin avisar, una petición de
ayuda (o un «no» seco) escala una sola vez y una frase larga dirigida a otra
persona no altera el episodio.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402
from app.environmental_listening import (  # noqa: E402
    EnvironmentalListeningEngine,
    ListeningConfig,
    interpret_check_in_answer,
)

TOKEN = "kan35-voice-checkin-token-7d1e5b90c3a4f2861d0e9b7c5a3f2e1"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
WAV = b"RIFF" + b"\x00" * 40 + b"PCM-AUDIO" * 8
DETECTION = {"signal": "cough", "confidence": 0.9}


@pytest.mark.parametrize("text,expected", [
    ("Estoy bien, gracias", "reassuring"),
    ("todo bien", "reassuring"),
    ("no me pasa nada", "reassuring"),
    ("Ayuda, me duele el pecho", "help"),
    ("socorro", "help"),
    ("No.", "help"),
    ("no, gracias", "help"),
    ("no estoy bien", "help"),
    ("me he caido", "help"),
    ("vamos a ver la television esta tarde con Maria", None),
    ("", None),
])
def test_interpret_check_in_answer(text: str, expected: str | None) -> None:
    assert interpret_check_in_answer(text) == expected


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_CREDENTIAL_PEPPER", "test-pepper")
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    main.repository = main.InMemoryRepository()
    main.repository.care_contacts.clear()
    main.repository.last_auto_alert.clear()
    main.acoustic_listening = EnvironmentalListeningEngine(ListeningConfig())
    return TestClient(main.app)


def configure_contact(client: TestClient) -> None:
    response = client.post("/v1/care-contacts", headers=HEADERS, json={
        "display_name": "Cuidadora", "phone_e164": "+34600111222", "role": "family",
        "whatsapp_consent": True, "priority": 1, "alerts_enabled": True,
    })
    assert response.status_code == 201, response.text


def start_episode(client: TestClient) -> None:
    for _ in range(3):
        assert client.post("/v1/acoustic-events", headers=HEADERS, json=DETECTION).status_code == 200
    assert main.acoustic_listening.active_episode is not None


def spoken(client: TestClient, monkeypatch: pytest.MonkeyPatch, transcript: str) -> dict:
    monkeypatch.setattr(main, "transcribe_audio", lambda data, filename="command.wav": transcript)
    response = client.post(
        "/v1/voice/intent", headers=HEADERS,
        data={"peak": "9000", "loud_ms": "400"},
        files={"audio": ("command.wav", WAV, "audio/wav")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_reassuring_spoken_answer_closes_without_alert(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    configure_contact(client)
    start_episode(client)
    body = spoken(client, monkeypatch, "Estoy bien, gracias")
    assert body["acoustic"]["action"] == "closed"
    assert body["acoustic"]["outcome"] == "reassured"
    assert body["acoustic"]["alerted"] is False
    assert body["alert_status"] is None
    assert main.acoustic_listening.active_episode is None
    assert client.get("/v1/events", headers=HEADERS, params={"kind": "hazard"}).json() == []
    episodes = client.get("/v1/events", headers=HEADERS, params={"kind": "episode"}).json()
    assert any(event["metadata"].get("acoustic_stage") == "reassured" for event in episodes)


def test_help_spoken_answer_escalates_once(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    configure_contact(client)
    start_episode(client)
    body = spoken(client, monkeypatch, "Ayuda, no puedo respirar")
    assert body["acoustic"]["action"] == "escalate"
    assert body["acoustic"]["escalation"]["reason"] == "help_request"
    assert body["matched"] is True
    assert body["alert_status"] in {"test_mode", "sent"}
    hazards = client.get("/v1/events", headers=HEADERS, params={"kind": "hazard"}).json()
    assert len(hazards) == 1
    assert "tos" in hazards[0]["summary"].casefold()


def test_short_negative_answer_escalates(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    start_episode(client)
    body = spoken(client, monkeypatch, "No.")
    assert body["acoustic"]["action"] == "escalate"
    assert body["acoustic"]["escalation"]["reason"] == "help_request"


def test_unrelated_speech_keeps_the_episode_waiting(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    start_episode(client)
    body = spoken(client, monkeypatch, "vamos a ver la television esta tarde con Maria")
    assert body["acoustic"] is None
    assert main.acoustic_listening.active_episode is not None
    assert main.acoustic_listening.active_episode.status == "awaiting_response"
    assert client.get("/v1/events", headers=HEADERS, params={"kind": "hazard"}).json() == []


def test_spoken_answer_without_episode_keeps_previous_behaviour(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    body = spoken(client, monkeypatch, "Estoy bien, gracias")
    assert body["acoustic"] is None
    assert body["matched"] is False
    assert client.get("/v1/events", headers=HEADERS).json() == []
