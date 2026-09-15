"""KAN-81 — Casos de uso / pruebas del plan de reparto de tareas entre asistentes.

Validan que `docs/kan81-delegacion.json` está completo y es coherente, que el
Markdown generado coincide con el comprometido en el repositorio y que la
fotografía de tareas pendientes de Jira (2026-09-15) está cubierta al 100 %.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PLAN_PATH = ROOT / "docs" / "kan81-delegacion.json"
MD_PATH = ROOT / "docs" / "kan81-delegacion-ia.md"
GENERADOR_PATH = ROOT / "scripts" / "kan81_generar_plan.py"

HERRAMIENTAS_ESPERADAS = {"deepseek-opencode", "copilot-pro", "gemini-pro", "amazon-quick", "leo"}
PRIORIDADES = {"Highest", "High", "Medium", "Low", "Lowest"}

PENDIENTES = {
    "KAN-6", "KAN-26", "KAN-34", "KAN-37", "KAN-38", "KAN-40", "KAN-41", "KAN-43",
    "KAN-45", "KAN-50", "KAN-51", "KAN-52", "KAN-53", "KAN-54", "KAN-55", "KAN-56",
    "KAN-59", "KAN-61", "KAN-63", "KAN-64", "KAN-65", "KAN-67", "KAN-68", "KAN-69",
    "KAN-70", "KAN-72", "KAN-73", "KAN-75", "KAN-77", "KAN-78", "KAN-79", "KAN-82",
    "KAN-85", "KAN-89", "KAN-91", "KAN-92", "KAN-93", "KAN-95", "KAN-97",
}

NO_DELEGADAS = {
    "KAN-30", "KAN-31", "KAN-33", "KAN-35", "KAN-36", "KAN-39", "KAN-44", "KAN-60",
    "KAN-62", "KAN-66", "KAN-81", "KAN-84", "KAN-86", "KAN-87", "KAN-96",
}


def _cargar_generador():
    spec = importlib.util.spec_from_file_location("kan81_generar_plan", GENERADOR_PATH)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def plan() -> dict:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


def test_plan_json_valido(plan: dict) -> None:
    assert plan["version"] == 1
    assert plan["actualizado"] == "2026-09-15"
    assert plan["fuente"].strip()
    assert plan["objetivo"].strip()
    assert len(plan["flujo"]) >= 3
    assert plan["herramientas"]
    assert plan["tareas"]
    assert plan["no_delegadas"]


def test_herramientas_completas(plan: dict) -> None:
    assert {h["id"] for h in plan["herramientas"]} == HERRAMIENTAS_ESPERADAS
    for herramienta in plan["herramientas"]:
        assert herramienta["nombre"].strip()
        assert herramienta["fortaleza"].strip()
        assert herramienta["acceso"].strip()


def test_claves_unicas_y_formato(plan: dict) -> None:
    claves = [t["clave"] for t in plan["tareas"]]
    assert len(claves) == len(set(claves))
    assert all(re.fullmatch(r"KAN-\d+", clave) for clave in claves)


def test_tareas_campos_completos(plan: dict) -> None:
    ids = {h["id"] for h in plan["herramientas"]}
    for tarea in plan["tareas"]:
        assert tarea["titulo"].strip()
        assert tarea["brief"].strip()
        assert tarea["prioridad"] in PRIORIDADES
        assert tarea["estado"] == "Por hacer"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", tarea["creada"])
        assert tarea["responsable"] in ids


def test_cobertura_exacta_de_pendientes(plan: dict) -> None:
    assert {t["clave"] for t in plan["tareas"]} == PENDIENTES


def test_kan81_no_se_autodelega(plan: dict) -> None:
    assert "KAN-81" not in {t["clave"] for t in plan["tareas"]}


def test_no_delegadas_completas(plan: dict) -> None:
    assert {t["clave"] for t in plan["no_delegadas"]} == NO_DELEGADAS
    for tarea in plan["no_delegadas"]:
        assert tarea["estado"] in {"En curso", "En revisión"}
        assert tarea["motivo"].strip()


def test_markdown_generado_coincide(plan: dict) -> None:
    generador = _cargar_generador()
    generado = generador.generar_markdown(plan)
    assert generado == MD_PATH.read_text(encoding="utf-8")


def test_markdown_contiene_cada_brief(plan: dict) -> None:
    markdown = MD_PATH.read_text(encoding="utf-8")
    for herramienta in plan["herramientas"]:
        assert f"### {herramienta['nombre']}" in markdown
    for tarea in plan["tareas"]:
        assert f"#### {tarea['clave']} — {tarea['titulo']}" in markdown
    assert markdown.count("#### ") == len(plan["tareas"])


def test_resumen_ordenado_por_prioridad(plan: dict) -> None:
    generador = _cargar_generador()
    esperado = [t["clave"] for t in generador.ordenar_tareas(plan["tareas"])]
    markdown = MD_PATH.read_text(encoding="utf-8")
    resumen = markdown.split("## Briefs por herramienta")[0]
    filas = [
        linea.split("|")[1].strip()
        for linea in resumen.splitlines()
        if linea.startswith("| KAN-")
    ]
    assert filas == esperado
