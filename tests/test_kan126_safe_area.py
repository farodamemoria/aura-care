"""KAN-126 — La cabecera del portal respeta la barra de estado en la app (TWA)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_hero_usa_safe_area_inset() -> None:
    css = (ROOT / "web" / "assets" / "tokens.css").read_text(encoding="utf-8")
    assert "env(safe-area-inset-top" in css
    assert ".hero { padding-top: max(" in css


def test_viewport_cover_activo() -> None:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert "viewport-fit=cover" in html


def test_versiones_de_cache_actualizadas() -> None:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    sw = (ROOT / "web" / "assets" / "sw.js").read_text(encoding="utf-8")
    assert "/assets/tokens.css?v=6" in html
    assert "/assets/tokens.css?v=6" in sw
    assert "faro-familia-v48" in sw
