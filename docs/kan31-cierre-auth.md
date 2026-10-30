# KAN-31 — Cierre de la autenticación pública de desarrollo y rotación de credenciales

Fecha: 2026-10-30. Alcance: backend `aura-care`, portal `web/`, puente Realtime y apps cliente.
Este documento no contiene valores de credenciales; solo nombres, rutas y huellas parciales.

## 1. Problema confirmado

La instancia pública (`https://api.loginea.com`) aceptaba como válido el token de desarrollo
conocido y devolvía datos del círculo familiar en `/v1/people`. La causa era doble:

- `AURA_LOCAL_TOKEN` del servicio `aura-backend` estaba configurado con ese valor histórico.
- El portal (`web/assets/app.js`) lo llevaba incrustado como valor por defecto.
- La app de gafas (`FaroApi.kt`, `FaroReminders.kt`) y el puente (`faro-puente-app`) llevaban
  credenciales por defecto en código cliente.

## 2. Cambios aplicados

### Backend (`app/main.py`)

1. **Sin valor por defecto y sin tokens conocidos.** `configured_local_token()` exige
   `AURA_LOCAL_TOKEN`, rechaza los tokens históricos (comparados por hash SHA-256) y exige una
   longitud mínima de 24 caracteres. Si la configuración no es segura, responde `503`.
2. **Sesiones por usuario y círculo familiar.** `POST /v1/auth/session` (solo con el token de
   arranque) emite un token firmado con HMAC-SHA256 (`AURA_SESSION_SECRET`) que incluye
   `cid` (círculo), `role`, `sub` (usuario), `iat` y `exp`. Caducidad entre 60 s y 24 h.
3. **Aislamiento entre familias.** `require_auth` rechaza (`403`) una sesión de otro círculo y
   `require_auth_or_device` / `/v1/device-credentials/validate` hacen lo mismo con credenciales
   de dispositivo de otro círculo.
4. **Pepper obligatorio.** `credential_hash()` ya no cae al token local: sin
   `AURA_CREDENTIAL_PEPPER` responde `503`.

### Portal (`web/`)

- `app.js` ya no tiene token por defecto: usa `?token=...` una vez (se guarda en `localStorage`) o
  el token almacenado. Sin token no llama a la API y muestra «Acceso no autorizado».
- Se sube la versión de `app.js` (`v47`) y la caché del service worker (`faro-familia-v57`).

### Cliente Android y puente

- Se eliminan las constantes con token del código fuente; la app usa la credencial de dispositivo
  obtenida en el emparejamiento (`FaroPairing`). El puente deja el token por defecto vacío y lo
  pide en sus ajustes.

## 3. Rotación ejecutada

`scripts/rotate_faro_credentials.py` genera y escribe, con permisos `0600`:

| Fichero | Claves |
|---|---|
| `/etc/faro/aura.env` | `AURA_LOCAL_TOKEN`, `AURA_CREDENTIAL_PEPPER`, `AURA_SESSION_SECRET`, `AURA_CARE_CIRCLE_ID` |
| `/etc/faro/realtime.env` | `AURA_ACCESS_TOKEN` (sincronizado con el nuevo token) |

Solo se publican longitudes y huellas SHA-256 parciales. Después se reinician
`aura-backend` y `faro-realtime`.

## 4. Verificación (sin datos personales)

Comandos y resultado esperado:

```bash
curl -s -o /dev/null -w '%{http_code}' https://api.loginea.com/v1/people
# 401 (anónimo)
curl -s -o /dev/null -w '%{http_code}' -H 'Authorization: Bearer <token-historico>' \
  https://api.loginea.com/v1/people
# 401 (token de desarrollo revocado)
curl -s -o /dev/null -w '%{http_code}' -H 'Authorization: Bearer <token-nuevo>' \
  https://api.loginea.com/v1/people
# 200 (token rotado válido, sin mostrar datos)
```

Pruebas negativas automatizadas: `tests/test_public_access.py` (anónimo, token histórico, token
inválido, configuración débil, sesión caducada, firma manipulada y sesión de otra familia).

Auditoría de repositorio: `python scripts/audit_repository_secrets.py` (0 hallazgos en el árbol de
trabajo; el token histórico aparece solo en commits antiguos y ya está revocado).

## 5. Verificación externa ejecutada (2026-10-30)

Solo códigos de estado; sin cuerpos de respuesta ni datos personales.

| Comprobación | Resultado |
|---|---|
| `GET https://api.loginea.com/health` | 200 |
| `GET /v1/people`, `/v1/events`, `/v1/onboarding`, `/v1/reviews`, `/v1/location-sessions/active` sin cabecera | 401 |
| Los mismos 5 endpoints con el token de desarrollo histórico | 401 |
| `POST /v1/auth/session` sin credencial de arranque | 401 |
| `POST /v1/auth/session` con el token histórico | 401 (`Bootstrap authentication required`) |
| `GET /v1/auth/session` | 405 (la ruta existe; solo admite POST) |

Lectura: el servicio está arriba, los endpoints sensibles exigen identidad y el token histórico no
autoriza ninguno. Como el servicio no devuelve `503`, el `AURA_LOCAL_TOKEN` configurado existe y no
es uno de los tokens de desarrollo bloqueados por hash: la rotación está aplicada en producción.

## 6. Cliente de gafas (2026-10-30)

- `FaroApi`, `FaroNotify`/`FaroReminderService` y `FaroAudioMonitor` ya no tienen constante de
  token: piden la credencial de dispositivo a `FaroPairing`. Sin emparejamiento no se envía ninguna
  petición autenticada.
- Prueba JVM nueva `FaroCredentialSourceTest` (3 casos): ausencia del token histórico en fuentes,
  cabeceras `Authorization` con la credencial emparejada y `FaroApi.token` delegando en el
  emparejamiento.
- `gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug` → BUILD SUCCESSFUL; 3/3 pruebas;
  lint sin errores. APK `app-arm64-v8a-debug.apk` (SHA-256 `B46FDDD2…F3A2CE`) sin la cadena del token
  histórico en sus ficheros DEX.

## 7. Pendiente operativo

Instalar el APK nuevo en el visor (KAN-112, entrega física) para que la app use el emparejamiento.
El APK antiguo contiene el token histórico, que ya no autoriza ninguna petición.

