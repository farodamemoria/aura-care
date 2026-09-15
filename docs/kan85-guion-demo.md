# KAN-85 — Guion y casos de uso de la demo (1 de octubre de 2026)

Responsable de la demo: **Leo** · Apoyo técnico: DeepSeek (opencode) · Estado: guion listo para ensayar.

Objetivo: mostrar Faro de punta a punta (portal + voz + gafas + avisos) con casos reales,
y garantizar que todo lo que se muestra funciona el día de la demo.

## 1. Preparación

### Checklist de la víspera

- [ ] Verificación técnica en verde: `python scripts/kan85_verificar_demo.py` (portal, salud, versión y descargas).
- [ ] Suite del repositorio en verde: `python -m pytest -q`.
- [ ] Gafas cargadas y emparejadas con la app de Meta en el móvil del paciente.
- [ ] Camera Access / Faro Móvil instaladas y probadas en el móvil.
- [ ] Portal abierto y con sesión iniciada en el navegador del presentador.
- [ ] Red de cuidados: teléfono de pruebas añadido, con consentimiento marcado y prioridad 1.
- [ ] WhatsApp: número de pruebas listo. **Limitación**: en Development solo entrega a números
      de prueba; para números reales hace falta KAN-89 (Live + verificación de empresa).
- [ ] Guion impreso o abierto en el móvil.

### Checklist 30 minutos antes

- [ ] WiFi/4G estables; notificaciones y llamadas silenciadas.
- [ ] Volumen alto en el móvil y en el altavoz; brillo subido.
- [ ] Baterías por encima del 50 %: gafas, móvil y portátil.
- [ ] Ensayo rápido del caso 2 (voz) y del caso 6 (descargas).
- [ ] Plan B a mano: capturas de avisos ya recibidos por si falla la red.

## 2. Casos de uso

Cada caso incluye **Objetivo**, **Preparación**, **Pasos**, **Resultado esperado**, **Plan B** y el mensaje para el público.

### Caso 1 — El portal familiar (Faro Familia)

- **Objetivo**: mostrar que la familia tiene todo en un solo sitio.
- **Preparación**: portal abierto en `https://d2n7ih9kfxbzvd.cloudfront.net`.
- **Pasos**:
  1. Mostrar el resumen superior: personas conocidas, por identificar y contactos preparados.
  2. Repasar las pestañas: Paciente, Personas conocidas, Por aclarar, Cuidados y Memoria.
  3. Abrir la ficha del paciente y la red de cuidados (prioridad y estado de avisos).
- **Resultado esperado**: datos reales cargados y el indicador de conexión en verde.
- **Plan B**: si el portal no cargase, mostrar capturas y continuar con las gafas.
- **Mensaje**: «Todo el círculo de cuidados cabe en el móvil, sin instalar nada».

### Caso 2 — Hablar con Faro por voz (Memoria)

- **Objetivo**: demostrar la memoria conversacional y la respuesta leída en voz alta.
- **Preparación**: pestaña Memoria abierta; micrófono permitido en el navegador.
- **Pasos**:
  1. Pulsar «🎤 Hablar» y preguntar: «¿Cómo ha ido hoy?».
  2. Faro responde con el resumen del día y lo lee en voz alta; el micrófono sigue activo.
  3. Hacer una segunda pregunta (por ejemplo, «¿Ha visto a alguien?») para mostrar el hilo.
  4. Despedirse («gracias, hasta luego»): Faro se despide y el micrófono se apaga.
  5. Mostrar «Empezar de nuevo» para reiniciar la conversación.
- **Resultado esperado**: respuestas coherentes con los eventos del paciente, sin inventar datos,
  y micro que se apaga al despedirse.
- **Plan B**: si el micro del navegador falla, escribir la pregunta en el cuadro de texto.
- **Mensaje**: «La familia pregunta con su propia voz y Faro contesta con lo que ha acompañado».

### Caso 3 — Las gafas reconocen a una persona conocida

- **Objetivo**: enseñar el reconocimiento prudente y la identificación desde el portal.
- **Preparación**: persona conocida con sus 5 fotos preparadas; gafas emparejadas y puestas.
- **Pasos**:
  1. El paciente mira a la persona preparada; Faro le dice su nombre.
  2. Segunda persona sin fotos preparadas: Faro **no pronuncia ningún nombre** y aparece en
     «Por aclarar» del portal.
  3. Un familiar la identifica en el portal; desde ese momento queda reconocible.
- **Resultado esperado**: nombre correcto en el primer caso; duda prudente y flujo de
  identificación en el segundo.
- **Plan B**: si el reconocimiento en vivo no responde, mostrar las capturas y el flujo de
  «Por aclarar» en el portal.
- **Mensaje**: «Si no está seguro, no lo dice: pide ayuda a la familia. La privacidad primero».

### Caso 4 — Aviso por WhatsApp a la red de cuidados

- **Objetivo**: mostrar que los avisos llegan por WhatsApp, también con el móvil guardado.
- **Preparación**: contacto de pruebas en la red de cuidados; móvil de pruebas a mano.
- **Pasos**:
  1. En el chat de Faro: «Avísame si se cae o se queja de dolor». Faro confirma que el aviso
     queda activo por WhatsApp.
  2. Lanzar la prueba de entrega desde el portátil:
     `curl -s -X POST https://d2n7ih9kfxbzvd.cloudfront.net/v1/alerts/test -H "Authorization: Bearer $AURA_LOCAL_TOKEN"`.
  3. Mostrar el WhatsApp recibido en el móvil de pruebas y el aviso en la línea de tiempo.
- **Resultado esperado**: mensaje con la plantilla `faro_emergency_alert` (tipo y texto) y el
  aviso reflejado en el portal.
- **Plan B**: en Development solo entrega a números de prueba; si no llega, mostrar el mensaje
  ya recibido y explicar KAN-89 (paso a Live).
- **Mensaje**: «El aviso viaja como plantilla aprobada: llega aunque el familiar no esté conectado».

### Caso 5 — Ubicación en tiempo real

- **Objetivo**: mostrar el seguimiento prudente cuando la familia lo necesita.
- **Preparación**: iniciar una sesión de ubicación desde las gafas o el móvil; portal en Memoria.
- **Pasos**:
  1. Mostrar el panel de seguimiento activo en el portal.
  2. Enseñar la ubicación actualizada y la antigüedad del dato.
  3. Detener la sesión y comprobar que el panel desaparece.
- **Resultado esperado**: la ubicación solo se comparte mientras la sesión está activa.
- **Plan B**: usar el último evento de ubicación registrado en la línea de tiempo.
- **Mensaje**: «La ubicación se comparte solo cuando hace falta y se puede cortar en un toque».

### Caso 6 — Descargar las apps desde el portal

- **Objetivo**: mostrar la distribución controlada de las tres aplicaciones.
- **Preparación**: portal abierto en la cabecera (grupo de descargas).
- **Pasos**: pulsar los botones «⬇ Faro Familia», «⬇ App gafas» y «⬇ Faro Móvil».
- **Resultado esperado**: las tres descargas comienzan (verificado el 2026-09-15: 200 en los
  tres enlaces).
- **Plan B**: si la red va lenta, no esperar a que terminen: enseñar que el enlace funciona.
- **Mensaje**: «Cada persona instala solo lo que necesita, desde el propio portal».

## 3. Guion hablado (sugerencia)

- Apertura: «Faro da Memoria acompaña a personas con pérdida de memoria con unas gafas y un
  portal para la familia. Todo lo que vais a ver está funcionando ahora mismo».
- Caso 1: «Empezamos por el portal: aquí vive el círculo de cuidados».
- Caso 2: «La familia no rellena formularios: pregunta y Faro responde».
- Caso 3: «Faro reconoce a quien conoce y, si duda, no inventa: pregunta a la familia».
- Caso 4: «Y si pasa algo importante, el aviso sale por WhatsApp con contexto».
- Caso 5: «Si se desorienta, la familia puede ver dónde está, solo mientras haga falta».
- Caso 6: «Cada app se descarga desde el portal».
- Cierre: «Privacidad, avisos prudentes y la familia en el centro».

## 4. Verificación técnica (2026-09-15)

| Comprobación | Resultado |
| --- | --- |
| Portal `/` | 200 · «Faro Familia» presente |
| Salud `/health` | `status: ok` · proveedor WhatsApp (Meta) activo |
| Versión `/v1/version` | `family_conversation`, `family_ai`, `location_tracking`, `family_alerts`, `care_network_management`, `events` |
| Instalación `/.well-known/assetlinks.json` | 200 (TWA a pantalla completa) |
| Descarga `/download/faro.apk` | 200 · 2,6 MB |
| Descarga `/download/camera-access.apk` | 200 · 132,0 MB |
| Descarga `/download/faro-movil.apk` | 200 · 16,3 MB |
| Suite del repositorio | 45/45 PASS |

Reproducible con `python scripts/kan85_verificar_demo.py` (no necesita token).

## 5. Lo que aún requiere ensayo con hardware

- Caso 2: audio y latencia reales del micro y de la voz.
- Caso 3: reconocimiento con las gafas y las personas preparadas.
- Caso 4: entrega real del WhatsApp (número de prueba o KAN-89 completado).
- Caso 5: ubicación en vivo desde las gafas o el móvil.

## 6. Ensayos

- Ensayo 1 (técnico, 20 min): recorrer los 6 casos seguidos y cronometrar (objetivo: menos de 12 minutos).
- Ensayo 2 (general, 30 min): simular público, practicar el guion hablado y los planes B.
