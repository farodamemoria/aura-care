"""KAN-115 — Foto de la persona vinculada en las fichas de cuidados."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_ficha_de_cuidados_muestra_la_foto() -> None:
    script = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    assert "profile-photo" in script
    seccion = script.split("function renderCareContacts")[1].split("function ")[0]
    assert "profile-photo" in seccion
    assert "avatar" in seccion
    assert "known_person_id" in seccion
