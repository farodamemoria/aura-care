"""KAN-69 - proceso de Q&A y feedback de pilotos (documento publicado)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "kan69-proceso-qa-pilotos.md"


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def test_documento_publicado_con_plantilla_completa() -> None:
    text = _text()
    for field in (
        "Aplicación:",
        "Versión:",
        "Dispositivo:",
        "Pasos:",
        "Resultado esperado:",
        "Resultado observado:",
        "Evidencia:",
        "Severidad:",
    ):
        assert field in text, field


def test_severidades_y_flujo() -> None:
    text = _text()
    assert "S1 crítico" in text and "S4 cosmético" in text
    assert "relates to" in text
    assert "Revisión de sprint" in text


def test_responsables_definidos() -> None:
    text = _text()
    for name in ("Leonardo", "Leo", "Jose", "Bibiana"):
        assert name in text


def test_primer_ciclo_aplicado_a_las_tres_apps() -> None:
    text = _text()
    assert "CameraAccess" in text
    assert "Faro Móvil" in text
    assert "Faro Familia" in text
    assert "2026-10-13" in text


def test_criterios_de_cierre_marcados() -> None:
    text = _text()
    assert text.count("- [x]") >= 3
