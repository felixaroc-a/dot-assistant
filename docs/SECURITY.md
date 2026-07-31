# Política de seguridad — Nordik-IA

## Reportar vulnerabilidades

Envíe un informe privado al equipo de desarrollo con:

- Descripción del impacto
- Pasos de reproducción
- Versión afectada (commit o tag)
- PoC si es posible (sin datos reales de usuarios)

## Secretos

- **Nunca** commitear `client_secret.json`, `firebase-service-account.json`, `.env` con claves reales.
- Rotar credenciales si hubo exposición: ver [CREDENTIALS_ROTATION.md](./CREDENTIALS_ROTATION.md).

## Despliegue seguro

1. `NORDIK_ENV=production`
2. `JWT_PRIVATE_KEY_PEM` + `JWT_PUBLIC_KEY_PEM` (RS256)
3. `CORS_ALLOW_ORIGINS` con orígenes explícitos
4. HTTPS con certificado válido
5. `NORDIK_API_TLS_PIN_SHA256` en cliente Electron (opcional)
6. Firmar instaladores (Authenticode / Apple notarization)

## Dependencias

```bash
cd frontend && npm audit
cd frontend/backend && pip audit  # o safety check
```

## Modelo de amenazas

Ver [THREAT_MODEL.md](./THREAT_MODEL.md).
