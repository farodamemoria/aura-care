"""KAN-85 — Casos de uso / pruebas del guion de la demo (sin red).

Validan que el guion está completo (preparación, casos con sus bloques y
verificación) y que el verificador `scripts/kan85_verificar_demo.py` es
coherente con el guion y con los enlaces reales del portal.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GUION_PATH = ROOT / "docs" / "kan85-guion-demo.md"
SCRIPT_PATH = ROOT / "scripts" / "kan85_verificar_demo.py"
PORTAL_PATH = ROOT / "web" / "index.html"


def _cargar_script():
    spec = importlib.util.spec_from_file_location("kan85_verificar_demo", SCRIPT_PATH)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def guion() -> str:
    return GUION_PATH.read_text(encoding="utf-8")


def test_guion_tiene_secciones_obligatorias(guion: str) -> None:
    for titulo in (
        "## 1. Preparación",
        "## 2. Casos de uso",
        "## 3. Guion hablado",
        "## 4. Verificación técnica",
        "## 5. Lo que aún requiere ensayo con hardware",
        "## 6. Ensayos",
    ):
        assert titulo in guion


def test_checklists_presentes(guion: str) -> None:
    assert "Checklist de la víspera" in guion
    assert "Checklist 30 minutos antes" in guion


def test_casos_de_uso_completos(guion: str) -> None:
    assert len(re.findall(r"^### Caso \d+ — ", guion, flags=re.MULTILINE)) >= 6
    for bloque in guion.split("### Caso ")[1:]:
        for etiqueta in ("**Objetivo**", "**Preparación**", "**Pasos**", "**Resultado esperado**", "**Plan B**"):
            assert etiqueta in bloque


def test_verificacion_lista_los_mismos_paths(guion: str) -> None:
    script = _cargar_script()
    for comprobacion in script.COMPROBACIONES:
        assert f"`{comprobacion['path']}`" in guion


def test_comprobaciones_bien_formadas() -> None:
    script = _cargar_script()
    ids = [c["id"] for c in script.COMPROBACIONES]
    assert len(ids) == len(set(ids))
    for comprobacion in script.COMPROBACIONES:
        assert comprobacion["path"].startswith(("/", "http"))
        assert comprobacion["tipo"] in {"html", "json", "archivo"}
        assert comprobacion["descripcion"].strip()


def test_descargas_coinciden_con_el_portal() -> None:
    script = _cargar_script()
    portal = PORTAL_PATH.read_text(encoding="utf-8")
    paths = {c["path"] for c in script.COMPROBACIONES if c["tipo"] == "archivo"}
    assert paths
    for path in paths:
        assert f'href="{path}"' in portal


def test_features_requeridas_completas() -> None:
    script = _cargar_script()
    assert {"family_conversation", "family_ai", "location_tracking", "family_alerts"} <= set(
        script.FEATURES_REQUERIDAS
    )
