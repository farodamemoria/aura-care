# KAN-35 — Escucha ambiental inteligente y escalado (evidencia local)

Fecha: 2026-09-14. Alcance: backend `aura-care` (motor determinista + endpoints).

## Qué se ha implementado

Motor puro y determinista `app/environmental_listening.py`:

- Catálogo ampliable de señales acústicas (`cough`, `choking`, `fall`, `groan`, `cry`, `shout`).
- Umbrales configurables: ventana de repetición, número mínimo de detecciones,
  confianza mínima, tiempo de espera de respuesta, reintentos limitados y enfriamiento.
- Estado de diálogo: `listening` → `awaiting_response` → `reassured` | `escalated`.
- Una sola pregunta de comprobación («¿Estás bien?») ante patrón repetido; una tos
  aislada no interviene.
- Escalado por petición de ayuda, persistencia de la señal o falta de respuesta,
  con mensaje prudente («posible …»), sin diagnósticos.

Integración en `app/main.py`:

- `POST /v1/acoustic-events` — reporta una detección y devuelve la siguiente acción.
- `POST /v1/acoustic-events/response` — respuesta del paciente a la comprobación.
- `POST /v1/acoustic-events/tick` — avanza la lógica temporal (timeout/reintento).
- `GET /v1/acoustic-episodes` — episodio activo e histórico.
- Los episodios se registran en la línea de tiempo (`events`) y el escalado envía
  aviso a la red de cuidados (`enabled_alert_contacts`) con deduplicación de 10 min.

## Pruebas (Q&A)

`tests/test_environmental_listening.py` (22) y `tests/test_acoustic_endpoints.py` (7).
Suite completa del repo: **59 PASS**.

Cubren los criterios de aceptación 1–5: tos aislada sin aviso; secuencia repetida →
una sola pregunta; respuesta tranquilizadora detiene y registra sin avisar; ayuda,
persistencia o falta de respuesta escalan; sin diagnósticos; casos de ruido/falsa
alarma (baja confianza, fuera de ventana, enfriamiento).

## Pendiente (requiere hardware/onda real)

- Criterio 6: pruebas con **audio grabado real** y ruido ambiental (el motor se ha
  probado con detecciones simuladas).
- Criterio 7: consumo de batería y comportamiento con pantalla apagada (app Android).
- Captura/streaming de audio en las gafas (integración con `AudioInputHandler`).
