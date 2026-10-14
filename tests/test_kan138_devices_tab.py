"""KAN-138 - pestana especifica de dispositivos y servicios."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _html() -> str:
    return (ROOT / "web" / "index.html").read_text(encoding="utf-8")


def test_pestana_de_dispositivos_existe() -> None:
    html = _html()
    assert 'id="tab-devices"' in html
    assert 'data-view="devices-view"' in html
    assert 'id="devices-view"' in html


def test_el_contenedor_de_dispositivos_vive_en_la_pestana() -> None:
    html = _html()
    section_start = html.index('id="devices-view"')
    section = html[section_start : html.index("</section>", section_start)]
    assert 'id="devices"' in section
    assert "Dispositivos y servicios" in section


def test_ya_no_hay_bloque_suelto_bajo_el_resumen() -> None:
    assert 'class="reveal devices-panel"' not in _html()


def test_cache_actualizada() -> None:
    sw = (ROOT / "web" / "assets" / "sw.js").read_text(encoding="utf-8")
    cache = re.search(r"faro-familia-v(\d+)", sw)
    assert cache and int(cache.group(1)) >= 54
