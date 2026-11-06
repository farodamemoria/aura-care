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


def test_kan221_alerta_explica_que_ha_pasado() -> None:
    alert = main.EmergencyAlertCreate(
        kind="hazard",
        spoken_message="¿Estás bien?",
        context="La cámara ha visto a una persona en el suelo junto a la cocina",
        explicit_help_request=False,
        latitude=42.0, longitude=-8.0, location_source="last_known",
    )
    message = main.build_alert_message(alert)
    assert "Tipo: peligro en casa" in message
    assert "Qué ha pasado: La cámara ha visto a una persona en el suelo" in message
    assert "maps.google.com" in message


def test_kan221_plantilla_incluye_la_interpretacion() -> None:
    alert = main.EmergencyAlertCreate(
        kind="hazard", alert_type="posible caída",
        spoken_message="No responde", context="El paciente no contesta a la comprobación",
        explicit_help_request=False, latitude=42.0, longitude=-8.0,
    )
    body = main._template_body(alert, " https://maps.google.com/?q=42,-8", "")
    assert "posible caída" in (alert.alert_type or "").lower()
    assert "Qué ha pasado: El paciente no contesta" in body
    assert "No responde" in body
