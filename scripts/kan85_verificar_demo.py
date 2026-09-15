"""KAN-85 — Verifica que lo que se va a mostrar en la demo del 1 de octubre funciona.

Uso:
    python scripts/kan85_verificar_demo.py

Comprueba, contra produccion (CloudFront), el portal, la salud del backend, la
version con sus funcionalidades y las tres descargas de APK (peticion parcial
para no bajar el APK grande). No necesita token.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

BASE = "https://d2n7ih9kfxbzvd.cloudfront.net"
TIMEOUT = 20

FEATURES_REQUERIDAS = [
    "family_conversation",
    "family_ai",
    "location_tracking",
    "family_alerts",
    "care_network_management",
    "events",
]

COMPROBACIONES = [
    {"id": "portal", "path": "/", "tipo": "html", "descripcion": "Portal Faro Familia carga"},
    {"id": "salud", "path": "/health", "tipo": "json", "descripcion": "Backend operativo (status ok)"},
    {"id": "version", "path": "/v1/version", "tipo": "json", "descripcion": "Funciones de la demo presentes"},
    {"id": "assetlinks", "path": "/.well-known/assetlinks.json", "tipo": "json", "descripcion": "TWA enlazada (a pantalla completa)"},
    {"id": "apk-faro-familia", "path": "/download/faro.apk", "tipo": "archivo", "descripcion": "Descarga Faro Familia"},
    {"id": "apk-camera-access", "path": "/download/camera-access.apk", "tipo": "archivo", "descripcion": "Descarga App gafas (Camera Access)"},
    {"id": "apk-faro-movil", "path": "/download/faro-movil.apk", "tipo": "archivo", "descripcion": "Descarga Faro Movil"},
]


def _peticion(path: str, headers: dict | None = None):
    req = urllib.request.Request(
        BASE + path,
        headers={"User-Agent": "faro-kan85-verificador", **(headers or {})},
    )
    return urllib.request.urlopen(req, timeout=TIMEOUT)


def _texto(resp, limite: int = 200_000) -> str:
    return resp.read(limite).decode("utf-8", errors="replace")


def comprobar_html(comprobacion: dict) -> str:
    with _peticion(comprobacion["path"]) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status}")
        cuerpo = _texto(resp)
    if "Faro Familia" not in cuerpo:
        raise RuntimeError("no aparece 'Faro Familia' en el portal")
    return "200 · 'Faro Familia' presente"


def comprobar_json(comprobacion: dict) -> str:
    with _peticion(comprobacion["path"]) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status}")
        datos = json.loads(_texto(resp))
    if comprobacion["id"] == "salud":
        if datos.get("status") != "ok":
            raise RuntimeError(f"status={datos.get('status')!r}")
        proveedor = str(datos.get("alert_provider", ""))
        if "WhatsApp" not in proveedor:
            raise RuntimeError(f"proveedor de avisos inesperado: {proveedor!r}")
        return f"status ok · avisos: {proveedor}"
    if comprobacion["id"] == "version":
        features = set(datos.get("features", {}))
        faltan = [f for f in FEATURES_REQUERIDAS if f not in features]
        if faltan:
            raise RuntimeError("faltan funciones: " + ", ".join(faltan))
        return f"{len(FEATURES_REQUERIDAS)} funciones clave presentes"
    return "200 · JSON valido"


def comprobar_archivo(comprobacion: dict) -> str:
    with _peticion(comprobacion["path"], headers={"Range": "bytes=0-0"}) as resp:
        estado = resp.status
        rango = resp.headers.get("Content-Range", "")
        largo = int(resp.headers.get("Content-Length", "0") or 0)
    if estado not in (200, 206):
        raise RuntimeError(f"HTTP {estado}")
    if "/" in rango:
        total = int(rango.rsplit("/", 1)[-1])
    else:
        total = largo
    if total < 1_000_000:
        raise RuntimeError(f"tamano inesperado: {total} bytes")
    return f"{estado} · {total / 1_000_000:.1f} MB"


COMPROBADORES = {"html": comprobar_html, "json": comprobar_json, "archivo": comprobar_archivo}


def main() -> int:
    print("== KAN-85 · verificacion de la demo (1 de octubre) ==")
    fallos = 0
    for comprobacion in COMPROBACIONES:
        try:
            detalle = COMPROBADORES[comprobacion["tipo"]](comprobacion)
            estado = "OK"
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, RuntimeError, ValueError) as error:
            detalle = str(error)[:100]
            estado = "FALLO"
            fallos += 1
        print(f"[{estado:5}] {comprobacion['id']}: {comprobacion['descripcion']} -> {detalle}")
    if fallos:
        print(f"\n{fallos} comprobacion(es) han fallado: revisa antes de la demo.")
        return 1
    print("\nTODO OK: lo verificado automaticamente funciona.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
