# KAN-35 — Registro de verificación (2026-10-31)

Máquina: DESKTOP-SDQ1TSF (portátil) · Python 3.13 · `aura-care` (rama `main`, cambios sin commit).

## 1. Audio real con el micrófono del PC

Capturas con `sounddevice` (16 kHz, mono, PCM 16 bits) en `docs/kan35-evidencia/`:

| Fichero | Dur. | SHA-256 |
|---|---|---|
| `ambiente-pc-real.wav` | 8,0 s | `D57B3625A17282D40F500C9043218CC4D96991322F95F250357F555309BCB595` |
| `golpes-pc-real.wav` | 7,0 s | `4848DB9363FFB553A1901605CF9FA3608A3B239A5C7A002BCD95C0882F6AAB1D` |
| `toses-sobre-ambiente-real.wav` | 8,0 s | `8CDF07704DD234A897B59D46FB030A400E8945CF414F60358EB74714E4E0D862` |

Resultado con `app.acoustic_audio.analyze_wav` + `feed_engine`:

- `ambiente-pc-real.wav`: 1 evento (`cough`, 0,97, −2,16 dBFS) → `listening`; sin pregunta.
- `golpes-pc-real.wav`: 0 eventos tras `min_peak_dbfs = −30 dBFS` (antes: 2 falsos
  positivos a −32 y −41 dBFS).
- `toses-sobre-ambiente-real.wav`: 3 `cough` → una sola pregunta y episodio
  `awaiting_response`.

## 2. HTTP real (uvicorn local)

`python -m uvicorn app.main:app --port 8101/8102` con `AURA_LOCAL_TOKEN` y
`curl --data-binary @wav`:

```
POST /v1/acoustic-audio ambiente-pc-real.wav        -> HTTP 200; results [listening]
POST /v1/acoustic-audio toses-sobre-ambiente-real   -> HTTP 200; listening, listening, ask, recorded
POST /v1/acoustic-audio sin Authorization           -> HTTP 401
POST /v1/acoustic-audio "no soy un wav"             -> HTTP 400 WAV no válido
GET  /v1/acoustic-episodes                          -> awaiting_response (tos)
POST /v1/acoustic-audio caida-sintetica.wav         -> HTTP 200; ask (reason immediate)
POST /v1/acoustic-events/tick (16 s)                -> ask (retry)
POST /v1/acoustic-events/tick (32 s)                -> escalate (no_response); evento hazard
GET  /v1/events?kind=hazard                         -> "Faro: posible golpe o caída; ..."
```

`alert.status = no_contact` porque el repositorio en memoria del servidor de prueba no
tiene contactos de cuidados (comportamiento esperado).

## 3. Tests

```
python -m pytest -q
358 passed, 2 warnings in 26.77s
```

Específicos: `test_acoustic_audio.py` (13), `test_acoustic_audio_endpoint.py` (7),
`test_environmental_listening.py` (22), `test_acoustic_endpoints.py` (7) → 49.

## 4. Criterio 7 (bloqueado)

```
adb devices -l
9THAC67T75LJIZDE  device product:fleur_eea model:2201117SY device:fleur transport_id:1
# el Pixel 9 Pro 53221FDAP002QF aparecía al inicio y se desconectó a mitad de la sesión

adb -s 9THAC67T75LJIZDE install -r app-debug.apk
Failure [INSTALL_FAILED_USER_RESTRICTED: Install canceled by user]   # MIUI

adb connect 192.168.1.114:5555  -> rechazado (10061)
barrido TCP 192.168.1.0/24:5555 -> ningún host
adb connect 192.168.1.48:5555   -> rechazado (10061)
```

APK de prueba compilada con `AURA_BACKEND_URL=http://192.168.1.136:8103` y token local:
`.../samples/CameraAccess/app/build/outputs/apk/debug/app-debug.apk` (BUILD SUCCESSFUL in 1m 8s).

## 5. Servidor de prueba

Tarea programada `KAN35Backend` → `uvicorn` en `0.0.0.0:8103`; accesible desde la LAN
(`nc` desde el Redmi devolvió `HTTP/1.1 200 OK`).
