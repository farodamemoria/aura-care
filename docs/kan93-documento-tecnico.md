# KAN-93 — Documento técnico: cómo están fabricadas las aplicaciones y las webs

Fecha: 2026-09-15 · Autor: DeepSeek (opencode) · Alcance: producto Faro da Memoria.

Este documento explica **con qué** y **cómo** está construido Faro da Memoria: las aplicaciones
(portal familiar, app de gafas y Faro Móvil), los servicios de servidor y las webs. No contiene
secretos: solo indica dónde están.

## 0. Mapa de componentes

| Componente | Qué es | Dónde vive | Fuente |
| --- | --- | --- | --- |
| **AURA Care (backend)** | API FastAPI que sirve el portal y toda la lógica (reconocimiento, eventos, avisos, chat). | EC2 `ip-172-31-17-219` (servicio `aura-backend`) | Repo `aura-care`, `app/main.py` |
| **Portal Faro Familia** | PWA de familiares y cuidadores (HTML/CSS/JS). | EC2 + CloudFront | Repo `aura-care`, `web/` |
| **Faro Familia (TWA/APK)** | El portal envuelto como app Android (Trusted Web Activity). | APK descargable desde el portal | Proyecto Gradle local `faro-familia-twa` (no está en Git) |
| **App de gafas (Camera Access)** | App Android que conecta con las gafas Meta y analiza fotos. | APK descargable desde el portal | Repo `android`, `samples/CameraAccess` (Meta Wearables DAT) |
| **LifeSense API** | Servicio de análisis visual de fotos (OpenAI). | EC2 `ip-172-31-17-219` (servicio `lifesense-api`) | Repo `android`, `backend/` |
| **Realtime bridge** | Conversación en tiempo real de las gafas. | EC2 `ip-172-31-17-219` (servicio `faro-realtime`) | Solo en el servidor (`/home/ec2-user/realtime-backend`) |
| **Faro Móvil** | App para conversar con cámara y micrófono del teléfono, sin gafas (KAN-44). | APK descargable desde el portal | Pendiente de localizar/subir a Git |

## 1. Arquitectura general

```text
   Gafas Meta (Ray-Ban)
        │  Bluetooth / WiFi
        ▼
   App de gafas "Camera Access" (Android + Meta DAT SDK)
        │  foto (JPEG base64)
        ▼
   LifeSense API (FastAPI, EC2)  ──►  OpenAI Responses (visión)
        ▲
        │  eventos / avisos / ubicación
        │
   Backend AURA Care (FastAPI, EC2)  ──►  SQLite + ficheros (fotos)
        ▲                                ├─► AWS Rekognition (colección faro-faces)
        │                                ├─► OpenAI (chat familiar + avisos)
        │                                └─► WhatsApp Business (Meta, plantillas)
        │
   Portal Faro Familia (PWA + TWA)  ◄── CloudFront (HTTPS público)
```

El portal y las apps hablan **solo con AURA Care**; AURA Care habla con los proveedores
(OpenAI, Rekognition, WhatsApp). El cliente nunca introduce claves de terceros.

## 2. Backend AURA Care (`aura-care`)

- **Stack**: Python 3.12, **FastAPI** `0.2.0` (`app/main.py`), servido con **uvicorn** en `0.0.0.0:8082`
  (en Docker el `Dockerfile` usa el puerto 8080: `python:3.12-slim` + `uvicorn app.main:app`).
- **Dependencias** (`requirements.txt`): `fastapi==0.116.1`, `uvicorn[standard]==0.35.0`,
  `pydantic==2.11.7`, `python-multipart`, `boto3==1.40.21`, `pytest==8.4.1`, `httpx`, `tzdata`.
- **Persistencia**: SQLite (`faro-events.db`) para eventos y configuración, y ficheros para las
  fotos de personas (`person-photos/`). Tablas: `events`, `configuration`, `pairing_invites`,
  `device_credentials`, `memories`, `family_messages`, `whatsapp_status`, `family_alert_rules`.
- **Autenticación**: cabecera `Authorization: Bearer <AURA_LOCAL_TOKEN>`. La versión actual del
  portal es de **acceso público** (token por defecto de desarrollo, `LOCAL_TOKEN` en `app/main.py`);
  el endurecimiento y la rotación de credenciales están pendientes (**KAN-31**). El objetivo de
  producción es **JWT de Cognito** validado por API Gateway.
- **Zona horaria e idioma**: `Europe/Madrid` (`AURA_FAMILY_TIMEZONE`) y es/gl/en
  (`AURA_FAMILY_LANGUAGE`).
- **Proveedores**: `AURA_FACE_PROVIDER=rekognition` con colección `faro-faces` (región
  `us-east-2`); `AURA_WHATSAPP_*` con plantilla `faro_emergency_alert` (idioma `es`);
  `AURA_OPENAI_API_KEY` y `AURA_OPENAI_MODEL=gpt-4.1-mini`.

### 2.1 Reconocimiento de personas

- Se enrolan **5 fotos** por persona (`POST /v1/people/{person_id}/face-samples`); cada muestra
  se indexa en Rekognition (`SearchFacesByImage`).
- La app envía fotogramas a `POST /v1/recognitions`; el backend decide con criterio conservador:
  confianza mínima **95 %**, media mínima **97 %**, **2 fotogramas** coincidentes, enfriamiento de
  10 minutos y revisión de imágenes con TTL de 24 horas. Si duda, no pronuncia el nombre y lo manda
  a «Personas por aclarar» (`GET /v1/reviews`, `POST /v1/reviews/{review_id}/resolve`).

### 2.2 Chat familiar y avisos por WhatsApp

- `POST /v1/family/ask` construye la respuesta con los eventos del día y la **memoria
  conversacional** (`family_messages` + `conversation_id`). Si el familiar se despide, devuelve
  `end_conversation=true`.
- La IA puede activar avisos con la herramienta `registrar_aviso`, que guarda reglas en
  `family_alert_rules` (palabras clave: dolor, caída/golpe, respiración; más reglas propias del
  familiar).
- La entrega usa **plantilla aprobada** (`faro_emergency_alert`) por WhatsApp Business, con
  deduplicación y webhook de estados (`POST /v1/whatsapp/webhook`, `GET /v1/whatsapp/statuses`).
  En Development solo entrega a números de prueba; el paso a **Live** es KAN-89.

### 2.3 Escucha ambiental

`app/environmental_listening.py` es un motor determinista (sin diagnósticos) que, ante señales
acústicas repetidas (tos, atragantamiento, caída, quejido, llanto, grito), hace **una sola**
pregunta de comprobación y escala solo si hay petición de ayuda, persistencia o falta de respuesta.
Se expone por `POST /v1/acoustic-events`, `POST /v1/acoustic-events/response`,
`POST /v1/acoustic-events/tick` y `GET /v1/acoustic-episodes`.

### 2.4 Inventario de endpoints

Portal y estáticos:

- `GET /` — portal Faro Familia.
- `GET /track/{share_token}` — página pública de seguimiento de una ubicación compartida.
- `GET /.well-known/assetlinks.json` — enlace de la TWA de Faro Familia.
- `GET /download/faro.apk`, `GET /download/camera-access.apk`,
  `GET /download/faro-movil.apk`, `GET /download/faro-familia.apk` — descargas de las apps.

Salud y versión:

- `GET /health`, `GET /v1/version`.

Cuenta y configuración:

- `GET /v1/account`, `GET /v1/care-contact`, `PUT /v1/care-contact`,
  `GET /v1/onboarding`, `PUT /v1/onboarding`.

Paciente:

- `GET /v1/patient-profile`, `PUT /v1/patient-profile`,
  `GET /v1/patient-profile/photo`,
  `GET /v1/patient-profile/face-samples/{sample_index}`,
  `POST /v1/patient-profile/face-samples`.

Personas conocidas:

- `POST /v1/people`, `GET /v1/people`,
  `GET /v1/people/{person_id}`, `PATCH /v1/people/{person_id}`, `DELETE /v1/people/{person_id}`,
  `GET /v1/people/{person_id}/profile-photo`,
  `GET /v1/people/{person_id}/face-samples/{sample_index}`,
  `POST /v1/people/{person_id}/face-samples`.

Reconocimiento y revisiones:

- `POST /v1/recognitions`, `GET /v1/reviews`,
  `GET /v1/reviews/{review_id}/image`, `POST /v1/reviews/{review_id}/resolve`.

Red de cuidados:

- `GET /v1/care-contacts`, `POST /v1/care-contacts`,
  `PATCH /v1/care-contacts/{contact_id}`, `DELETE /v1/care-contacts/{contact_id}`.

Avisos:

- `POST /v1/emergency-alerts`, `GET /v1/emergency-alerts`, `POST /v1/alerts/test`,
  `GET /v1/whatsapp/webhook`, `POST /v1/whatsapp/webhook`, `GET /v1/whatsapp/statuses`,
  `POST /v1/protective-observations`.

Ubicación:

- `POST /v1/location-sessions`, `PUT /v1/location-sessions/{session_id}/location`,
  `GET /v1/location-sessions/active`, `POST /v1/location-sessions/{session_id}/stop`,
  `GET /v1/location-share/{share_token}`, `POST /v1/location/answer`.

Eventos y memoria:

- `POST /v1/events`, `GET /v1/events`, `GET /v1/conversation-memory/search`,
  `POST /v1/memories`, `GET /v1/memories`.

Conversación familiar:

- `POST /v1/family/ask`.

Emparejamiento y dispositivos:

- `POST /v1/pairing-invites`, `POST /v1/pairing/claim`,
  `POST /v1/device-credentials/validate`.

Escucha ambiental:

- `POST /v1/acoustic-events`, `POST /v1/acoustic-events/response`,
  `POST /v1/acoustic-events/tick`, `GET /v1/acoustic-episodes`.

## 3. Portal Faro Familia (`aura-care/web`)

- **Stack**: HTML5, CSS y JavaScript **vanilla** (sin framework ni build). PWA instalable mediante
  `web/assets/manifest.webmanifest` (`display: standalone`, idioma `es`) y **service worker**
  (`web/assets/sw.js`, caché `faro-familia-v27`) con estrategia «red primero, caché de respaldo».
- **Estructura**: `web/index.html` (vistas), `web/assets/app.js` (lógica y llamadas a la API),
  y las hojas `web/assets/app.css` + `events.css` + `people.css` + `care.css` + `patient.css` +
  `family.css`.
- **Vistas** (pestañas): Paciente, Personas conocidas, Por aclarar, Cuidados y Memoria.
  - Paciente: ficha propia (no se mezcla con familiares) y preparación de reconocimiento (5 fotos).
  - Personas conocidas: alta con consentimiento y 5 muestras; ficha y fotos visibles.
  - Por aclarar: identificación de desconocidos; nada se pronuncia hasta confirmarlo.
  - Cuidados: red de contactos con rol, prioridad y consentimiento de WhatsApp; vinculación de
    otro cuidador con código de un solo uso (10 minutos).
  - Memoria: cronología de eventos con filtros y **chat de voz** (`Web Speech API` para
    reconocimiento de voz y `speechSynthesis` para leer la respuesta), con conversación continua y
    «Empezar de nuevo».
- **Versionado de caché**: al cambiar el frontend se sube la versión de `app.js?v=NN` y del `CACHE`
  del service worker para forzar la actualización.
- **TWA**: el APK de Faro Familia envuelve el portal a pantalla completa; el backend sirve el
  `assetlinks.json` que autoriza el enlace.

## 4. App de gafas «Camera Access» (`android`, `samples/CameraAccess`)

- **Stack**: Android nativo **Kotlin** `2.2.21` con **Jetpack Compose** (BOM `2026.05.01`,
  Material 3), AGP `8.11.1`, ciclo de vida `2.10.0`. Compila con Gradle Wrapper.
- **SDK**: **Meta Wearables Device Access Toolkit** (`mwdat` `0.9.0`: `mwdat-core`,
  `mwdat-camera`, `mwdat-mockdevice`) desde GitHub Packages de Meta (requiere `GITHUB_TOKEN`).
- **Permisos y servicios**: Bluetooth y `BLUETOOTH_CONNECT`, cámara, internet, grabación de audio,
  **servicio en primer plano** tipo `connectedDevice` y `WAKE_LOCK` para seguir en segundo plano.
- **Registro en Meta**: `AndroidManifest.xml` toma `APPLICATION_ID` y `CLIENT_TOKEN` de la app
  registrada en el Wearables Developer Center (variables `mwdat_application_id` y
  `mwdat_client_token`). El esquema `cameraaccess://` permite volver desde Meta AI.
- **Código principal**: `MainActivity.kt`, `CameraViewModel`/`CameraUiState`,
  `stream/StreamingService`, `stream/VideoCaptureHandler`, `stream/AudioInputHandler`,
  `stream/HevcDecoder`, `stream/VideoRecorder`, `ui/...` (pantallas Compose) y
  `assistant/AssistantApi.kt`.
- **Flujo de análisis**: la app captura un fotograma, lo comprime a JPEG (calidad 85) y lo envía a
  `POST /v1/vision/analyze` del backend **LifeSense**; la clave de OpenAI nunca está en la app.
- El APK que se distribuye como «App gafas» es `camera-access.apk`.

## 5. LifeSense API (`android/backend`)

- **Stack**: Python + **FastAPI** (`LifeSense AI API` `0.1.0`), `httpx`; variables
  `OPENAI_API_KEY` y `OPENAI_MODEL` (`gpt-4.1-mini`).
- **Endpoints**: `GET /healthz` (sonda) y `POST /v1/vision/analyze` (JSON con `image_base64` de
  hasta 5 MiB y un `prompt` opcional) que llama a la **Responses API** de OpenAI y devuelve
  `answer`.
- **Despliegue**: EC2, servicio systemd `lifesense-api` (`/home/ec2-user/lifesense-api`),
  por HTTPS y detrás de autenticación de la app.

## 6. Realtime bridge

Servicio en la EC2 (`/home/ec2-user/realtime-backend`, systemd `faro-realtime`) que da la
conversación en tiempo real de las gafas (interrupción natural y sin respuestas diferidas). Su
código no está en los repositorios locales: vive en el servidor.

## 7. Faro Móvil

App Android para conversar con la **cámara y el micrófono del teléfono** sin gafas ni ordenador
(KAN-44, en revisión). Se distribuye como `faro-movil.apk` desde el portal; su código todavía no
está en un repositorio local.

## 8. Infraestructura y despliegue

- **EC2** `ip-172-31-17-219` con tres servicios systemd: `aura-backend`, `lifesense-api` y
  `faro-realtime`.
- **CloudFront** delante del portal: `https://d2n7ih9kfxbzvd.cloudfront.net`.
- **AWS**: Rekognition (colección `faro-faces`, `us-east-2`), Lambda para el panel de estado de
  Jira, AWS Budgets para el coste.
- **Meta**: app `farodamemoria`; **WhatsApp Business** con la plantilla `faro_emergency_alert`.
- **OpenAI**: chat familiar, avisos y análisis visual (clave en Secrets Manager / ficheros `.env`
  del servidor; nunca en Git).
- **Despliegue del backend**: en la EC2, `git pull origin main`, instalar `requirements.txt` y
  `sudo systemctl restart aura-backend`; probar en producción y registrarlo en Jira.
- **Reparto de secretos** (no incluidos aquí): `/etc/aura-backend/whatsapp.env`,
  `/etc/aura-backend/openai.env`, `/etc/faro/realtime.env`.

## 9. Seguridad, privacidad y datos

- Alta con **consentimiento explícito** y revocable; cinco muestras por persona; borrado completo
  al eliminar (`DELETE /v1/people/{person_id}`).
- **Minimización**: las identidades dudosas van al portal y nunca se pronuncian; LED de grabación
  en hardware propio; sin diagnósticos automáticos ni decisiones clínicas.
- Separación por **círculo de cuidados** `care_circle_id` como objetivo de arquitectura SaaS
  (Cognito + API Gateway + Lambda + DynamoDB cifrado con KMS en la versión de producción).
- Pendiente de producción: **DPIA**, condiciones del tratamiento biométrico y validación legal;
  y el endurecimiento de la autenticación (**KAN-31**).

## 10. Flujo de trabajo del código

- Repositorios: `aura-care` (backend + portal) y `android` (SDK de Meta, app de gafas y LifeSense).
- Regla: **nunca** se sube directo a `main`; cada tarea de Jira es una rama `KAN-XX-descripcion` y
  un Pull Request que se mergea cuando los tests pasan al 100 %.
- Los tests viven en `aura-care/tests/` (pytest) y cubren reconocimiento, avisos, escucha
  ambiental, portal público y las tareas documentales.
