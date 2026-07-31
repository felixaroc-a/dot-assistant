# Checklist de salida a produccion — Nordik + OpenClaw

## Instrucciones
- Cada item debe ser verificado y marcado antes del deploy a produccion.
- Si un item es bloqueante (B) y falla, no se puede hacer deploy.
- Si un item es recomendado (R), se puede deployar con deuda tecnica documentada.

---

## 1. Seguridad y autenticacion

| # | Item | Tipo | Verificado | Notas |
|---|------|------|------------|-------|
| 1.1 | JWT usa RS256 (no HS256) en produccion | B | [ ] | `JWT_PRIVATE_KEY_PEM` + `JWT_PUBLIC_KEY_PEM` configurados |
| 1.2 | `NORDIK_ENV=production` en backend | B | [ ] | Desactiva docs, OAuth dev, warnings |
| 1.3 | `ALLOW_OAUTH_DEV_WITHOUT_FIREBASE_AUTH` esta vacio o ausente | B | [ ] | Prohibido en produccion |
| 1.4 | `TOKEN_ENCRYPTION_KEY` generada con Fernet | B | [ ] | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| 1.5 | `HARDWARE_TOKEN_PEPPER` = mismo valor en `frontend/backend` y `auto-venta1` | B | [ ] | Si no coinciden, login con pendrive falla |
| 1.6 | `CORS_ALLOW_ORIGINS` lista explicita (sin `*`) | B | [ ] | |
| 1.7 | HTTPS con certificado valido | B | [ ] | |
| 1.8 | Firebase service account NO esta en el repo | B | [ ] | Ruta en `FIREBASE_SERVICE_ACCOUNT_PATH` |
| 1.9 | `client_secret.json` NO esta en el repo | B | [ ] | Ruta en `GOOGLE_CLIENT_SECRETS_PATH` apunta a `infra/credentials/client_secret.json` |
| 1.10 | Rate limiting activo en todos los endpoints | B | [ ] | SlowAPI configurado en main.py |
| 1.11 | CSP headers configurados en Electron y API | B | [ ] | `Content-Security-Policy` en main.cjs |
| 1.12 | Refresh token rotation + deteccion de reuso activa | B | [ ] | `auth_service.refresh_session` |

## 2. Base de datos y persistencia

| # | Item | Tipo | Verificado | Notas |
|---|------|------|------------|-------|
| 2.1 | `DATABASE_URL` apunta a Postgres produccion (no SQLite) | B | [ ] | |
| 2.2 | Tabla `subscription_reminder_outbox` creada | B | [ ] | Ver `infra/billing/schema.sql` |
| 2.3 | Migracion de claves a bcrypt ejecutada | B | [ ] | `scripts/migrate_clave_acceso_hash.py` |
| 2.4 | Indices creados en `fecha_vencimiento`, `correo`, `telefono` | R | [ ] | |
| 2.5 | Backup automatizado de Postgres configurado | R | [ ] | |

## 3. Meta WhatsApp (Chatbot-Cobro)

| # | Item | Tipo | Verificado | Notas |
|---|------|------|------------|-------|
| 3.1 | `META_ACCESS_TOKEN` valido y con permisos | B | [ ] | |
| 3.2 | `META_PHONE_NUMBER_ID` correcto | B | [ ] | |
| 3.3 | `META_WEBHOOK_VERIFY_TOKEN` configurado | B | [ ] | |
| 3.4 | `META_APP_SECRET` configurado (firma HMAC) | B | [ ] | |
| 3.5 | `REMINDER_TEMPLATE_NAME` aprobado en Meta Business | B | [ ] | |
| 3.6 | `NODE_ENV=production` en Chatbot-Cobro | B | [ ] | |
| 3.7 | `REMINDER_OWNER=chatbot-cobro` en auto-venta1 | R | [ ] | Evita duplicacion de recordatorios |

## 4. Panel admin (auto-venta1)

| # | Item | Tipo | Verificado | Notas |
|---|------|------|------------|-------|
| 4.1 | Panel tiene autenticacion (usuario/contraseña o SSO) | B | [ ] | Hoy es interno sin login |
| 4.2 | `ADMIN_API_KEY` generada y configurada | B | [ ] | |
| 4.3 | `SESSION_SECRET` generado | B | [ ] | |
| 4.4 | `REPOSITORY_BACKEND=sql` | B | [ ] | |
| 4.5 | `PORT` != 8000 (usar 8001 o superior) | B | [ ] | |

## 5. Chat y OpenClaw

| # | Item | Tipo | Verificado | Notas |
|---|------|------|------------|-------|
| 5.1 | `enable_chat` feature flag en true | R | [ ] | Settings del backend |
| 5.2 | OpenClaw CLI instalado y verificable | B | [ ] | `npx openclaw --version` debe funcionar |
| 5.3 | Allowlist de paquetes OpenClaw revisada | B | [ ] | `openclaw-allowlist.cjs` |
| 5.4 | Proveedor de chat configurado (API key) | B | [ ] | Variable de entorno del modelo |

## 6. Monitoreo y observabilidad

| # | Item | Tipo | Verificado | Notas |
|---|------|------|------------|-------|
| 6.1 | Logging configurado con nivel INFO en prod | B | [ ] | `main.py` lo maneja automaticamente |
| 6.2 | Health endpoint responde `GET /health` | B | [ ] | |
| 6.3 | Telemetria backend recibiendo eventos | R | [ ] | `POST /v1/telemetry/event` |
| 6.4 | Alertas de caida de servicio configuradas | R | [ ] | |
| 6.5 | Registro de errores 5xx monitoreado | R | [ ] | |

## 7. Legal y compliance

| # | Item | Tipo | Verificado | Notas |
|---|------|------|------------|-------|
| 7.1 | Textos de plantilla Meta revisados por abogado | B | [ ] | |
| 7.2 | Politica de opt-out (palabra STOP) documentada | B | [ ] | |
| 7.3 | Politica de retencion de datos definida | R | [ ] | |
| 7.4 | Aviso de privacidad visible para el usuario | R | [ ] | |

## 8. Despliegue y rollback

| # | Item | Tipo | Verificado | Notas |
|---|------|------|------------|-------|
| 8.1 | Script de despliegue probado en staging | B | [ ] | |
| 8.2 | Backup de BD antes del deploy | B | [ ] | |
| 8.3 | Plan de rollback documentado | B | [ ] | Ver `rollback-plan.md` |
| 8.4 | Versiones de servicios etiquetadas (git tag) | B | [ ] | |
| 8.5 | Variables de entorno documentadas por ambiente | R | [ ] | Ver `docs/env-registry.md` |

## Firma de verificacion

```text
Fecha: _______________
Verificado por: _______________
Ambiente: _______________
Commit/Tag: _______________
Observaciones: _______________
```
