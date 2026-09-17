"""KAN-108 — Pruebas de la pestaña de evolución en el portal."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_portal_tiene_pestana_de_evolucion() -> None:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert 'data-view="evolution-view"' in html
    assert 'id="evolution"' in html
    assert 'id="evolution-summary"' in html
    script = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    assert "/v1/cognitive-exercises/evolution" in script
    assert "renderEvolution" in script
