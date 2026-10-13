"""KAN-126 — La cabecera del portal respeta la barra de estado en la app (TWA)."""

from __future__ import annotations

import re
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
    tokens_html = re.search(r"/assets/tokens\.css\?v=(\d+)", html)
    tokens_sw = re.search(r"'/assets/tokens\.css\?v=(\d+)'", sw)
    assert tokens_html and tokens_sw
    assert tokens_html.group(1) == tokens_sw.group(1)
    assert int(tokens_html.group(1)) >= 6
    cache = re.search(r"faro-familia-v(\d+)", sw)
    assert cache and int(cache.group(1)) >= 48
