"""KAN-178/KAN-208 - Puente del ojo de Faro (camara Tapo conectada al movil/casa).

Atiende DOS cosas con un solo consumidor (sin duplicar capturas ni gasto de IA):
- Captura BAJO DEMANDA: el familiar pulsa "Ver ahora" en el portal -> el backend
  devuelve la peticion y este puente sube una foto.
- VIGILANCIA (KAN-208): si la patrulla esta activa, el backend pide una foto cada
  `interval_seconds`. El puente compara con el fotograma anterior y solo deja que
  el backend analice cuando la escena cambia; una caida al suelo es un cambio
  grande y dispara el aviso a la familia. Si la escena esta quieta no se gasta IA.

Uso:
  python scripts/camera_eye_bridge.py --rtsp rtsp://user:pass@ip:554/stream1 \
      --backend https://api.loginea.com --token <AURA_LOCAL_TOKEN>

Variables de entorno equivalentes: TAPO_RTSP_URL, FARO_BACKEND, FARO_TOKEN.
Opcional: --interval (segundos entre consultas, por defecto 2.5), --motion-threshold
(diferencia media 0-255 para considerar que la escena cambio, por defecto 4.0) y
--once (captura y sube una sola foto, sin bucle).
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def ffmpeg_path() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return "ffmpeg"


def capture_frame(rtsp_url: str) -> bytes | None:
    """Un unico fotograma JPEG del RTSP (sin dejar la camara abierta en bucle)."""
    with tempfile.TemporaryDirectory() as folder:
        output = Path(folder) / "ojo.jpg"
        command = [ffmpeg_path(), "-y", "-loglevel", "error"]
        if rtsp_url.lower().startswith("rtsp://"):
            command += ["-rtsp_transport", "tcp"]
        command += [
            "-i", rtsp_url, "-frames:v", "1", "-q:v", "3", str(output),
        ]
        try:
            subprocess.run(command, timeout=45, capture_output=True)
        except Exception:  # noqa: BLE001
            return None
        if not output.exists() or output.stat().st_size < 1024:
            return None
        return output.read_bytes()


def frame_signature(jpeg: bytes) -> bytes | None:
    """Huella barata del fotograma (64x48 en gris) para detectar cambios de escena."""
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001
        return None
    try:
        with Image.open(io.BytesIO(jpeg)) as image:
            return image.convert("L").resize((64, 48)).tobytes()
    except Exception:  # noqa: BLE001
        return None


def scene_changed(previous: bytes | None, current: bytes | None, threshold: float) -> bool:
    """True si la escena cambio (o no se puede medir: mejor analizar de mas que perder una caida)."""
    if previous is None or current is None or len(previous) != len(current):
        return True
    if threshold <= 0:
        return True
    difference = sum(abs(a - b) for a, b in zip(previous, current)) / len(current)
    return difference >= threshold


def send_json(backend: str, token: str, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        backend.rstrip("/") + path, data=data, method=method,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as error:
        return error.code, {}


def pending_capture(backend: str, token: str) -> dict | None:
    status, body = send_json(backend, token, "GET", "/v1/camera/capture")
    if status == 204:
        return None
    if status != 200:
        raise RuntimeError(f"capture request failed: HTTP {status}")
    return body or None


def upload_frame(
    backend: str, token: str, jpeg: bytes, request_id: str | None = None,
    reason: str = "demand", changed: bool | None = None,
) -> dict:
    body = {
        "image_base64": base64.b64encode(jpeg).decode("ascii"),
        "mime_type": "image/jpeg",
        "reason": "watch" if reason == "watch" else "demand",
    }
    if request_id:
        body["request_id"] = request_id
    if changed is not None:
        body["changed"] = changed
    status, result = send_json(backend, token, "POST", "/v1/camera/frame", body)
    if status != 200:
        raise RuntimeError(f"frame upload failed: HTTP {status}")
    return result


def describe(result: dict) -> str:
    if result.get("skipped") == "no_change":
        return "Sin cambios en la escena (no se gasta IA)."
    if result.get("skipped"):
        return f"IA pausada: {result['skipped']}"
    if result.get("hazard"):
        return f"PELIGRO {result.get('kind')}: {result.get('description')}"
    return f"Reconocido: {result.get('description')}"


def last_frame_at(args: argparse.Namespace) -> str | None:
    status, body = send_json(args.backend, args.token, "GET", "/v1/camera/status")
    if status != 200:
        return None
    return body.get("last_frame_at")


def capture_once(
    args: argparse.Namespace, request_id: str | None = None, reason: str = "demand",
) -> bool:
    jpeg = capture_frame(args.rtsp)
    if not jpeg:
        print("Sin fotograma de la camara.", flush=True)
        return False
    signature = frame_signature(jpeg)
    previous = getattr(args, "last_signature", None)
    changed = scene_changed(previous, signature, args.motion_threshold)
    if previous is None and signature is not None:
        # El primer fotograma solo sirve de referencia; se analiza igualmente.
        args.last_signature = signature
    before = last_frame_at(args)
    try:
        result = upload_frame(args.backend, args.token, jpeg, request_id, reason, changed)
        print(describe(result), flush=True)
        if changed and signature is not None:
            args.last_signature = signature
        return True
    except Exception as error:  # noqa: BLE001
        # El gateway puede cortar la respuesta (504) aunque el backend termine el
        # analisis: se comprueba si el ojo ya tiene una imagen nueva antes de fallar.
        for _ in range(20):
            time.sleep(3)
            current = last_frame_at(args)
            if current and current != before:
                status, body = send_json(args.backend, args.token, "GET", "/v1/camera/status")
                print(f"Reconocido (el gateway corto la respuesta): {body.get('description')}", flush=True)
                return True
        print(f"Error subiendo el fotograma: {error}", flush=True)
        return False


def demand_loop(args: argparse.Namespace) -> None:
    print(
        f"Ojo activo: {args.backend} (bajo demanda + vigilancia; sin captura continua)",
        flush=True,
    )
    handled: str | None = None
    while True:
        try:
            pending = pending_capture(args.backend, args.token)
        except Exception as error:  # noqa: BLE001
            print(f"No pude consultar la captura: {error}", flush=True)
            pending = None
        if pending and pending.get("request_id") and pending["request_id"] != handled:
            handled = str(pending["request_id"])
            reason = "watch" if pending.get("reason") == "watch" else "demand"
            label = "Vigilancia" if reason == "watch" else "Captura pedida"
            print(f"{label} ({handled[:8]}): abro la camara y subo una foto", flush=True)
            try:
                capture_once(args, handled, reason)
            except Exception as error:  # noqa: BLE001
                print(f"Error capturando: {error}", flush=True)
        time.sleep(max(1.0, args.interval))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Puente del ojo de Faro (Tapo RTSP)")
    parser.add_argument("--rtsp", default=os.getenv("TAPO_RTSP_URL", ""))
    parser.add_argument("--backend", default=os.getenv("FARO_BACKEND", "https://api.loginea.com"))
    parser.add_argument("--token", default=os.getenv("FARO_TOKEN", ""))
    parser.add_argument("--interval", type=float, default=2.5)
    parser.add_argument(
        "--motion-threshold", type=float,
        default=float(os.getenv("FARO_MOTION_THRESHOLD", "4.0")),
        help="Diferencia media (0-255) para considerar que la escena cambio; 0 analiza siempre",
    )
    parser.add_argument("--once", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if not args.rtsp or not args.token:
        print("Faltan --rtsp o --token (o TAPO_RTSP_URL / FARO_TOKEN).", flush=True)
        return 2
    if args.once:
        return 0 if capture_once(args) else 1
    try:
        demand_loop(args)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
