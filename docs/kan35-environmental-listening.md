# KAN-35 — Escucha ambiental inteligente y escalado (evidencia)

Fecha: 2026-09-14 (motor) / 2026-10-30 (audio real) / 2026-10-31 (verificación y bloqueo).
Alcance: backend `aura-care` + app Android `AmbientListeningService`.

## Qué se ha implementado

Motor puro y determinista `app/environmental_listening.py`:

- Catálogo ampliable de señales acústicas (`cough`, `choking`, `fall`, `groan`, `cry`, `shout`).
- Umbrales configurables: ventana de repetición, número mínimo de detecciones,
  confianza mínima, tiempo de espera de respuesta, reintentos limitados y enfriamiento.
- Estado de diálogo: `listening` → `awaiting_response` → `reassured` | `escalated`.
- Una sola pregunta de comprobación («¿Estás bien?») ante patrón repetido; una tos
  aislada no interviene. Una caída (`fall`) se comprueba al momento (`reason: immediate`).
- Escalado por petición de ayuda, persistencia de la señal o falta de respuesta,
  con mensaje prudente («posible …»), sin diagnósticos.

Analizador de audio `app/acoustic_audio.py` (criterio 6):

- Decodifica WAV PCM (8/16/24/32 bits, mono o estéreo, cualquier frecuencia), sin
  dependencias externas.
- Enventana (32 ms / salto 16 ms), calcula RMS, cresta, cruces por cero, bandas
  espectrales, centroide y tonalidad con una FFT radix-2 propia.
- Umbral adaptativo por percentil del ruido de fondo y separación de golpes dentro
  de un fondo activo, para que una tos sobre ruido ambiental no se pierda ni se
  cuente dos veces.
- Umbral absoluto `min_peak_dbfs = −30 dBFS`: descarta clics y transitorios casi
  inaudibles que antes se colaban como eventos.
- Clasificación conservadora: el ruido blanco fuerte y la conversación/televisión
  continua no generan detecciones.
- `feed_engine()` inyecta los eventos en el mismo motor que usan los endpoints.

Integración en `app/main.py`:

- `POST /v1/acoustic-events` — reporta una detección y devuelve la siguiente acción.
- `POST /v1/acoustic-events/response` — respuesta del paciente a la comprobación.
- `POST /v1/acoustic-events/tick` — avanza la lógica temporal (timeout/reintento).
- `POST /v1/acoustic-audio` — sube un WAV, lo analiza y ejecuta el motor.
- `GET /v1/acoustic-episodes` — episodio activo e histórico.
- Los episodios se registran en la línea de tiempo (`events`) y el escalado envía
  aviso a la red de cuidados (`enabled_alert_contacts`) con deduplicación de 10 min.

## Pruebas (Q&A) — criterio 6

Audio real:

- `tests/fixtures/audio/ambiente-sala-real.wav`: ambiente de sala (6 s, 16 kHz mono)
  versionado como fixture. El analizador no emite ninguna detección.
- Mezcla de esa misma grabación con tres toses sintéticas: se emite una única
  pregunta de comprobación.
- `docs/kan35-evidencia/ambiente-pc-real.wav`: captura real del micrófono del PC
  (8 s, 16 kHz mono, SHA-256 `D57B3625A17282D40F500C9043218CC4D96991322F95F250357F555309BCB595`).
  Un transitorio fuerte aislado (`cough` 0,97 a −2,16 dBFS) deja el motor en
  `listening`: un sonido aislado no interrumpe.
- `docs/kan35-evidencia/toses-sobre-ambiente-real.wav`: la captura real anterior con
  tres toses mezcladas → una sola pregunta y episodio `awaiting_response`.
- Antes de añadir `min_peak_dbfs`, `docs/kan35-evidencia/golpes-pc-real.wav` generaba
  detecciones espurias de `cough` a −32 y −41 dBFS; ahora 0. Regresión cubierta por
  `test_very_quiet_transients_are_not_events`.

Audio sintético determinista (`tests/fixtures/audio/generate_fixtures.py`):

- `tos-repetida-sintetica.wav` → 3 detecciones `cough` → una sola pregunta.
- `tos-aislada-sintetica.wav` → 1 detección → sin intervención.
- `ruido-blanco-fuerte.wav` → 0 detecciones (falsa alarma descartada).
- `television-fondo-sintetica.wav` → 0 detecciones (falsa alarma descartada).
- `caida-sintetica.wav` → `fall` → pregunta inmediata.
- `grito-sintetico.wav` → `shout`; `llanto-sintetico.wav` → `cry`.

Suites:

- `tests/test_acoustic_audio.py` (13) y `tests/test_acoustic_audio_endpoint.py` (7).
- `tests/test_environmental_listening.py` (22) y `tests/test_acoustic_endpoints.py` (7).
- Suite completa del repo: **358 PASS** (2026-10-31).

Prueba HTTP real (uvicorn local, token `AURA_LOCAL_TOKEN`):

- `POST /v1/acoustic-audio` con `ambiente-pc-real.wav` → **200**, 1 evento, `listening`.
- Con `toses-sobre-ambiente-real.wav` → **200**, 3 `cough`: `listening`, `listening`,
  `ask` («¿Estás bien?») y `recorded`; `GET /v1/acoustic-episodes` → `awaiting_response`.
- Sin token → **401**; WAV inválido → **400**.
- `caida-sintetica.wav` → **200**, `ask` inmediato (`reason: immediate`); `tick` a los
  16 s → `ask` (`retry`); `tick` a los 32 s → `escalate` (`no_response`) con evento
  `hazard` en `GET /v1/events`. Con el repositorio en memoria sin contactos,
  `alert.status = no_contact` (esperado).

## App de Android (escucha en segundo plano)

`AmbientListeningService` (servicio en primer plano tipo `microphone`, `PARTIAL_WAKE_LOCK`
de 60 min, pregunta por TTS y respuesta con `SpeechRecognizer`, sin guardar audio) vive en
la copia local usada para construir la APK instalada
(`meta-wearables-dat-android-main/.../samples/CameraAccess`), que **no está bajo control de
versiones**; el repo `android` todavía no la contiene.

## Pendiente (bloqueo físico, 2026-10-31)

- Criterio 7: consumo de batería y comportamiento con pantalla apagada.
  - Quest 2 (`1WMHHA62SR1471`): no aparece en `adb devices`; `adb connect
    192.168.1.114:5555` rechazado y ningún host de la LAN acepta el puerto 5555.
  - Pixel 9 Pro (`53221FDAP002QF`, con la app de gafas instalada): se desconectó a mitad
    de la sesión (sí aparecía al empezar).
  - Redmi (`9THAC67T75LJIZDE`, Android 13): la instalación por adb la rechaza MIUI
    (`INSTALL_FAILED_USER_RESTRICTED`; requiere activar «Instalar por USB» con cuenta Mi).
  - APK de prueba ya compilada (`app-debug.apk`, `AURA_BACKEND_URL=http://192.168.1.136:8103`,
    token local, sin tocar producción): la prueba se reanuda en cuanto haya un dispositivo
    disponible.
- Captura/streaming de audio en la app de las gafas: el backend ya acepta WAV en
  `POST /v1/acoustic-audio`; falta que la app envíe los segmentos.
