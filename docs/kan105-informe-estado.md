# Informe de estado — Faro da Memoria

**Fecha:** 2026-09-15 · **Proyecto:** KAN · **Elaborado por:** IA (opencode) para Jose Sanchez
**Fuentes:** tablero KAN, panel de estado del proyecto y `docs/kan93-documento-tecnico.md`.

---

## 1. Resumen de avance

| Estado | Tareas | % |
|---|---:|---:|
| Finalizado | 58 | 55 % |
| En revisión | 11 | 10 % |
| En curso | 5 | 5 % |
| Por hacer | 31 | 30 % |
| **Total** | **105** | **100 %** |

Más de la mitad del tablero está cerrado. El núcleo del producto (reconocimiento, avisos,
chat de voz, portal, agenda) está entregado; lo pendiente es, sobre todo, validación en
dispositivo, publicación en tienda y verificación de Meta.

## 2. Entregables por área

| Área | Entregado | Estado |
|---|---|---|
| **Gafas (Camera Access)** | Reconocimiento de personas, captura de foto/vídeo, avisos con foto y ubicación, agenda por voz, streaming y segundo plano | Finalizado |
| **Portal Faro Familia** | Paciente, Personas conocidas, Por aclarar, Cuidados, Memoria + chat de voz, Ejercicios, **Agenda** (KAN-104), descargas de APK | Finalizado |
| **Faro Móvil** | Conversar con cámara/micrófono del teléfono (KAN-44); puente móvil→OpenCode (KAN-102) | En revisión |
| **Avisos** | Plantilla aprobada `faro_emergency_alert`, webhook de estados, criterios por dolor/caída/respiración | Finalizado |
| **Agenda** | Backend + tick (KAN-92), sección en el portal (KAN-104), **la IA crea recordatorios** (KAN-97) | Finalizado |
| **Backend / infra** | AURA Care en AWS (CloudFront + EC2), documento técnico (KAN-93), persistencia cifrada de revisiones (KAN-78) | Finalizado |

## 3. Horas imputadas

- **~10 h 5 min** registradas (36.300 s) repartidas en **19 tareas**.
- **Reparto por persona:** 100 % atribuido a **Leo** (registros de imputación retroactiva estimada).
- **Nota:** el trabajo real no está reflejado en su totalidad; solo una parte de las tareas tiene
  horas registradas, por lo que esta cifra es un **mínimo**, no el esfuerzo real.

## 4. Riesgos y bloqueos

1. **Autenticación pública y credenciales expuestas (KAN-31, Highest)** — el portal usa un token de
   desarrollo por defecto y hay claves que rotar. Es el riesgo más alto.
2. **Meta en Development (KAN-89)** — WhatsApp solo entrega a números de prueba hasta pasar a
   **Live** y verificar la empresa; condiciona la producción de los avisos.
3. **Validación en dispositivo pendiente (KAN-99, KAN-100, KAN-101)** — requieren gafas y móvil
   físicos; no pueden cerrarse de forma remota.
4. **Despliegue en EC2** — los cambios en `main` necesitan `git pull` + `systemctl restart` en el
   servidor; no siempre hay acceso desde el puesto de trabajo.
5. **Registro de horas** — dependencia de una sola persona para imputar tiempo.

## 5. Próximos pasos (y responsable)

| Acción | Responsable |
|---|---|
| Desplegar en EC2 lo mergeado en `main` (KAN-104/97/78 entre otros) | Leo |
| Cerrar la autenticación pública y rotar credenciales (KAN-31) | Leo |
| Publicar la app de Meta en **Live** + verificación de empresa (KAN-89) | Leo |
| Pruebas físicas con móvil y gafas (KAN-99, KAN-100, KAN-101) | Jose |
| Ensayo de la demo del **1 de octubre** (KAN-85) y comprobar que todo funciona | Todo el equipo |
| Publicar las apps en Play Store (KAN-63 / KAN-45) | Leo |

## 6. Hito próximo

**Demo del 1 de octubre** (KAN-85): guion y casos de uso ya preparados; hay que ensayarlos y
asegurar sobre dispositivo que todo lo mostrado funciona.
