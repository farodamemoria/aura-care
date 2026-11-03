"""KAN-195 - el recordatorio no se consume hasta que se reproduce (peek + reserva + ack)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "kan195-token-5f3c9a7e1b6d8042c4e8a9f0d2b7c6"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("AURA_TICK_SCHEDULER", "0")
    main.repository = main.InMemoryRepository()
    monkeypatch.setattr(main, "ensure_daily_generic_exercises", lambda reference=None: 0)
    return TestClient(main.app)


def _enqueue_calendar_reminder(client: TestClient) -> None:
    created = client.post("/v1/calendar-events", headers=HEADERS, json={
        "title": "Hacer algo",
        "start_at": "2026-09-20T18:30:00+02:00",
        "reminder_minutes_before": 10,
        "for_patient": True,
    })
    assert created.status_code == 201
    client.post("/v1/calendar-tick", headers=HEADERS, params={"at": "2026-09-20T18:20:00+02:00"})


def _pending_count() -> int:
    return main.repository.event_db.execute(
        "SELECT count(*) FROM voice_reminders WHERE spoken_at IS NULL"
    ).fetchone()[0]


def test_peek_no_consume_el_recordatorio(client: TestClient) -> None:
    _enqueue_calendar_reminder(client)
    assert _pending_count() == 1

    first = client.get("/v1/voice-reminders", headers=HEADERS, params={"peek": "1"}).json()
    second = client.get("/v1/voice-reminders", headers=HEADERS, params={"peek": "1"}).json()

    assert len(first) == 1
    assert len(second) == 1
    assert first[0]["id"] == second[0]["id"]
    assert "Hacer algo" in first[0]["message"]
    assert _pending_count() == 1, "peek no debe marcar como hablado"


def test_claim_reserva_sin_consumir_y_ack_confirma(client: TestClient) -> None:
    _enqueue_calendar_reminder(client)

    claim = client.post("/v1/voice-reminders/claim", headers=HEADERS)
    assert claim.status_code == 200
    payload = claim.json()
    assert payload["lease_seconds"] == main.VOICE_REMINDER_LEASE_SECONDS
    assert len(payload["reminders"]) == 1
    reminder_id = payload["reminders"][0]["id"]

    assert client.get("/v1/voice-reminders", headers=HEADERS, params={"peek": "1"}).json() == []
    assert _pending_count() == 1, "reservar no debe marcar como hablado"

    ack = client.post("/v1/voice-reminders/ack", headers=HEADERS, json={"ids": [reminder_id]})
    assert ack.status_code == 200
    assert ack.json()["acked"] == 1
    assert _pending_count() == 0
    assert client.get("/v1/voice-reminders", headers=HEADERS, params={"peek": "1"}).json() == []


def test_claim_sin_ack_vuelve_a_la_cola(client: TestClient) -> None:
    _enqueue_calendar_reminder(client)
    assert len(client.post("/v1/voice-reminders/claim", headers=HEADERS).json()["reminders"]) == 1

    expired = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    main.repository.event_db.execute(
        "UPDATE voice_reminders SET claimed_until=? WHERE spoken_at IS NULL", (expired,)
    )
    main.repository.event_db.commit()

    pending = client.get("/v1/voice-reminders", headers=HEADERS, params={"peek": "1"}).json()
    assert len(pending) == 1
    assert _pending_count() == 1


def test_ack_marca_el_ejercicio_preguntado_solo_al_confirmar(client: TestClient) -> None:
    when = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    created = client.post("/v1/cognitive-exercises/scheduled", headers=HEADERS, json={
        "question": "¿Cómo se llamaba tu madre?",
        "expected_answer": "Maria",
        "scheduled_at": when,
    })
    assert created.status_code == 201
    exercise_id = created.json()["id"]
    assert client.post("/v1/cognitive-exercises/tick", headers=HEADERS).json()["asked"] == 1

    claim = client.post("/v1/voice-reminders/claim", headers=HEADERS).json()
    assert len(claim["reminders"]) == 1
    reminder = claim["reminders"][0]
    assert reminder["kind"] == "exercise"
    assert main.repository.cognitive_exercises[main.UUID(exercise_id)].asked_at is None

    client.post("/v1/voice-reminders/ack", headers=HEADERS, json={"ids": [reminder["id"]]})
    assert main.repository.cognitive_exercises[main.UUID(exercise_id)].asked_at is not None


def test_retry_devuelve_a_la_cola_y_limpia_la_reserva(client: TestClient) -> None:
    _enqueue_calendar_reminder(client)
    claim = client.post("/v1/voice-reminders/claim", headers=HEADERS).json()
    reminder = claim["reminders"][0]
    client.post("/v1/voice-reminders/ack", headers=HEADERS, json={"ids": [reminder["id"]]})

    retry = client.post(
        f"/v1/voice-reminders/{reminder['event_id']}/retry", headers=HEADERS
    )
    assert retry.status_code == 200
    pending = client.get("/v1/voice-reminders", headers=HEADERS, params={"peek": "1"}).json()
    assert len(pending) == 1
    assert pending[0]["id"] == reminder["id"]
    assert main.repository.event_db.execute(
        "SELECT claimed_until FROM voice_reminders WHERE id=?", (reminder["id"],)
    ).fetchone()[0] is None


def test_claim_y_ack_exigen_autenticacion(client: TestClient) -> None:
    assert client.post("/v1/voice-reminders/claim").status_code == 401
    assert client.post("/v1/voice-reminders/ack", json={"ids": []}).status_code == 401


def test_ack_vacio_o_desconocido_no_falla(client: TestClient) -> None:
    assert client.post("/v1/voice-reminders/ack", headers=HEADERS, json={"ids": []}).json() == {
        "acked": 0
    }
    unknown = "00000000-0000-4000-8000-000000000000"
    assert client.post(
        "/v1/voice-reminders/ack", headers=HEADERS, json={"ids": [unknown]}
    ).json() == {"acked": 0}
