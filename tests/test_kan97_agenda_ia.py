"""KAN-97 — Pruebas de la agenda creada por la IA del chat familiar."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "integration-agenda-ia-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_CREDENTIAL_PEPPER", "test-pepper")
    main.repository.calendar_events.clear()
    return TestClient(main.app)


def test_herramienta_de_agenda_expuesta() -> None:
    assert main.FAMILY_AGENDA_TOOL["name"] == "crear_evento_agenda"


def test_crea_evento_desde_la_ia(client: TestClient) -> None:
    resultado = main.execute_family_tool(
        "crear_evento_agenda",
        '{"titulo":"Visita del médico","cuando":"2026-09-20T10:00:00+02:00","categoria":"appointment","aviso_minutos":30}',
    )
    assert resultado["status"] == "ok"
    eventos = client.get("/v1/calendar-events", headers=HEADERS).json()
    evento = next(item for item in eventos if item["title"] == "Visita del médico")
    assert evento["category"] == "appointment"
    assert evento["reminder_minutes_before"] == 30


def test_categoria_invalida_usa_otra_y_aviso_por_defecto(client: TestClient) -> None:
    resultado = main.execute_family_tool(
        "crear_evento_agenda",
        '{"titulo":"Paseo","cuando":"2026-09-20T18:00:00+02:00","categoria":"otra"}',
    )
    assert resultado["status"] == "ok"
    assert resultado["category"] == "other"
    eventos = client.get("/v1/calendar-events", headers=HEADERS).json()
    paseo = next(item for item in eventos if item["title"] == "Paseo")
    assert paseo["reminder_minutes_before"] == 15


def test_argumentos_invalidos() -> None:
    assert main.execute_family_tool("crear_evento_agenda", '{"titulo":""}')["status"] == "error"
    assert main.execute_family_tool(
        "crear_evento_agenda", '{"titulo":"X","cuando":"no-es-fecha"}',
    )["status"] == "error"
    assert main.execute_family_tool("desconocida", "{}")["status"] == "error"


def test_sigue_creando_avisos() -> None:
    resultado = main.execute_family_tool(
        "registrar_aviso", '{"descripcion":"Avisar si se cae","palabras_clave":["caida"]}',
    )
    assert resultado["status"] == "ok"
