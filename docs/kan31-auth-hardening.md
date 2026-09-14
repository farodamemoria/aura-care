# KAN-31 — Endurecimiento de autenticación (evidencia local)

Fecha: 2026-09-14. Alcance: backend `aura-care` (API FastAPI) y portal `web/`.
Sin secretos: este documento no incluye valores de credenciales.

## Problema

`app/main.py` conservaba un token de desarrollo conocido como valor por defecto
(`AURA_LOCAL_TOKEN` con fallback) y el portal `web/assets/app.js` lo incrustaba
como token inicial. Cualquiera con ese valor literal podía autenticarse.

## Cambios aplicados

1. **Backend — fallo cerrado.** Se elimina el token por defecto. `require_auth`
   ahora exige `AURA_LOCAL_TOKEN` configurado y compara en tiempo constante
   (`hmac.compare_digest`). Sin configuración, ninguna petición se autoriza.
2. **Backend — derivación de credenciales.** `credential_hash` exige
   `AURA_CREDENTIAL_PEPPER`; si falta, responde `503`. Ya no cae de vuelta al
   token de desarrollo.
3. **Portal — sin token incrustado.** `web/assets/app.js` ya no contiene un token
   por defecto. Usa el `auraToken` guardado en `localStorage`; admite
   inicializarlo una vez vía `?token=...` en la URL.

## Configuración requerida antes de desplegar

En el servicio `aura-backend` (ver `CONTEXT.md` §4):

- `AURA_LOCAL_TOKEN` = token fuerte y aleatorio (renovado).
- `AURA_CREDENTIAL_PEPPER` = pepper fuerte y aleatorio.

Sin ambas variables el backend devuelve `401` en los endpoints protegidos.

## Pruebas automáticas

`tests/test_auth_hardening.py` (pytest). Resultado local:

```
30 passed
```

Casos cubiertos:

- endpoints sensibles rechazan petición anónima (401);
- el token de desarrollo conocido es rechazado en todos los endpoints sensibles (401);
- bearer inválido y esquema no-Bearer rechazados (401);
- bearer válido aceptado (200);
- sin `AURA_LOCAL_TOKEN`, el fallo es cerrado incluso con el token histórico;
- `credential_hash` sin pepper falla; nunca usa el token de desarrollo; depende del pepper;
- el código (`app/main.py`, `web/assets/app.js`) no contiene el token histórico.

## Auditoría de repositorio

`scripts/audit-repository-secrets.ps1` revisa los ficheros rastreados por Git
buscando el token histórico y patrones de credenciales, sin imprimir valores.

## Pendiente (fuera del alcance puramente local)

- **Rotar** la clave de OpenAI expuesta en un canal de soporte y sustituirla en
  `/etc/faro/realtime.env` y `/etc/aura-backend/openai.env`, reiniciando servicios.
- **Desplegar** el backend con `AURA_LOCAL_TOKEN` y `AURA_CREDENTIAL_PEPPER`.
- **Aislamiento por círculo familiar** (Cognito/JWT o equivalente): hoy el
  repositorio es global; requiere diseño de multi-familia.
- **Verificación externa** desde CloudFront de que el token histórico ya no
  autoriza ningún endpoint.
