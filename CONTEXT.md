# CONTEXTO DEL PROYECTO — Faro da Memoria

> Documento de contexto para asistentes de IA (opencode / DeepSeek) y desarrolladores.
> **Si eres una IA que acaba de iniciar sesión: lee este archivo COMPLETO antes de actuar.**
> **Última actualización:** 2026-09-11 · **Punto estable:** rama `main` (último commit de código: `732363e`).
> Este documento NO contiene secretos: solo indica DÓNDE están.

---

## 1. Qué es Faro da Memoria

Producto de acompañamiento para personas con problemas de memoria (p. ej. Alzheimer), basado en **gafas inteligentes Meta (Ray-Ban)** + IA. El paciente lleva las gafas; la familia y cuidadores usan un portal.

Componentes del producto:
- **Faro (app de las gafas, Android):** reconoce a personas conocidas, conversa con el paciente, comparte ubicación y lanza avisos a la familia.
- **Faro Familia (portal de familiares/cuidadores):** PWA para gestionar personas conocidas, "personas por aclarar", la red de cuidados, la memoria/eventos y **hablar con Faro por voz**.
- **Faro Móvil:** versión para conversar con la cámara/micrófono del teléfono sin gafas (en desarrollo; ver KAN-44).
- **Backend AURA Care:** API + portal en AWS que conecta todo.

---

## 2. Componentes y repositorios

| Componente | Qué es | Dónde |
|---|---|---|
| **AURA Care (backend)** | API FastAPI que sirve el portal y la lógica (reconocimiento, avisos, chat). | Repo `aura-care` → `app/main.py` |
| **Faro Familia (PWA)** | Portal de cuidadores (HTML/CSS/JS vanilla). | Repo `aura-care` → `web/` |
| **Faro (app de gafas)** | App Android sobre el **Meta Wearables DAT SDK**. | Repo `android` (rama `farodamemoria-replace-repository-content`) |
| **LifeSense API** | Análisis visual de fotos de las gafas (OpenAI). | EC2 → `/home/ec2-user/lifesense-api` |
| **Realtime bridge** | Conversación en tiempo real de las gafas. | EC2 → `/home/ec2-user/realtime-backend` |
| **Faro Familia TWA (APK/AAB)** | El portal envuelto como app Android (Trusted Web Activity). | Local `faro-familia-twa` (NO está en Git) |
| **Dashboard Jira** | Panel de estado del proyecto (AWS Lambda). | URL abajo |

---

## 3. Enlaces y plataformas

### GitHub
- Cuenta: https://github.com/farodamemoria
- Backend + portal: https://github.com/farodamemoria/aura-care
- App de gafas: https://github.com/farodamemoria/android

### Jira
- Sitio: https://farodamemoria.atlassian.net
- Proyecto: **KAN**
- Cuenta: `farodamemoria@gmail.com`
- Acceso desde IA: **REST API** con email + API token (el token lo tiene el titular; NO está en este doc). El MCP de Atlassian está configurado pero a veces falla; usar REST.
- Endpoint útil: `GET /rest/api/3/issue/KAN-XX?fields=status,summary`, `GET .../transitions`, `POST .../comment` (v2 para texto plano).

### AWS
- **Portal en producción (CloudFront):** https://d2n7ih9kfxbzvd.cloudfront.net
- **EC2:** `ip-172-31-17-219` (IP privada), usuario `ec2-user`. Servicios systemd: `aura-backend`, `lifesense-api`, `faro-realtime`.
- **Rekognition:** colección de caras `faro-faces` (región `us-east-2`).
- **Dashboard Jira (Lambda):** https://uxzydoziyfnynjpzriedndf62a0pfiom.lambda-url.us-east-1.on.aws/

### Meta
- **App de Meta:** `farodamemoria` (App ID `1592113852645672`) → https://developers.facebook.com/apps/1592113852645672/
- **WhatsApp Business:** número **+34 644 44 98 43** (Phone Number ID `1304805966046293`).
- **Plantilla de aviso:** **`faro_emergency_alert`** (idioma `es`, 2 parámetros: `{{1}}` tipo, `{{2}}` mensaje). Categoría "Servicio".
- **Número de prueba Meta:** +1 (555) 198-1206 (Phone Number ID `1282949794901705`).
- **Webhook de estados:** `https://d2n7ih9kfxbzvd.cloudfront.net/v1/whatsapp/webhook` (verify token `faro-whatsapp-verify`; suscribir campo `messages`).

### OpenAI
- Usado por el backend (chat familiar + avisos), por LifeSense y por el realtime de las gafas.
- La clave está en el servidor (ver sección 4).

### Google Drive
- APK de Faro Familia (TWA): https://drive.google.com/file/d/1iPEDhTCHLJ6UCtqImrTgnrxARAs8qnfi/view

### Herramienta de IA
- **opencode** con modelo **DeepSeek**. Contexto del proyecto: este archivo.

---

## 4. Secretos (DÓNDE están — nunca en Git)

- **WhatsApp:** `/etc/aura-backend/whatsapp.env` → `AURA_WHATSAPP_PHONE_NUMBER_ID`, `AURA_WHATSAPP_TOKEN`.
- **OpenAI:** `/etc/aura-backend/openai.env` (reutiliza la clave de `/etc/faro/realtime.env`).
- **Realtime/OpenAI original:** `/etc/faro/realtime.env`.
- **Keystore del TWA:** `faro-familia-twa/app/faro-familia.keystore` (contraseña: la tiene el titular; NO incluida aquí).
- **Token de Jira y credenciales de GitHub:** los tiene el titular.

> Regla: los `.env`, tokens, keystores y bases de datos NO se suben a Git (están en `.gitignore`).

---

## 5. Estado actual (Jira)

- **KAN-80** — "Faro Familia puede hablar" → **En revisión** (implementado; pendiente validar por el PO).
- **KAN-87** — Investigación del chat/WhatsApp + solución → **En revisión**.
- **KAN-89** — Publicar la app de Meta en **Live** + verificación de empresa (WhatsApp producción) → **Por hacer**.
- **KAN-31** — Cerrar autenticación pública de desarrollo y rotar credenciales expuestas (incluye la clave de OpenAI) → pendiente.
- Resto de tareas del proyecto: ver tablero KAN.

### Funcionalidades entregadas (KAN-80)
- **Chat de voz** en la pestaña Memoria: pregunta por voz (Web Speech API) y respuesta leída en voz alta (`speechSynthesis`).
- **Memoria conversacional**: mantiene el hilo (tabla `family_messages` + `conversation_id`); botón "Empezar de nuevo".
- **Conversación continua**: tras cada respuesta el micrófono sigue activo; se cierra al despedirse (`end_conversation`).
- **Criterios de aviso por WhatsApp**: dolor, caída/golpe, respiración (+ reglas personalizadas).
- **La IA registra avisos** (function calling `registrar_aviso`) → tabla `family_alert_rules`.
- **Entrega garantizada**: los avisos van como **plantilla aprobada** (`faro_emergency_alert`), así llegan aunque el familiar no haya interactuado en 24 h.
- **Botón de descarga del APK** (TWA de Faro Familia) en el portal.
- **Diagnóstico**: `POST /v1/alerts/test` (canal plantilla/texto + error) y webhook de estados (`/v1/whatsapp/statuses`).

### Pendientes
- Validar las 5 pruebas del chat: (1) resumen, (2) despedida apaga el micro, (3) rechaza informes, (4) rechaza temas ajenos (chistes), (5) registra el aviso.
- Publicar la app de Meta en **Live** + verificación de empresa (**KAN-89**).
- **Rotar la clave de OpenAI** expuesta (**KAN-31**).
- Subir el proyecto **TWA** a GitHub (sin el keystore).

---

## 6. Arquitectura técnica del backend (`aura-care`)

- **FastAPI** "AURA Care" v0.2.0 (`app/main.py`), servido con uvicorn en `0.0.0.0:8082`.
- **Persistencia:** SQLite (`faro-events.db`) + ficheros (fotos de caras en `person-photos/`).
- **Auth:** cabecera `Authorization: Bearer <AURA_LOCAL_TOKEN>` (token configurado en el servidor; sin valor por defecto: si falta, el fallo es cerrado). Objetivo producción: JWT de Cognito validado por API Gateway.
- **Zona horaria** del "día" del paciente: `Europe/Madrid` (`AURA_FAMILY_TIMEZONE`).
- **Idiomas** del chat: es/gl/en (`AURA_FAMILY_LANGUAGE`, por defecto `es`).

### Tablas SQLite
`events`, `configuration`, `pairing_invites`, `device_credentials`, `memories`, `family_messages`, `whatsapp_status`, `family_alert_rules`.

### Endpoints principales
- Salud/versión: `GET /health`, `GET /v1/version`
- Personas: `GET/POST /v1/people`, `GET/PATCH/DELETE /v1/people/{id}`, `.../profile-photo`, `.../face-samples`
- Reconocimiento: `POST /v1/recognitions`, `GET /v1/reviews`, `GET /v1/reviews/{id}/image`, `POST /v1/reviews/{id}/resolve`
- Paciente: `GET/PUT /v1/patient-profile`, `.../photo`, `.../face-samples`
- Cuidados: `GET/POST /v1/care-contacts`, `PATCH/DELETE /v1/care-contacts/{id}`
- Eventos: `GET/POST /v1/events`
- Avisos: `POST /v1/emergency-alerts`, `GET /v1/emergency-alerts`, `POST /v1/protective-observations`, `POST /v1/alerts/test`
- WhatsApp: `GET/POST /v1/whatsapp/webhook`, `GET /v1/whatsapp/statuses`
- Ubicación: `POST /v1/location-sessions`, `GET /v1/location-sessions/active`, `POST /v1/location-sessions/{id}/stop`, `GET /v1/location-share/{token}`
- **Chat familiar:** `POST /v1/family/ask` (pregunta por voz/texto; memoria; avisos)
- Memoria: `GET /v1/conversation-memory/search`, `GET/POST /v1/memories`
- Emparejamiento: `POST /v1/pairing-invites`, `POST /v1/pairing/claim`, `POST /v1/device-credentials/validate`
- TWA: `GET /.well-known/assetlinks.json`, `GET /download/faro.apk`
- Onboarding: `GET/PUT /v1/onboarding`

### Variables de entorno (servicio `aura-backend`)
`AURA_EVENT_DB`, `AURA_DATA_FILE`, `AURA_FACE_PROVIDER=rekognition`, `AURA_REKOGNITION_COLLECTION=faro-faces`, `AWS_REGION=us-east-2`, `AURA_LOCAL_TOKEN`, `AURA_WHATSAPP_PHONE_NUMBER_ID`, `AURA_WHATSAPP_TOKEN`, `AURA_WHATSAPP_TEMPLATE=faro_emergency_alert`, `AURA_WHATSAPP_TEMPLATE_LANG=es`, `AURA_WHATSAPP_PREFER_TEMPLATE=1`, `AURA_WHATSAPP_VERIFY_TOKEN=faro-whatsapp-verify`, `AURA_OPENAI_API_KEY` / `OPENAI_API_KEY`, `AURA_OPENAI_MODEL=gpt-4.1-mini`, `AURA_FAMILY_LANGUAGE=es`, `AURA_FAMILY_TIMEZONE=Europe/Madrid`.

### Frontend (`web/`)
`index.html`, `assets/app.js`, `assets/app.css`, `assets/family.css`, `assets/events.css`, `assets/people.css`, `assets/care.css`, `assets/patient.css`, `assets/sw.js` (service worker), `assets/manifest.webmanifest`.

### Estructura del repo `aura-care`
```
aura-care/
├── app/
│   ├── __init__.py
│   └── main.py            # Backend FastAPI completo
├── web/
│   ├── index.html         # Portal Faro Familia
│   └── assets/            # app.js, css, sw.js, manifest
├── Dockerfile
├── requirements.txt
├── README.md
└── .gitignore
```

---

## 7. Cómo trabajar (flujo)

### Flujo Git/GitHub (colaboración — 3 personas)

> Regla permanente: **nunca** se sube directo a `main`. Todo pasa por ramas + Pull Request. Una tarea de Jira = una rama.

**Antes de empezar una tarea** (actualizar tu copia y aislar el trabajo):
```bash
git checkout main
git pull origin main
git checkout -b KAN-XX-descripcion
```

**Desarrollar y subir** (commits pequeños y frecuentes):
```bash
git add .
git commit -m "KAN-XX: resumen del cambio"
git push -u origin KAN-XX-descripcion
```

**Abrir Pull Request** en GitHub (rama → `main`) y **hacer el merge a `main`** (lo hace la IA cuando los tests pasan al 100%; no hace falta revisión de otro miembro). Al mergear se borra la rama.

**Mantenerse al día** (a diario o antes de empezar):
```bash
git checkout main
git pull origin main
```

Reglas para no pisarse:
1. **Nunca pushear directo a `main`**; solo vía rama + PR. `main` queda siempre estable y desplegable.
2. **Una rama = una tarea de Jira** (nada de mezclar tareas).
3. **Trabajar en archivos distintos siempre que se pueda.** Si dos personas tocan el mismo archivo, el segundo merge tendrá conflicto: se resuelve en local (`git pull origin main` en tu rama → resolver → commit → push), **nunca a ciegas**.
4. **No subir secretos ni builds:** `.env`, `*.keystore`, `__pycache__/`, `.gradle/`, `app/build/`, `*.db` (ya están en los `.gitignore`; respetarlos).
5. Cada persona sube a su rama; los demás reciben el trabajo con `git pull origin main` tras el merge del PR.

### Despliegue y registro

1. **Editar en local** (repo clonado). El punto estable es la rama `main`.
2. **Desplegar en la EC2:**
   ```bash
   cd /home/ec2-user/aura-backend
   git pull origin main
   .venv/bin/pip install -r requirements.txt
   sudo systemctl restart aura-backend
   ```
3. **Probar** en producción: https://d2n7ih9kfxbzvd.cloudfront.net
4. **Registrar TODO en Jira:** comentario con el resultado; mover la tarea a **"En revisión"** al terminar y a **"Finalizado"** cuando el PO valide; crear tareas nuevas cuando haga falta.
5. **No subir secretos** a Git.

### Comandos útiles
```bash
# Prueba de aviso WhatsApp (envía mensaje real):
curl -s -X POST https://d2n7ih9kfxbzvd.cloudfront.net/v1/alerts/test -H "Authorization: Bearer $AURA_LOCAL_TOKEN"

# Estados de entrega (requiere app en Live + webhook):
curl -s "https://d2n7ih9kfxbzvd.cloudfront.net/v1/whatsapp/statuses" -H "Authorization: Bearer $AURA_LOCAL_TOKEN"

# Pregunta al chat familiar:
curl -s -X POST https://d2n7ih9kfxbzvd.cloudfront.net/v1/family/ask \
  -H "Authorization: Bearer $AURA_LOCAL_TOKEN" -H "Content-Type: application/json" \
  -d '{"question":"¿Cómo ha ido hoy?","language":"es"}'
```

---

## 8. Convenciones y notas importantes

- **Idioma:** gallego para el paciente (gafas); español para el portal/familia (configurable).
- **La IA del chat debe:** responder preguntas sobre eventos, registrar avisos por WhatsApp, **crear recordatorios en la agenda** (`crear_recordatorio`), mantenerse en el ámbito del paciente, **no inventar funciones ni datos**, no entrar en bucle, y **no ofrecer funciones que no existen** (informes periódicos, envíos a demanda…).
- **Entrega de avisos:** por **plantilla aprobada** (no dependen de la ventana de 24 h).
- **Meta Development vs Live:** en Development, WhatsApp solo entrega a números de prueba; para producción hay que pasar a **Live** + verificación de empresa (**KAN-89**).
- **Despliegue:** la EC2 sirve el portal; CloudFront delante. Tras cambios de frontend, subir la versión de `app.js?v=NN` y del `CACHE` del service worker para forzar la actualización.
- **TWA:** el APK de Faro Familia se genera con un proyecto Gradle local (`faro-familia-twa`); el `assetlinks.json` se sirve desde el backend para que abra a pantalla completa.

---

## 9. Equipo y cuentas

- **Cuenta principal:** `farodamemoria@gmail.com`.
- **Otra persona del equipo** tiene físicamente las gafas (hace las pruebas reales).
- **Herramienta de IA:** opencode (DeepSeek), compartida entre las dos personas.

---

## 10. Cómo arrancar (para la IA)

> "Lee `CONTEXT.md` para tener todo el contexto del proyecto."

Con eso ya conoces: qué es el producto, los repos, los enlaces (Jira, GitHub, AWS, Meta, Drive), la arquitectura del backend, el estado actual de las tareas y los pendientes. **No hay secretos en este documento**; si necesitas uno, pídeselo al titular o míralo en la EC2 (ver sección 4).
