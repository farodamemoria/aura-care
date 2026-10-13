# KAN-69 — Proceso de Q&A y feedback de pilotos

> Objetivo: convertir las pruebas de socios y pilotos en incidencias reproducibles y priorizadas.
> Última actualización: 2026-10-13 (primer ciclo aplicado).

## 1. Plantilla de incidencia de piloto

Cada hallazgo de un piloto se registra como tarea en Jira (proyecto KAN) con esta plantilla:

```
Aplicación:            CameraAccess | Faro Móvil | Faro Familia (PWA/TWA) | Portal web
Versión:               (versión visible en la app o tag/commit)
Dispositivo:           (modelo, versión Android/iOS, gafas conectadas sí/no)
Pasos:                 1. … 2. … 3. …
Resultado esperado:    …
Resultado observado:   …
Evidencia:             captura / vídeo / log (adjunta al ticket)
Severidad:             S1 crítico | S2 mayor | S3 menor | S4 cosmético
Duplicados/enlaces:    KAN-XX (relates to)
Entorno:               producción | piloto | local
```

## 2. Severidades

| Nivel | Criterio | Respuesta |
|---|---|---|
| S1 crítico | La app no arranca, pierde datos o hay riesgo para la persona | Corrección inmediata + aviso al PO |
| S2 mayor | Una función principal falla (voz, alertas, reconocimiento, descarga) | Entra en el sprint en curso |
| S3 menor | Molestia con rodeo disponible (UX, textos, permisos confusos) | Siguiente sprint |
| S4 cosmético | Estética o pulido sin impacto funcional | Backlog |

## 3. Flujo (registro → triaje → sprint)

1. **Registro**: el piloto (o quien prueba) crea la incidencia con la plantilla y evidencia.
2. **Triaje** (mismo día): se etiqueta (`piloto`, `qa`), se fija severidad, se asignan
   responsables y se enlazan duplicados (`relates to`). Si es duplicado, se cierra el nuevo
   apuntando al original.
3. **Revisión de sprint**: cada ciclo de pilotos se revisa en la reunión semanal; las S1/S2
   pasan al sprint, S3/S4 al backlog priorizado.
4. **Cierre**: cada incidencia se cierra solo con prueba en el dispositivo o versión indicada.

## 4. Responsables

| Rol | Persona | Responsabilidad |
|---|---|---|
| Priorización / PO | Leonardo | Decide severidad de negocio y cierra el ciclo |
| Desarrollo | Leo (asistido por IA) | Corrige, despliega y adjunta evidencias de la corrección |
| Pruebas físicas | Jose | Pruebas con gafas y móvil reales |
| UX / portal | Bibiana | Revisión de usabilidad y contenido del portal |

## 5. Primer ciclo aplicado (2026-10-13)

| App | Versión | Dispositivo | Resultado | Incidencias enlazadas |
|---|---|---|---|---|
| CameraAccess (gafas) | 1.0 (build KAN-112) | Pixel 9 Pro | Instala y arranca; UI correcta. Conexión con gafas pendiente (en camino) y voz bloqueada por créditos | KAN-112, KAN-134, KAN-135 |
| Faro Móvil | 0.1-mvp+kan127 | Pixel 9 Pro | Instala y arranca; emparejada; estado vacío y botones correctos. Reapertura de cámara corregida (pendiente ciclo de 3 análisis); voz bloqueada por créditos | KAN-68, KAN-127, KAN-135 |
| Faro Familia (web/TWA) | PWA (app.css v3, token v7) | Chrome / TWA Android | Cabecera ya no choca con la barra de estado (KAN-126 desplegado); descarga de Faro Puente operativa (200). Micrófono de la app reporta sin permisos (abierto) | KAN-126, KAN-116, KAN-128 |

Observaciones del ciclo:
- La caída de voz es transversal a las tres apps: causa única **OpenAI sin créditos** (KAN-135).
- Las pruebas de cámara/reconocimiento en Faro Móvil quedan a expensas de restablecer la voz.

## 6. Criterios de cierre de KAN-69

- [x] Plantilla publicada (este documento).
- [x] Responsables definidos.
- [x] Primer ciclo aplicado a CameraAccess, Faro Móvil y Faro Familia con incidencias enlazadas.
