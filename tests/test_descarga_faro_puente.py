"""KAN — Descarga de la app Faro Puente desde la web."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402


def test_ruta_de_descarga_existe() -> None:
    rutas = {getattr(ruta, "path", "") for ruta in main.app.routes}
    assert "/download/faro-puente.apk" in rutas


def test_portal_ofrece_la_descarga() -> None:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert 'href="/download/faro-puente.apk"' in html
