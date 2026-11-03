# KAN-82 — Selección de hardware abierto para Faro (cámara + voz Home Assistant + pulsera de ubicación)

Fecha: 2026-11-03. Autor: opencode. Presupuesto objetivo fijado por Leonardo: **~50 EUR por pieza**
(comentario del 15/10/2026). Criterio transversal: **SDK/protocolo abierto y sin nube propietaria
obligatoria**, porque el cerebro sigue siendo `aura-backend` (STT + LLM + TTS) y los datos del
paciente no deben salir a un proveedor cerrado.

## 1. Decisión en una tabla

| Pieza | Decisión | Precio verificado | SDK / protocolo abierto |
|---|---|---|---|
| Cámara fija | **TP-Link Tapo C210** (ya desplegada como «Ojo de Faro») | 39,99 EUR PVP; 25–30 EUR en oferta | RTSP + ONVIF locales; sin SDK propietario necesario |
| Voz / puente | **Home Assistant** (PC nuevo o Raspberry Pi) + **HA Voice PE** | HA: 0 EUR · Voice PE: **59 EUR** | ESPHome (firmware/hardware abiertos), API Assist/REST |
| Voz económica | **M5Stack Atom Echo** | ~15–20 EUR | ESPHome |
| **Pulsera de ubicación** | **LILYGO T-A7670E R2 con GPS** (módulo wearable en bolsa de cinturón) | **32,89 USD (~30 EUR)** | Ejemplos **MIT** (`LilyGo-Modem-Series`), ESP32 + LTE Cat-1 + GNSS, MQTT/HTTP propios |
| Anclas indoor | **2–3x ESP32 (LILYGO T7 Mini32 V1.5)** con ESPHome `bluetooth_proxy` | **7,44 USD/u** | ESPHome (build verificado, ver §6) |
| Pulsera solo-wrist (fase 2) | **PineTime** | **26,99 USD** | InfiniTime **GPL-3.0**, BLE estándar |
| Alternativa comercial | Traccar + tracker compatible | 30–50 EUR | Servidor **Apache-2.0**, protocolo abierto |

**Compra recomendada para el primer prototipo (≈47 EUR, dentro del objetivo):**
1x T-A7670E R2 **con GPS** (32,89 USD) + 1x batería 18650 y bolsa/carcasa (≈6 EUR) + 2x T7 Mini32
(14,88 USD). Total ≈ 47,77 USD + 6 EUR ≈ **47 EUR**. SIM IoT aparte (3–5 EUR/mes). La voz y la
cámara ya están cubiertas por lo desplegado.

## 2. Cámara — Tapo C210 (confirmada)

- Ficha oficial ES (200 OK): https://www.tp-link.com/es/home-networking/cloud-camera/tapo-c210/
  — «Cámara de Vigilancia Wi-Fi de 360 Grados con Vista 2K 3MP», menciona RTSP y ONVIF.
- Ya está integrada y probada en producción (KAN-178): `POST /v1/camera/capture` → puente RTSP
  (192.168.1.47, `farocam`) → fotograma 2304×1296 → Gemini → preview y tarjeta en el portal.
- No hace falta SDK: el contrato es RTSP/ONVIF + nuestro backend. Axis (VAPIX/ACAP) es la evolución
  profesional (>150 EUR), fuera de presupuesto para el piloto.

## 3. Voz y Home Assistant (confirmado)

- HA es **software** (PC nuevo `100.114.6.14` o Raspberry Pi); no es hardware que comprar.
- HA Voice PE: página oficial 200 OK, precio mostrado **$69 / 59 €**, ESPHome, microWakeWord, XMOS.
  https://www.home-assistant.io/voice-pe/
- El agente de conversación es nuestro backend: se expone un endpoint compatible OpenAI
  (`/v1/chat/completions`) o un componente custom de HA. STT/TTS pueden ser los nuestros.
- Palabra de activación «Faro»: hay que entrenar un modelo microWakeWord (no viene de fábrica).

## 4. Pulsera de ubicación del paciente — decisión nueva

### 4.1 Requisitos reales (Alzheimer/demencia)

1. Localización **en interior** (el GPS no vale dentro de casa; la fuga típica empieza en casa).
2. Localización **en exterior** con geocerca y aviso al cuidador.
3. Autonomía de al menos un día; carga sencilla.
4. Botón SOS y, deseable, detección de caída.
5. **SDK abierto**: poder cambiar el servidor de destino, sin cuenta ni nube del fabricante.
6. Datos en nuestro backend (GDPR: dato de salud + localización).
7. Coste ~50 EUR, sin cuotas abusivas.

### 4.2 Opciones evaluadas y por qué se descartan

| Opción | Motivo de descarte |
|---|---|
| Apple AirTag | Sin SDK público, MAC aleatoria anti-seguimiento, sin GPS propio, depende de iPhone cerca |
| Samsung SmartTag / Tile | Nube del fabricante, sin API pública de localización |
| Relojes infantiles LTE baratos (Qbit/Wonlex/Q19…) | Firmware y nube del vendedor; muchos no permiten cambiar el servidor; seguridad dudosa |
| LoRaWAN (SenseCAP T1000-E, etc.) | Necesita gateway LoRaWAN (150–300 EUR) y cobertura; no encaja en casa |
| Traccar + tracker comercial | Válido (servidor Apache-2.0), pero el dispositivo sigue siendo caja negra; se deja como plan B |

### 4.3 Decisión: LILYGO T-A7670E R2 **con GPS**

Es la única opción verificada que cumple SDK abierto + LTE + GNSS + BLE dentro de presupuesto.

- Producto: `T-A7670E/G/SA R2`, variante **«T-A7670E R2 With GPS»**, SKU Q334, **32,89 USD**.
  Incluye antena GPS, antena LTE y cable de alimentación; **no** incluye 18650 ni SIM.
- MCU: **ESP32-WROVER-E**, 4 MB flash + 8 MB PSRAM (BLE y Wi-Fi disponibles).
- Módem: **A7670E**, LTE-FDD **B1/B3/B5/B7/B8/B20** + GSM 900/1800 → válido en España/EU.
- GNSS integrado (variante GPS) + antena en la caja.
- Firmware abierto: repo `Xinyuan-LilyGO/LilyGo-Modem-Series`, licencia **MIT**, con ejemplos
  `DeviceTracker` (GNSS + HTTP POST a servidor propio), `GPS_BuiltIn`, `MqttClient`,
  `MqttsBuiltlnNoSSL`, `DeepSleep` y `ModemSleep`.
- Papel en la arquitectura:
  - **Interior**: el ESP32 emite beacon BLE (iBeacon) → 2–3 ESP32 con ESPHome `bluetooth_proxy`
    → HA + Bermuda calculan la **habitación** por RSSI.
  - **Exterior**: GNSS + LTE Cat-1 → MQTT/TLS a `aura-backend` y `device_tracker` MQTT de HA para
    geocerca y alertas.
  - **SOS**: botón físico a GPIO → mensaje prioritario al backend.
- Formato: no es una pulsera de muñeca; va en **bolsa de cinturón** o carcasa impresa. Si Leonardo
  exige muñeca, se añade **PineTime** (26,99 USD, InfiniTime GPL-3.0) como tag BLE y el T-A7670E
  queda en la mochila/bolsillo (total ~57 EUR, fase 2).

## 5. Arquitectura resultante

```
                 +---------------------- aura-backend (EC2) ----------------------+
                 |  STT + LLM + TTS  ·  /v1/camera/*  ·  ingesta /v1/location       |
                 +----^--------------------------^--------------------^-----------+
                      | MQTT/TLS                 | HTTPS snapshot      | Assist API
        +-------------+-----------+     +--------+---------+   +------+-----------+
        | T-A7670E (pulsera)      |     | Tapo C210        |   | HA + Voice PE    |
        | BLE beacon + GNSS + LTE |     | RTSP/ONVIF 2K    |   | ESPHome, AEC     |
        +------------+------------+     +------------------+   +------------------+
                     | BLE (interior)
        +------------v------------+
        | 2-3x ESP32 bluetooth_proxy | -> HA + Bermuda (habitación)
        +---------------------------+
```

- HA corre en el PC nuevo o en Raspberry Pi; el backend sigue siendo el cerebro.
- `device_tracker` MQTT de HA admite `source_type: gps`, `json_attributes_topic` y `state_topic`
  (documentación oficial verificada, 200 OK).
- Plan B si se prefiere producto acabado: servidor **Traccar** (Apache-2.0, 8.043★) + tracker
  compatible con su protocolo abierto.

## 6. Verificación ejecutada (2026-11-03)

| Comprobación | Comando / fuente | Resultado |
|---|---|---|
| Backend vivo | `GET https://api.loginea.com/health` | **200** `{"status":"ok","service":"aura-backend"...}` |
| Ficha Tapo C210 ES | `Invoke-WebRequest https://www.tp-link.com/es/home-networking/cloud-camera/tapo-c210/` | **200**, 210.162 B; título 2K 3MP 360; RTSP y ONVIF presentes |
| Precio T-A7670E R2 GPS | `GET https://www.lilygo.cc/products/t-sim-a7670e.json` | **32,89 USD** variante Q334 «With GPS»; caja con antenas GPS+LTE |
| Specs MCU/módem | `docs/en/esp32/a7670-esp32/README.MD` (repo) | ESP32-WROVER-E 4 MB/8 MB; LTE B1/B3/B5/B7/B8/B20 + GSM 900/1800 |
| Licencia/actividad SDK LilyGO | `GET api.github.com/repos/Xinyuan-LilyGO/LilyGo-Modem-Series` | **MIT**, 368★, último push **2026-11-02** |
| Ejemplos necesarios | `GET .../contents/examples` | `DeviceTracker`, `GPS_BuiltIn`, `MqttClient`, `DeepSleep`, `ModemSleep` presentes |
| Precio PineTime | `GET https://pine64.com/product/pinetime-smartwatch-sealed/` | **26,99 USD** |
| Licencia/actividad InfiniTime | `GET api.github.com/repos/InfiniTimeOrg/InfiniTime` | **GPL-3.0**, 3.414★, push **2026-11-03** |
| Precio XIAO ESP32C3 | `GET https://www.seeedstudio.com/Seeed-XIAO-ESP32C3-p-5431.html` | **4,90 USD** (no se elige: el build C3 falló por toolchain) |
| Precio ancla ESP32 | `GET https://www.lilygo.cc/products/t7-mini32-v1-5.json` | **7,44 USD**; ESP32 dual-core 240 MHz, 4 MB flash, PSRAM, BLE |
| Bermuda (trilateración HA) | repo `agittins/bermuda` | **MIT**, 2.126★, push **2026-10-20**; requiere ESPHome `bluetooth_proxy` |
| Traccar (plan B) | repo `traccar/traccar` | **Apache-2.0**, 8.043★, push **2026-11-03** |
| HA `device_tracker` MQTT | `https://www.home-assistant.io/integrations/device_tracker.mqtt/` | **200**; `source_type`, `json_attributes_topic`, `state_topic` |
| Config ESPHome del ancla | `esphome config faro-scanner-c3.yaml` | **Configuration is valid!** (exit 0) |
| Build real del ancla | `esphome compile` (ESP32-WROOM, ESPHome **2026.10.2**) | **Successfully compiled** · `firmware.factory.bin` 1.218.543 B (66,4 % flash, 34 % libre) |
| Config beacon del tag | `esphome config faro-tag-beacon.yaml` | **Configuration is valid!** (exit 0) |

Nota: el build para **ESP32-C3** falló en este portátil por un problema del toolchain RISC-V
(`bits/c++config.h` no encontrado), no por el YAML. Para no vender humo, la compra de anclas se
propone con **ESP32 (T7 Mini32 V1.5, clase WROOM)**, que sí compiló. Queda como pendiente reevaluar C3 (más pequeño y
barato) cuando se fije el toolchain en el PC nuevo.

## 7. Pendiente (bloqueo físico: hace falta comprar)

- Prueba en banco **no realizada**: no hay unidad física. Al recibirla: flashear `DeviceTracker` con
  MQTT a `aura-backend`, medir autonomía, probar geocerca y precisión indoor con 2–3 anclas.
- SIM IoT: contratar datos (3–5 EUR/mes); comprobar que la operadora mantiene LTE Cat-1 (B20) y el
  fallback 2G en la zona.
- GDPR: consentimiento del paciente/familia y cifrado TLS en MQTT; retención de posiciones definida.

## 8. Enlaces de compra

- T-A7670E R2 con GPS: https://lilygo.cc/products/t-sim-a7670e (elegir «T-A7670E R2 With GPS»)
- PineTime: https://pine64.com/product/pinetime-smartwatch-sealed/
- ESP32 D1 Mini (equivalente): https://es.aliexpress.com/w/wholesale-esp32-d1-mini.html
- Ancla ESP32 verificada: https://www.lilygo.cc/products/t7-mini32-v1-5
- XIAO ESP32C3: https://www.seeedstudio.com/Seeed-XIAO-ESP32C3-p-5431.html
- Tapo C210: https://www.tp-link.com/es/home-networking/cloud-camera/tapo-c210/
- HA Voice PE: https://www.home-assistant.io/voice-pe/
- Bermuda: https://github.com/agittins/bermuda
- Traccar: https://www.traccar.org/protocols/
