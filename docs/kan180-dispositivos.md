# KAN-180 — Dispositivos de Faro Familia: análisis funcional y rediseño UX/UI

**Firmado por: opencode**

## 1. Problema

La pestaña **Dispositivos** mezclaba cinco conceptos distintos en tarjetas sueltas sin jerarquía:
fuentes de actividad (`glasses`, `phone`, `portal`, `backend`), credenciales emparejadas
(`Dispositivo autorizado – role`), cámaras, patrulla y consentimiento. No se distinguía un
dispositivo real de un acceso, ni había acciones claras por dispositivo.

## 2. Modelo funcional

| Concepto | Dónde vive | Qué representa |
|---|---|---|
| **Dispositivo real** | actividad por `source` + `cameras` | Hardware o canal que produce datos: Gafas, Móvil, Ojo (Tapo C210), Portal. |
| **Servicio** | `source=backend` | Backend AURA Care; su estado se comprueba contra este mismo endpoint. |
| **Acceso autorizado** | `device_credentials` | Credencial emitida al canjear un código de emparejamiento. Tiene rol (`family`, `caregiver`, `clinician`) y puede revocarse. No es hardware. |
| **Emparejamiento** | `pairing_invites` | Código de un solo uso (10 min) que crea una credencial. Roles: familiar, cuidador, profesional sanitario. |
| **Consentimiento de vídeo** | `configuration.video_consent` | Requisito previo a cualquier transmisión en directo. |
| **Transmisiones** | `live_views` | Solicitudes de vídeo en directo de Gafas/Móvil, auditadas (`pending`, `active`, `completed`, `cancelled`, `denied`). |
| **Cámara / Ojo de Faro** | `cameras`, `/v1/camera/*` | Tapo C210 a través del puente RTSP. En línea si la última imagen tiene menos de 5 min. |
| **Patrulla** | `configuration.camera_patrol` | Barrido horizontal y vertical, intervalo y presupuesto diario de IA. |
| **Rastreadores** | `/v1/trackers` | Objetos (llaves, cartera…) con estado cerca/lejos/perdido (KAN-165). |
| **Permisos por dispositivo** | `device_settings` (KAN-180) | Micrófono, cámara, ubicación y seguimiento. Persisten por dispositivo y quedan auditados. |

Reglas de estado:

- **Gafas/Móvil/Portal**: en línea si su última actividad tiene menos de 15 min; si no,
  «sin actividad reciente». No se inventa un ping que el hardware no expone.
- **Ojo de Faro**: en línea si la última imagen tiene menos de 5 min (mismo criterio que
  `/v1/camera/status`).
- **Servicio**: en línea cuando responde esta API.
- La prueba de conexión devuelve `online`, `detail`, `checked_at`, `latency_ms` y
  `last_activity_at` medidos en el momento.

## 3. Estructura definitiva de la sección

0. **Estado de Faro** (dashboard de salud, encima de todo): siete indicadores con semáforo
   (verde / ámbar / rojo / sin dato) y un resumen global del estado del sistema.
   | Indicador | Cálculo (datos reales, sin inventar) |
   |---|---|
   | Batería | `battery_percent` más reciente de cada fuente en los eventos y en `last_location`; se muestra el mínimo y el detalle por dispositivo. |
   | Última conexión | `last_event_at` por fuente (`glasses`, `phone`, `portal`); verde < 15 min, ámbar < 30, rojo ≥ 30. |
   | Estado de la cámara | `cameras[].online` y antigüedad de `last_frame_at`; verde < 10 min, ámbar < 30, rojo ≥ 30. |
   | Calidad de conexión | latido más reciente (fuentes + cámara): verde < 5 min, ámbar < 30, rojo ≥ 30. |
   | Última sincronización | `max(created_at)` de los eventos cargados en el panel. |
   | Errores de reconocimiento | número de revisiones en estado `pending` ("Personas por aclarar"). |
   | Estado de los avisos | último `delivery_status`/`family_alert_status`/`alert_status` de un evento de aviso y contactos con avisos + consentimiento activos. |
   Las baterías se leen de los eventos y de `location-sessions/active`; si el hardware no las envía, el
   indicador dice "Sin dato" en lugar de suponer un valor. El resumen global es rojo si algún
   indicador está rojo, ámbar si hay avisos y verde si todo está correcto.
1. **Cabecera** con resumen (dispositivos en línea / total) y acciones globales:
   *Emparejar dispositivo* y *Actualizar*.
2. **Dispositivos** (tarjeta por dispositivo real):
   - Gafas, Móvil y Portal: estado, última actividad, eventos 24 h, permisos
     (micrófono, cámara, ubicación, seguimiento), *Probar conexión* y *Ver en directo*.
   - Ojo de Faro: estado, última imagen, vista previa, *Ver ahora*, *Probar conexión* y
     configuración de patrulla (horizontal, vertical, intervalo, presupuesto de IA).
   - Servicio: estado y última actividad.
3. **Accesos autorizados**: credenciales por rol, fecha y acción *Revocar acceso*.
4. **Privacidad y consentimiento**: activar/retirar el consentimiento de vídeo.
5. **Transmisiones**: solicitudes con estado y opción de cancelar.
6. **Rastreadores**: objetos vinculados y su último estado; si no hay, se explica cómo se usan.

## 4. API

| Método | Ruta | Uso |
|---|---|---|
| `GET` | `/v1/devices` | Inventario + actividad + `settings` por dispositivo + cámaras + consentimiento. |
| `PUT` | `/v1/devices/sources/{source}/settings` | Guarda micrófono/cámara/ubicación/seguimiento. |
| `POST` | `/v1/devices/{id}/revoke` | Revoca una credencial (404 si no existe o ya estaba revocada). |
| `POST` | `/v1/devices/connection-test` | Prueba de conexión real de `glasses`, `phone`, `portal`, `backend` o `camera`. |
| `POST` | `/v1/pairing-invites` | Crea el código de emparejamiento. |
| `PUT` | `/v1/devices/video-consent` | Activa/retira consentimiento. |
| `POST` | `/v1/live-views` | Solicita transmisión (requiere consentimiento). |

## 5. Criterios de aceptación

- Una sola sección, agrupada por dispositivo real y con jerarquía visual.
- Estado, configuración y acciones visibles en cada tarjeta.
- Los accesos por rol dejan de confundirse con hardware.
- Dashboard **Estado de Faro** con los siete indicadores pedidos y semáforos calculados con datos reales.
- Sin desbordes horizontales a 1366 px y 390 px.
- Permisos, revocación y prueba de conexión verificados por API y por UI.
