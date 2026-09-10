# Faro de la Memoria — backend y portal de cuidadores

Una sola cuenta del producto da acceso a la app de las gafas y al portal familiar. AWS, OpenAI y
cualquier otro proveedor son infraestructura interna: el cliente no crea cuentas ni introduce
claves de terceros.

## Ejecución local

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8082
```

Abrir `http://127.0.0.1:8082`. La API local usa `Bearer local-development-only`; producción usa
JWT de Cognito validados por API Gateway.

## Arquitectura SaaS objetivo

- Cuenta Faro: titular, usuario de gafas y cuidadores con roles. Cada cuenta es un `care_circle`
  aislado; ninguna consulta puede cruzar ese identificador.
- Precio mensual fijo e interacciones ilimitadas. El medidor interno registra coste real de AWS y
  OpenAI para optimizar el margen, pero no corta una conversación ni cobra por interacción.
- Cognito gestiona identidad y recuperación de cuenta. API Gateway valida el JWT y aporta
  `account_id`, `care_circle_id` y rol a Lambda.
- Lambda aplica autorización, consentimiento, consenso y auditoría. Lambda es cómputo, no un
  agente de IA.
- Rekognition Collections mantiene una colección por círculo familiar. Recibe bytes directamente
  y conserva vectores; no se crea un bucket S3 de fotografías faciales.
- DynamoDB cifrado con KMS almacena cuentas, membresías, perfiles, revisiones, consentimiento,
  memoria y consumo, siempre particionado por `care_circle_id`.
- OpenAI usa una cuenta empresarial de Faro y claves en Secrets Manager. Recibe solo identidad ya
  confirmada y contexto mínimo; no decide biometría.
- El proveedor de pago se integra con Faro mediante webhooks. Este servicio no almacena tarjetas.

## Economía de precio fijo

El producto evita llamadas innecesarias: detección local, consenso en tres fotogramas, supresión
de anuncios repetidos durante diez minutos, contexto resumido y caché de datos estables. El uso se
mide por cuenta para conocer el coste, ajustar el precio y detectar automatización abusiva, nunca
para limitar el uso humano normal. AWS Budgets alerta al 50/80/100 % del presupuesto global.

## Privacidad y operación

Alta con consentimiento explícito, cinco muestras, revocación y borrado completo. Las identidades
dudosas se mandan al portal y nunca se pronuncian. Antes de producción se requieren DPIA,
condiciones de tratamiento biométrico y validación legal.
