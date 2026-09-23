"""El proveedor de WhatsApp debe construir y enviar la plantilla sin errores (regresión NameError)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402


class _Contact:
    phone_e164 = "+34600000000"
    display_name = "Bibiana"


@pytest.mark.parametrize("kind", ["reminder", "hazard", "episode", "lost"])
def test_provider_sends_template(kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = main.MetaWhatsAppProvider("0", "token", "faro_emergency_alert")
    payloads: list[bytes] = []

    def fake_post(payload: bytes) -> dict:
        payloads.append(payload)
        return {"messages": [{"id": "wamid.1"}]}

    monkeypatch.setattr(provider, "_post_json", fake_post)
    alert = main.EmergencyAlertCreate(
        kind=kind, spoken_message="Mensaje de prueba", explicit_help_request=False,
        latitude=42.0, longitude=-8.0,
    )
    delivery = provider.send(_Contact(), alert)
    assert delivery.message_id == "wamid.1"
    assert payloads  # se construyó al menos un payload
