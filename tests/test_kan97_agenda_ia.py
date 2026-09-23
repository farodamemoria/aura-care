"""KAN-97 — Casos de uso / pruebas: la IA programa agendas (recordatorios) en Faro."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "integration-agenda-ia-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
INICIO = (datetime.now(timezone.utc) + timedelta(days=2)).replace(hour=18, minute=30, second=0, microsecond=0).isoformat()


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def _fake_openai(monkeypatch: pytest.MonkeyPatch, responses: list[dict]) -> list[dict]:
    captured: list[dict] = []
    queue = list(responses)

    def fake_urlopen(request, timeout=None):  # noqa: ANN001
        captured.append(json.loads(request.data.decode("utf-8")))
        return _FakeResponse(queue.pop(0))

    monkeypatch.setattr(main.urllib.request, "urlopen", fake_urlopen)
    return captured


@pytest.fixture(autouse=True)
def clean_calendar() -> None:
    main.repository.calendar_events.clear()


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_OPENAI_API_KEY", "test-openai-key")
    main.repository.calendar_events.clear()
    return TestClient(main.app)


def test_tool_creates_calendar_event() -> None:
    result = main.execute_family_tool("crear_recordatorio", json.dumps({
        "titulo": "Pastilla de la tensión", "fecha_hora": INICIO,
        "categoria": "medication", "avisar_minutos_antes": 10, "para_paciente": True,
    }))
    assert result["status"] == "ok"
    event = next(iter(main.repository.calendar_events.values()))
    assert event.title == "Pastilla de la tensión"
    assert event.category == "medication"
    assert event.reminder_minutes_before == 10
    assert event.for_patient is True
    assert event.start_at.isoformat() == INICIO


def test_tool_normalises_category_and_clamps_reminder() -> None:
    result = main.execute_family_tool("crear_recordatorio", json.dumps({
        "titulo": "Cita con la peluquería", "fecha_hora": INICIO,
        "categoria": "inventada", "avisar_minutos_antes": 5000, "para_paciente": False,
    }))
    assert result["status"] == "ok"
    event = next(iter(main.repository.calendar_events.values()))
    assert event.category == "other"
    assert event.reminder_minutes_before == 1440
    assert event.for_patient is False


def test_tool_rejects_bad_arguments() -> None:
    assert main.execute_family_tool("crear_recordatorio", "{}")["status"] == "error"
    assert main.execute_family_tool(
        "crear_recordatorio", json.dumps({"titulo": "x", "fecha_hora": "no-es-fecha"}),
    )["status"] == "error"
    assert main.execute_family_tool("desconocida", "{}")["detail"] == "unknown tool"


def test_tool_creates_recurring_reminder() -> None:
    result = main.execute_family_tool("crear_recordatorio", json.dumps({
        "titulo": "Medicación de la tensión", "fecha_hora": INICIO, "categoria": "medication",
        "recurrencia": "semanal", "dias_semana": [0, 2, 4], "repetir_cada": 1, "repetir_hasta": "2026-12-31",
    }))
    assert result["status"] == "ok"
    event = next(iter(main.repository.calendar_events.values()))
    assert event.recurrence == "weekly"
    assert event.recurrence_weekdays == [0, 2, 4]
    assert event.recurrence_until.isoformat() == "2026-12-31"


def test_prompt_requires_all_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_urlopen(request, timeout=None):  # noqa: ANN001
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse({"output": [{"type": "message", "content": [
            {"type": "output_text", "text": "¿A qué hora?"},
        ]}]})

    monkeypatch.setenv("AURA_OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(main.urllib.request, "urlopen", fake_urlopen)
    main.openai_family_answer("Programa una pastilla", [], "es")
    instructions = captured["payload"]["instructions"]
    assert "TODOS estos campos" in instructions
    assert "antelación" in instructions
    assert "se repite" in instructions


def test_prompt_exposes_agenda_and_calendar_tool(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    main.execute_family_tool("crear_recordatorio", json.dumps({
        "titulo": "Visita al médico", "fecha_hora": INICIO, "categoria": "appointment",
    }))
    captured = _fake_openai(monkeypatch, responses=[
        {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Tienes una visita."}]}]},
    ])
    answer = main.openai_family_answer("¿Qué hay en la agenda?", [], "es")
    assert answer == "Tienes una visita."
    payload = captured[0]
    assert "Agenda próxima" in payload["instructions"]
    assert "Visita al médico" in payload["instructions"]
    assert [tool["name"] for tool in payload["tools"]] == ["registrar_aviso", "crear_recordatorio"]


def test_family_ask_creates_reminder_via_ai(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_openai(monkeypatch, responses=[
        {"output": [{
            "type": "function_call", "name": "crear_recordatorio", "call_id": "call_1",
            "arguments": json.dumps({"titulo": "Tomar la pastilla", "fecha_hora": INICIO, "categoria": "medication"}),
        }]},
        {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Listo, lo he programado."}]}]},
    ])
    response = client.post("/v1/family/ask", headers=HEADERS, json={
        "question": "Recuérdale la pastilla de mañana a las 18:30",
    })
    assert response.status_code == 200, response.text
    assert response.json()["answer"] == "Listo, lo he programado."
    titles = [event.title for event in main.repository.calendar_events.values()]
    assert "Tomar la pastilla" in titles
