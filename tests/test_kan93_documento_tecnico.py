"""KAN-93 — Casos de uso / pruebas del documento técnico (sin red).

Comprueban que el documento cubre todos los endpoints reales de `app/main.py`,
que referencia ficheros que existen, que menciona el stack y los proveedores, y
que datos como la caché del service worker no se quedan desactualizados.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DOC_PATH = ROOT / "docs" / "kan93-documento-tecnico.md"
MAIN_PATH = ROOT / "app" / "main.py"
SW_PATH = ROOT / "web" / "assets" / "sw.js"

FICHEROS_REFERENCIADOS = [
    "app/main.py",
    "app/environmental_listening.py",
    "web/index.html",
    "web/assets/app.js",
    "web/assets/sw.js",
    "web/assets/manifest.webmanifest",
    "Dockerfile",
    "requirements.txt",
]

TERMINOS_OBLIGATORIOS = [
    "FastAPI",
    "uvicorn",
    "SQLite",
    "AURA Care",
    "Rekognition",
    "faro-faces",
    "CloudFront",
    "Meta Wearables",
    "mwdat",
    "LifeSense",
    "WhatsApp",
    "faro_emergency_alert",
    "aura-backend",
    "lifesense-api",
    "faro-realtime",
    "aura-care",
    "android",
]


def _documento() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_documento_tiene_secciones_obligatorias() -> None:
    documento = _documento()
    for titulo in (
        "## 0. Mapa de componentes",
        "## 1. Arquitectura general",
        "## 2. Backend AURA Care",
        "## 3. Portal Faro Familia",
        "## 4. App de gafas",
        "## 5. LifeSense API",
        "## 8. Infraestructura y despliegue",
        "## 9. Seguridad, privacidad y datos",
        "## 10. Flujo de trabajo del código",
    ):
        assert titulo in documento


def test_cubre_todos_los_endpoints_reales() -> None:
    documento = _documento()
    codigo = MAIN_PATH.read_text(encoding="utf-8")
    rutas = sorted(set(re.findall(r'@app\.(?:get|post|patch|put|delete)\("([^"]+)"', codigo)))
    assert len(rutas) >= 45
    for ruta in rutas:
        assert ruta in documento, f"endpoint sin documentar: {ruta}"


def test_referencia_ficheros_que_existen() -> None:
    documento = _documento()
    for relativo in FICHEROS_REFERENCIADOS:
        assert f"`{relativo}`" in documento
        assert (ROOT / relativo).is_file(), f"el documento referencia un fichero inexistente: {relativo}"


def test_menciona_stack_y_proveedores() -> None:
    documento = _documento()
    for termino in TERMINOS_OBLIGATORIOS:
        assert termino in documento, f"falta mencionar: {termino}"


def test_descargas_de_apk_documentadas() -> None:
    documento = _documento()
    rutas = ["/download/faro.apk", "/download/camera-access.apk", "/download/faro-movil.apk", "/download/faro-familia.apk"]
    for ruta in rutas:
        assert ruta in documento


def test_cache_pwa_coincide_con_el_service_worker() -> None:
    documento = _documento()
    sw = SW_PATH.read_text(encoding="utf-8")
    cache = re.search(r"const CACHE='([^']+)'", sw)
    assert cache is not None
    assert f"`{cache.group(1)}`" in documento, "la caché del service worker cambió y el documento no se actualizó"


def test_menciona_autenticacion_y_kang31() -> None:
    documento = _documento()
    assert "AURA_LOCAL_TOKEN" in documento
    assert "KAN-31" in documento
