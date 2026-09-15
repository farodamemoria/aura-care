# KAN-81 — Reparto de tareas entre asistentes de IA

> Actualizado: 2026-09-15 · Fuente: Jira KAN — tareas abiertas al 2026-09-15

Repartir las tareas pendientes (estado «Por hacer») del proyecto Faro da Memoria entre los asistentes de IA disponibles (Amazon Quick, GitHub Copilot Pro, DeepSeek/opencode y Gemini Pro) y Leo (titular), con un brief listo para ejecutar cada una.

## Herramientas y accesos

### DeepSeek (opencode)

- **Fortaleza:** Backend y portal de aura-care (FastAPI + web), incidencias de código, tests locales, automatización de Jira y despliegue.
- **Acceso:** Repos locales aura-care y android; token de Jira; puede ejecutar pytest y desplegar en la EC2.

### GitHub Copilot Pro

- **Fortaleza:** Cambios de código en los repos de GitHub (app Android de las gafas, Faro Móvil y web) con ramas y PR.
- **Acceso:** Cuenta GitHub farodamemoria y repos aura-care y android; siempre vía rama + PR, nunca push directo a main.

### Gemini Pro

- **Fortaleza:** Documentos largos, investigación, guiones de demo, contenidos de negocio y revisión del dossier.
- **Acceso:** CONTEXT.md, README y el dossier de C:\ia; salida en docs/ del repo o Google Docs.

### Amazon Quick

- **Fortaleza:** Investigación de producto y hardware, ecosistema AWS y Alexa, comparativas con enlaces, precios y disponibilidad.
- **Acceso:** Cuenta AWS del proyecto (Rekognition, Lambda) y navegación web.

### Leo (humano)

- **Fortaleza:** Cuentas (OpenAI, Meta, Google Play, Apple), hardware real, pruebas con personas, reuniones institucionales y validaciones legales.
- **Acceso:** Cuentas y dispositivos del proyecto; aprueba y valida el trabajo de los agentes.

## Resumen del reparto

| Clave | Prioridad | Creada | Tarea | Responsable |
| --- | --- | --- | --- | --- |
| KAN-40 | Highest | 2026-08-26 | Memoria visual de objetos y ayuda para encontrarlos | DeepSeek (opencode) |
| KAN-50 | Highest | 2026-08-31 | Gestión de medicación: pautas, recordatorios, confirmación y escalado | DeepSeek (opencode) |
| KAN-51 | Highest | 2026-08-31 | Zonas seguras y geocercas con seguimiento y escalado por desorientación | DeepSeek (opencode) |
| KAN-52 | Highest | 2026-08-31 | Detectar que el paciente no lleva las gafas y activar recordatorio o aviso | GitHub Copilot Pro |
| KAN-77 | Highest | 2026-09-08 | Ejercicios cognitivos personalizados basados en recuerdos verificados | DeepSeek (opencode) |
| KAN-85 | Highest | 2026-09-10 | Demo del 1 de octubre: guion y casos de uso, practicar y verificar | Gemini Pro |
| KAN-93 | Highest | 2026-09-14 | Documento técnico de cómo están fabricadas las dos aplicaciones y las webs | Gemini Pro |
| KAN-61 | High | 2026-08-31 | Las fotos almacenadas (paciente, conocidos, familiares…) deben verse en la ficha (las 5) | GitHub Copilot Pro |
| KAN-92 | High | 2026-09-14 | Calendario con recordatorios (medicación, rutinas, citas) en Faro Familia y por voz en las gafas | DeepSeek (opencode) |
| KAN-95 | High | 2026-09-15 | Incidencia: botones de descarga de APK mal posicionados y solapados en la web | GitHub Copilot Pro |
| KAN-97 | High | 2026-09-15 | La IA crea agendas para el paciente y familiares a partir de la memoria y el calendario | DeepSeek (opencode) |
| KAN-6 | Medium | 2026-08-20 | Crear API key para la conexión de OpenAI | Leo (humano) |
| KAN-41 | Medium | 2026-08-26 | Mejorar precisión y actualización progresiva de la ubicación en alertas | DeepSeek (opencode) |
| KAN-67 | Medium | 2026-09-07 | Sugerir identidad probable de personas por identificar usando el contexto de conversación | DeepSeek (opencode) |
| KAN-68 | Medium | 2026-09-07 | Incidencia Faro Móvil: la cámara se reabre después de cada análisis | GitHub Copilot Pro |
| KAN-69 | Medium | 2026-09-07 | Crear un proceso de Q&A y feedback de pilotos por aplicación y versión | Gemini Pro |
| KAN-70 | Medium | 2026-09-07 | Gestionar alianzas y reuniones institucionales y clínicas de Faro | Leo (humano) |
| KAN-75 | Medium | 2026-09-07 | Visualización remota segura de gafas, móvil y cámaras desde Faro Familia | DeepSeek (opencode) |
| KAN-78 | Medium | 2026-09-08 | Persistir Personas por aclarar y sus imágenes de forma segura | DeepSeek (opencode) |
| KAN-79 | Medium | 2026-09-09 | Prever fugas de casa: detectar puerta y verificar con cámaras si el paciente puede perderse | DeepSeek (opencode) |
| KAN-89 | Medium | 2026-09-11 | Publicar la app de Meta en Live + verificación de empresa (WhatsApp en producción) | Leo (humano) |
| KAN-91 | Medium | 2026-09-13 | Realizar una prueba integral con personas | Leo (humano) |
| KAN-37 | Low | 2026-08-26 | Panel longitudinal de crisis, riesgos y evolución del paciente | DeepSeek (opencode) |
| KAN-43 | Low | 2026-08-26 | Sustituir logos genéricos por la identidad visual de Faro da Memoria | GitHub Copilot Pro |
| KAN-45 | Low | 2026-08-28 | Distribuir Faro Móvil mediante Google Play en pruebas internas | Leo (humano) |
| KAN-53 | Low | 2026-08-31 | Integrar cámaras locales RTSP/ONVIF para caídas, peligros y objetos perdidos | DeepSeek (opencode) |
| KAN-54 | Low | 2026-08-31 | Integrar altavoz inteligente como canal de respaldo cuando no se usan las gafas | Amazon Quick |
| KAN-55 | Low | 2026-08-31 | Estudio de hardware asistencial: ergonomía, térmica, graduación e indicador de grabación | Amazon Quick |
| KAN-56 | Low | 2026-08-31 | Mapa de competencia, estado del arte y evidencia de innovación | Gemini Pro |
| KAN-59 | Low | 2026-08-31 | Definir kits de producto, licencias, costes y modelo comercial | Gemini Pro |
| KAN-63 | Low | 2026-09-01 | Disponer de las dos apps principales en Play Store | Leo (humano) |
| KAN-72 | Low | 2026-09-07 | Autocompletar y validar país, provincia, localidad y dirección en las fichas | GitHub Copilot Pro |
| KAN-73 | Low | 2026-09-07 | Protocolo para pedir ayuda a terceros y contactar con el familiar prioritario | DeepSeek (opencode) |
| KAN-82 | Low | 2026-09-09 | Recomendar cámara, Home Assistant y pulsera de ubicación con SDK abierto para vincular a la IA | Amazon Quick |
| KAN-26 | Lowest | 2026-08-26 | Mejorar front de conexión con las gafas: identidad corporativa y UX/UI | GitHub Copilot Pro |
| KAN-34 | Lowest | 2026-08-26 | Agrupar la línea de tiempo de eventos por día y hora | GitHub Copilot Pro |
| KAN-38 | Lowest | 2026-08-26 | Identidad de marca blanca de Faro da Memoria en voz, interfaz y errores | GitHub Copilot Pro |
| KAN-64 | Lowest | 2026-09-01 | Crear la versión para Apple | Leo (humano) |
| KAN-65 | Lowest | 2026-09-01 | Revisar la configuración en Meta y ver si hay que complementar algo más | Leo (humano) |

## Briefs por herramienta

Copiar el brief de cada tarea en la herramienta correspondiente.

### DeepSeek (opencode)

#### KAN-40 — Memoria visual de objetos y ayuda para encontrarlos

En aura-care: registrar objetos vistos por las gafas (tipo recuerdo de objeto) y permitir buscarlos desde el chat familiar. Reutilizar memories y /v1/family/ask. DoD: endpoints con tests y respuesta del chat con el último lugar donde se vio el objeto. Flujo CONTEXT.md: rama KAN-40-memoria-objetos + PR.

#### KAN-50 — Gestión de medicación: pautas, recordatorios, confirmación y escalado

En aura-care: pautas de medicación por paciente (pauta, dosis, horarios), recordatorio y confirmación; si no hay confirmación, escalar a la red de cuidados con los avisos existentes (plantilla faro_emergency_alert). DoD: endpoints + tests; aviso registrado y deduplicado.

#### KAN-51 — Zonas seguras y geocercas con seguimiento y escalado por desorientación

En aura-care: zonas seguras por paciente sobre location-sessions; detectar salida de zona y escalar con aviso preventivo. DoD: cálculo dentro/fuera con tests y aviso con mensaje prudente (sin diagnósticos).

#### KAN-77 — Ejercicios cognitivos personalizados basados en recuerdos verificados

En aura-care: generar ejercicios cognitivos a partir de memorias verificadas y añadir su sección en Faro Familia (portal web) con resultados. DoD: endpoints + UI + tests; sin diagnósticos ni valoraciones clínicas.

#### KAN-92 — Calendario con recordatorios (medicación, rutinas, citas) en Faro Familia y por voz en las gafas

En aura-care: CRUD de calendario y recordatorios en el portal; consulta por voz desde las gafas y desde el chat familiar. DoD: endpoints + UI + tests; zona horaria Europe/Madrid.

#### KAN-97 — La IA crea agendas para el paciente y familiares a partir de la memoria y el calendario

En aura-care: que el chat familiar use la memoria conversacional y el calendario (KAN-92) para crear y recordar agendas de paciente y familiares. Depende de KAN-92. DoD: función de agenda con tests; sin inventar datos ni ofrecer funciones inexistentes.

#### KAN-41 — Mejorar precisión y actualización progresiva de la ubicación en alertas

En aura-care: mejorar la ubicación de las alertas (sesión activa + última conocida + marca de antigüedad y precisión). DoD: tests del cálculo y enlace de mapa en los avisos.

#### KAN-67 — Sugerir identidad probable de personas por identificar usando el contexto de conversación

En aura-care: proponer identidad probable de una persona por aclarar combinando el nombre mencionado en la conversación con los candidatos de Rekognition (faro-faces). DoD: endpoint/consulta con tests; nunca afirmar una identidad dudosa (inferencia ≠ certeza).

#### KAN-75 — Visualización remota segura de gafas, móvil y cámaras desde Faro Familia

En aura-care: visualización remota con token de corta vida, consentimiento y auditoría (imagen de gafas/móvil y cámaras autorizadas) desde el portal. DoD: endpoints + UI + tests con registro de auditoría y revocación.

#### KAN-78 — Persistir Personas por aclarar y sus imágenes de forma segura

En aura-care: persistir las Personas por aclarar y sus imágenes con retención y borrado seguro; acceso solo con token del círculo. DoD: endpoints con tests y revisión de privacidad (minimización).

#### KAN-79 — Prever fugas de casa: detectar puerta y verificar con cámaras si el paciente puede perderse

En aura-care: motor que ante un audio de puerta verifique con las cámaras conectadas si el paciente puede estar saliendo (aunque no lleve las gafas) y avise a la red de cuidados. DoD: motor con tests incluidos falsos positivos y mensajes prudentes.

#### KAN-37 — Panel longitudinal de crisis, riesgos y evolución del paciente

En aura-care: panel longitudinal con agregados por día/semana de eventos y avisos (crisis, riesgos y evolución). DoD: endpoints + sección web + tests.

#### KAN-53 — Integrar cámaras locales RTSP/ONVIF para caídas, peligros y objetos perdidos

En aura-care: adaptador para cámaras locales RTSP/ONVIF (Home Assistant/Frigate), con la elección de hardware de KAN-82; detección de caídas, peligros y objetos. DoD: adaptador con tests simulados y aviso a la red de cuidados.

#### KAN-73 — Protocolo para pedir ayuda a terceros y contactar con el familiar prioritario

En aura-care: protocolo de ayuda con orden de la red de cuidados y reglas de escalado (contacto prioritario primero, después el resto). DoD: lógica con tests y aviso al contacto prioritario.

### GitHub Copilot Pro

#### KAN-52 — Detectar que el paciente no lleva las gafas y activar recordatorio o aviso

En el repo android (app de las gafas, Meta DAT SDK): detectar falta de uso (sin conexión o sin eventos) y lanzar recordatorio al paciente; si se prolonga, aviso a la familia vía API de aura-care. DoD: PR con la lógica y nota de prueba manual con las gafas.

#### KAN-61 — Las fotos almacenadas (paciente, conocidos, familiares…) deben verse en la ficha (las 5)

En aura-care (backend + portal): mostrar en la ficha las 5 fotos almacenadas de cada persona (perfil y muestras faciales). DoD: endpoints/UI + tests; sin exponer imágenes sin token.

#### KAN-95 — Incidencia: botones de descarga de APK mal posicionados y solapados en la web

En aura-care/web: revisar la corrección del commit 18ca56b y terminar de colocar los botones de descarga sin solapes en móvil y escritorio; subir app.js?v=NN y la caché del service worker. DoD: capturas antes/después y suite del repo en verde.

#### KAN-68 — Incidencia Faro Móvil: la cámara se reabre después de cada análisis

En la app Faro Móvil: corregir el ciclo de vida de la cámara para que no se reabra tras cada análisis (cerrar/reabrir solo con acción del usuario). DoD: PR con la corrección y pasos de prueba manual.

#### KAN-43 — Sustituir logos genéricos por la identidad visual de Faro da Memoria

En aura-care/web: sustituir los logos genéricos por la identidad visual de Faro (assets del dossier de C:\ia; pedir a Leo si falta algún formato). DoD: PR con capturas de las pantallas afectadas.

#### KAN-72 — Autocompletar y validar país, provincia, localidad y dirección en las fichas

En aura-care (portal): autocompletar y validar país, provincia, localidad y dirección con catálogo local, sin servicios de pago. DoD: validación con tests y sin romper fichas existentes.

#### KAN-26 — Mejorar front de conexión con las gafas: identidad corporativa y UX/UI

En aura-care/web: mejorar el front de conexión con las gafas con la identidad corporativa y UX/UI clara para personas mayores. DoD: PR con capturas y sin romper el flujo de emparejamiento.

#### KAN-34 — Agrupar la línea de tiempo de eventos por día y hora

En aura-care/web: agrupar la línea de tiempo de eventos por día y hora con encabezados claros. DoD: UI + tests y caché del service worker actualizada.

#### KAN-38 — Identidad de marca blanca de Faro da Memoria en voz, interfaz y errores

En aura-care y apps: aplicar la identidad de marca blanca en voz, interfaz y mensajes de error (tono cercano, nombres correctos, sin tecnicismos). Coordinar con la guía de marca; DoD: PR revisable + tests de textos.

### Gemini Pro

#### KAN-85 — Demo del 1 de octubre: guion y casos de uso, practicar y verificar

Crear el guion de la demo del 1 de octubre y los casos de uso a mostrar, con un guion de práctica para Leo y una checklist de «todo funciona el día de la demo». Entregable: docs/kan85-guion-demo.md en aura-care (rama KAN-85-guion-demo + PR) o Google Doc equivalente.

#### KAN-93 — Documento técnico de cómo están fabricadas las dos aplicaciones y las webs

Redactar el documento técnico (stack, repos, módulos, despliegue, flujos y diagramas) de la app de gafas, Faro Móvil y las webs. Fuentes: CONTEXT.md, README y código. Entregable: docs/kan93-documento-tecnico.md.

#### KAN-69 — Crear un proceso de Q&A y feedback de pilotos por aplicación y versión

Diseñar el proceso de pruebas y feedback de pilotos por aplicación y versión: plantillas de encuesta, criterios de aceptación por caso y registro de resultados. Entregable: docs/kan69-proceso-qa-pilotos.md + plantillas.

#### KAN-56 — Mapa de competencia, estado del arte y evidencia de innovación

Mapa de competencia (CrossSense/Wispy, CareYaya, etc.), estado del arte y evidencia de innovación con fuentes verificables. Entregable: docs/kan56-competencia.md listo para la candidatura a la Xunta.

#### KAN-59 — Definir kits de producto, licencias, costes y modelo comercial

Definir los 3 kits (Básico, Intermedio, Avanzado), licencias, costes y modelo comercial con las tarifas 49/79/99 € y el punto de equilibrio (~351 círculos). Entregable: doc de negocio con hoja de cálculo resumen.

### Amazon Quick

#### KAN-54 — Integrar altavoz inteligente como canal de respaldo cuando no se usan las gafas

Diseñar la integración con altavoz inteligente (Alexa) como canal de respaldo: skill, rutinas, avisos y límites. Entregable: plan de integración con pasos de configuración; la parte de API la implementa DeepSeek después.

#### KAN-55 — Estudio de hardware asistencial: ergonomía, térmica, graduación e indicador de grabación

Estudio de hardware: ergonomía y peso <15 g, gestión térmica, graduación (clip-on/insertos RX) e indicador LED de grabación obligatorio. Entregable: informe con opciones, costes y recomendación.

#### KAN-82 — Recomendar cámara, Home Assistant y pulsera de ubicación con SDK abierto para vincular a la IA

Investigar y recomendar cámara (Reolink/Hikvision), Home Assistant y pulsera BLE de ubicación con SDK abierto y compatibles con Faro. Entregable: comparativa con enlaces, precios, SDK y requisitos de integración.

### Leo (humano)

#### KAN-6 — Crear API key para la conexión de OpenAI

Crear la API key de OpenAI con la cuenta titular y guardarla como secreto de Faro (AWS Secrets Manager o /etc/aura-backend/openai.env en la EC2); no subirla nunca a Git. DoD: servicio con la clave configurada y prueba de conexión correcta.

#### KAN-70 — Gestionar alianzas y reuniones institucionales y clínicas de Faro

Contactar y agendar reuniones con la Xunta, clúster de salud y centros interesados; registrar acuerdos y próximos pasos. DoD: agenda de reuniones y resumen de cada una.

#### KAN-89 — Publicar la app de Meta en Live + verificación de empresa (WhatsApp en producción)

Completar en el panel de Meta la verificación de empresa y pasar la app a Live para que WhatsApp entregue a números reales (plantilla faro_emergency_alert). DoD: app en Live y prueba de aviso recibida en un número real.

#### KAN-91 — Realizar una prueba integral con personas

Coordinar la prueba con personas (20-30 participantes, 3 meses): consentimientos RGPD, calendario y registro de incidencias; apoyarse en el guion de KAN-85 y en el proceso de KAN-69. DoD: informe inicial de la prueba.

#### KAN-45 — Distribuir Faro Móvil mediante Google Play en pruebas internas

Publicar Faro Móvil en el canal de pruebas internas de Google Play: cuenta de organización, subir el AAB (lo prepara Copilot Pro) y lista de testers. DoD: enlace de pruebas internas funcionando.

#### KAN-63 — Disponer de las dos apps principales en Play Store

Publicar las dos apps principales en Play Store: cuenta de organización, fichas, política de privacidad y revisión (los builds los preparan Copilot Pro/DeepSeek). DoD: apps publicadas o en revisión con enlace.

#### KAN-64 — Crear la versión para Apple

Decidir y preparar la versión para Apple (requiere Mac y cuenta Apple Developer; evaluar alternativa PWA). DoD: decisión documentada y plan con costes.

#### KAN-65 — Revisar la configuración en Meta y ver si hay que complementar algo más

Revisar la app de Meta (permisos, webhooks, suscripciones, DAT SDK) y completar lo que falte; apoyarse en la checklist de KAN-89. DoD: checklist completada en el panel de Meta.

## Tareas no delegadas ahora

| Clave | Estado | Motivo |
| --- | --- | --- |
| KAN-30 | En curso | En curso: no reasignar; terminar y pasar a revisión. |
| KAN-36 | En curso | En curso: no reasignar; terminar y pasar a revisión. |
| KAN-60 | En curso | En curso: no reasignar; terminar y pasar a revisión. |
| KAN-66 | En curso | En curso: no reasignar; terminar y pasar a revisión. |
| KAN-31 | En revisión | En revisión: pendiente de validación del PO. |
| KAN-33 | En revisión | En revisión: pendiente de validación del PO. |
| KAN-35 | En revisión | En revisión: pendiente de validación del PO. |
| KAN-39 | En revisión | En revisión: pendiente de validación del PO. |
| KAN-44 | En revisión | En revisión: pendiente de validación del PO. |
| KAN-62 | En revisión | En revisión: pendiente de validación del PO. |
| KAN-81 | En revisión | Es esta misma tarea de gestión del reparto. |
| KAN-84 | En revisión | En revisión: pendiente de validación del PO. |
| KAN-86 | En revisión | En revisión: pendiente de validación del PO. |
| KAN-87 | En revisión | En revisión: pendiente de validación del PO. |
| KAN-96 | En revisión | En revisión: pendiente de validación del PO. |

## Flujo de trabajo

- Una tarea de Jira = una rama KAN-XX-descripcion. Nunca se empuja directo a main.
- Cada cambio pasa por Pull Request a main; el merge se hace cuando los tests del repo pasan al 100 %.
- Registrar en Jira el resultado: comentario, etiqueta del agente y estado correspondiente.
- No subir secretos ni builds a Git (.env, *.keystore, __pycache__/, app/build/, *.db).
- Leer CONTEXT.md (y android/CONTEXT.md si aplica) antes de tocar un repositorio.

## Cómo mantener este plan

1. Editar `docs/kan81-delegacion.json` (tareas, responsables o briefs).
2. Regenerar el Markdown: `python scripts/kan81_generar_plan.py`.
3. Ejecutar `python -m pytest tests/test_kan81_delegacion.py` para validar que el plan sigue completo y que el Markdown coincide.
