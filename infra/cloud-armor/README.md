# CF05 — Cloud Armor WAF · Nordik-IA (DOT)

> **Propósito:** Documentar el despliegue, validación y mantenimiento de las reglas WAF de Cloud Armor para la API de DOT.
> **Archivo de reglas:** `waf-rules.yaml`
> **Referencia:** BIBLIA-SEGURIDAD-ESCALA.md §2 (Mandamiento VIII — Protección DDoS activa)

---

## Requisitos previos

- `gcloud` CLI instalado y autenticado (`gcloud auth login`).
- Proyecto GCP configurado: `gcloud config set project nordik-ia`.
- Rol IAM: `Compute Security Admin` o `roles/compute.securityAdmin`.
- Cloud Load Balancer externo ya creado (o al menos planificado — ver `infra/lb-cdn/architecture.md` CF04).

---

## 1. Despliegue inicial

### 1.1 Crear la política de seguridad

```bash
gcloud compute security-policies create nordik-waf \
    --description "WAF policy for Nordik-IA (DOT) API — OWASP Top 10, rate limiting, geo-restriction"
```

### 1.2 Importar las reglas desde el YAML

Cloud Armor no soporta importación directa de un YAML completo. Las reglas se importan una por una desde el archivo YAML. Script de despliegue:

```bash
#!/bin/bash
# deploy-waf.sh — Desplegar todas las reglas de waf-rules.yaml en orden

POLICY="nordik-waf"
YAML="infra/cloud-armor/waf-rules.yaml"

echo "Desplegando reglas WAF en política: $POLICY"
echo "Esto sobrescribirá las reglas existentes. ¿Continuar? (y/N)"
read -r confirm
[[ "$confirm" != "y" ]] && echo "Abortado." && exit 0

# Regla 1 — Country restriction (priority 10)
gcloud compute security-policies rules create 10 \
    --security-policy="$POLICY" \
    --description="Allow only Venezuela (VE) and Colombia (CO)" \
    --expression='![origin.region_code].matches(["VE","CO"])' \
    --action=deny-403

# Regla 2 — IP allowlist admin (priority 20)
# NOTA: Reemplazar los rangos de IP con las IPs reales del equipo Nordik
gcloud compute security-policies rules create 20 \
    --security-policy="$POLICY" \
    --description="IP allowlist for admin panel (port 8001)" \
    --expression='request.path.matches("/admin/") || request.path.matches("/admin")' \
    --action=deny-403

# Regla 3 — SQLi protection (priority 100)
gcloud compute security-policies rules create 100 \
    --security-policy="$POLICY" \
    --description="Block SQL injection — OWASP sqli-v33-stable" \
    --expression="evaluatePreconfiguredExpr('sqli-v33-stable')" \
    --action=deny-403

# Regla 4 — XSS protection (priority 110)
gcloud compute security-policies rules create 110 \
    --security-policy="$POLICY" \
    --description="Block XSS — OWASP xss-v33-stable" \
    --expression="evaluatePreconfiguredExpr('xss-v33-stable')" \
    --action=deny-403

# Regla 5 — LFI/RFI protection (priority 120)
gcloud compute security-policies rules create 120 \
    --security-policy="$POLICY" \
    --description="Block LFI/RFI — OWASP lfi-v33-stable" \
    --expression="evaluatePreconfiguredExpr('lfi-v33-stable')" \
    --action=deny-403

# Regla 6 — RCE protection (priority 130)
gcloud compute security-policies rules create 130 \
    --security-policy="$POLICY" \
    --description="Block RCE — OWASP rce-v33-stable" \
    --expression="evaluatePreconfiguredExpr('rce-v33-stable')" \
    --action=deny-403

# Regla 7 — Protocol attack protection (priority 140)
gcloud compute security-policies rules create 140 \
    --security-policy="$POLICY" \
    --description="Block protocol attacks" \
    --expression="evaluatePreconfiguredExpr('protocolattack-v33-stable')" \
    --action=deny-403

# Regla 8 — Scanner detection (priority 150)
gcloud compute security-policies rules create 150 \
    --security-policy="$POLICY" \
    --description="Block vulnerability scanners" \
    --expression="evaluatePreconfiguredExpr('scannerdetection-v33-stable')" \
    --action=deny-403

# Regla 9 — Rate limit: auth endpoints (100 req/60s per IP)
gcloud compute security-policies rules create 200 \
    --security-policy="$POLICY" \
    --description="Rate limit auth endpoints: 100 req/60s per IP" \
    --expression='request.path.matches("/v1/auth/")' \
    --action=throttle \
    --rate-limit-threshold-count=100 \
    --rate-limit-threshold-interval-sec=60 \
    --conform-action=allow \
    --exceed-action=deny-429 \
    --enforce-on-key=IP

# Regla 10 — Rate limit: general API (300 req/60s per IP)
gcloud compute security-policies rules create 210 \
    --security-policy="$POLICY" \
    --description="Rate limit general API: 300 req/60s per IP" \
    --expression='request.path.matches("/v1/")' \
    --action=throttle \
    --rate-limit-threshold-count=300 \
    --rate-limit-threshold-interval-sec=60 \
    --conform-action=allow \
    --exceed-action=deny-429 \
    --enforce-on-key=IP

# Regla 11 — Rate limit: IA generation (20 req/60s per IP)
gcloud compute security-policies rules create 220 \
    --security-policy="$POLICY" \
    --description="Rate limit IA endpoints: 20 req/60s per IP" \
    --expression='request.path.matches("/v1/chat/stream") || request.path.matches("/v1/vision/") || request.path.matches("/v1/image/generate")' \
    --action=throttle \
    --rate-limit-threshold-count=20 \
    --rate-limit-threshold-interval-sec=60 \
    --conform-action=allow \
    --exceed-action=deny-429 \
    --enforce-on-key=IP

# Regla 12 — Default allow (priority max)
gcloud compute security-policies rules create 2147483647 \
    --security-policy="$POLICY" \
    --description="Allow all remaining traffic (default)" \
    --src-ip-ranges="*" \
    --action=allow

echo ""
echo "Todas las reglas desplegadas. Verificando..."
gcloud compute security-policies describe "$POLICY" --format="json" | head -20
```

### 1.3 Habilitar protección adaptativa

```bash
# Activar Layer 7 DDoS Defense con ML de Google
gcloud compute security-policies update nordik-waf \
    --enable-layer7-ddos-defense \
    --layer7-ddos-defense-rule-priority=50 \
    --layer7-ddos-defense-action=deny-403

# Para monitoreo (sin bloquear, solo throttle):
gcloud compute security-policies update nordik-waf \
    --enable-layer7-ddos-defense \
    --layer7-ddos-defense-rule-priority=50 \
    --layer7-ddos-defense-action=throttle
```

### 1.4 Adjuntar política al backend service

```bash
# Asociar el WAF al backend service de Cloud Run
gcloud compute backend-services update nordik-api-backend \
    --security-policy=nordik-waf

# Verificar que quedó adjunto
gcloud compute backend-services describe nordik-api-backend \
    --format="value(securityPolicy)"
```

---

## 2. Modo preview (despliegue seguro)

Antes de activar reglas en modo bloqueo, desplegarlas en **modo preview** para observar falsos positivos sin afectar tráfico real.

### 2.1 Activar preview en todas las reglas

```bash
# Listar reglas actuales
gcloud compute security-policies rules list \
    --security-policy=nordik-waf --format="table(priority,description,preview)"

# Activar preview para una regla específica
gcloud compute security-policies rules update <PRIORITY> \
    --security-policy=nordik-waf \
    --preview

# Ejemplo: poner regla de países en preview primero
gcloud compute security-policies rules update 10 \
    --security-policy=nordik-waf \
    --preview
```

### 2.2 Monitorear preview hits

```bash
# Ver métricas en Cloud Monitoring
# Métrica: security_policy/preview_requests_count
# Filtrar por security_policy_name="nordik-waf"

# Vía gcloud logging:
gcloud logging read \
    'resource.type="http_load_balancer" AND jsonPayload.enforcedSecurityPolicy.name="nordik-waf" AND jsonPayload.previewSecurityPolicy.outcome="DENY"' \
    --limit=50 --format="table(timestamp,jsonPayload.previewSecurityPolicy.priority,jsonPayload.previewSecurityPolicy.matchedFieldValue)"
```

---

## 3. Validación y testing

### 3.1 Probar restricción geográfica

```bash
# Desde una IP dentro de VE/CO → debería permitir
curl -sv https://api.nordikia.com/health 2>&1 | grep "< HTTP"

# Esperado: HTTP/2 200

# Simular desde IP fuera de VE/CO (usar VPN o proxy)
# Esperado: HTTP/2 403
```

### 3.2 Probar rate limiting de auth

```bash
# Enviar 110 requests en <60s al endpoint de login
for i in $(seq 1 110); do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST https://api.nordikia.com/v1/auth/login \
    -H "Content-Type: application/json" \
    -d '{"cedula":"123","password":"test"}'
done | sort | uniq -c

# Esperado: ~100 respuestas con código variado, luego 429
```

### 3.3 Probar protección SQLi

```bash
# Intentar inyección SQL en un parámetro
curl -sv "https://api.nordikia.com/v1/search?q='%20OR%201=1--" 2>&1 | grep "< HTTP"

# Esperado: HTTP/2 403 (bloqueado por WAF)

# Request normal debe funcionar:
curl -sv "https://api.nordikia.com/v1/search?q=hola" 2>&1 | grep "< HTTP"

# Esperado: HTTP/2 200 (o 401 si requiere auth, pero no 403 del WAF)
```

### 3.4 Probar protección XSS

```bash
# Intentar XSS en cualquier parámetro
curl -sv "https://api.nordikia.com/v1/users/profile" \
  -H "Content-Type: application/json" \
  -d '{"name":"<script>alert(1)</script>"}' 2>&1 | grep "< HTTP"

# Esperado: HTTP/2 403 (bloqueado por WAF)
```

### 3.5 Probar acceso al admin sin IP autorizada

```bash
# Desde una IP NO autorizada:
curl -sv https://admin.nordikia.com/admin/dashboard 2>&1 | grep "< HTTP"

# Esperado: HTTP/2 403 (o connection refused si el admin está en otra VM)
```

---

## 4. Monitoreo continuo

### 4.1 Métricas clave en Cloud Monitoring

| Métrica | Descripción |
|---------|-------------|
| `security_policy/requests_count` | Total de requests evaluadas por la política |
| `security_policy/preview_requests_count` | Requests evaluadas en modo preview |
| `security_policy/blocked_requests_count` | Requests bloqueadas (deny action) |
| `security_policy/throttled_requests_count` | Requests con throttle aplicado |

### 4.2 Dashboard recomendado

Crear un dashboard en Cloud Monitoring con:

1. **Requests bloqueadas por regla** (stacked bar chart, agrupado por `priority`).
2. **Ratio de bloqueo** (blocked / total requests) — alerta si >10%.
3. **Requests 429 (rate limit)** — línea de tiempo, para detectar picos de abuso.
4. **Top IPs bloqueadas** — tabla con `jsonPayload.enforcedSecurityPolicy.matchedFieldValue`.
5. **Geografía de requests bloqueadas** — mapa de calor por `origin.region_code`.

### 4.3 Alertas

```bash
# Alerta si más de 50 bloqueos en 5 minutos (posible ataque activo)
gcloud alpha monitoring policies create \
    --display-name="WAF: High block rate — possible attack" \
    --condition-filter='metric.type="loadbalancing.googleapis.com/https/request_count" AND resource.label.security_policy="nordik-waf" AND metric.label.response_code_class="400"' \
    --condition-threshold-value=50 \
    --condition-threshold-duration=300s \
    --combiner=OR \
    --notification-channels=<CHANNEL_ID>
```

---

## 5. Mantenimiento

### 5.1 Agregar un nuevo país

Cuando DOT se expanda a nuevos países, actualizar regla prioridad 10:

```bash
# Agregar Ecuador (EC) y Perú (PE):
gcloud compute security-policies rules update 10 \
    --security-policy=nordik-waf \
    --expression='![origin.region_code].matches(["VE","CO","EC","PE"])' \
    --action=deny-403
```

### 5.2 Agregar IP al allowlist de admin

```bash
# Actualizar regla 20 con nuevos rangos:
gcloud compute security-policies rules update 20 \
    --security-policy=nordik-waf \
    --expression='request.path.matches("/admin/") && !inIpRange(origin.ip, ["190.X.X.X/32","201.X.X.X/32"])' \
    --action=deny-403
```

### 5.3 Actualizar reglas preconfiguradas

Google actualiza periódicamente las reglas OWASP (sqli, xss, lfi, rce). Verificar versión actual y migrar:

```bash
# Listar versiones disponibles de reglas preconfiguradas
gcloud compute security-policies list-preconfigured-expression-sets

# Actualizar expresión a nueva versión (ej: v34)
gcloud compute security-policies rules update 100 \
    --security-policy=nordik-waf \
    --expression="evaluatePreconfiguredExpr('sqli-v34-stable')"
```

### 5.4 Ajustar rate limits

Si se observan muchos falsos positivos (usuarios legítimos bloqueados por rate limit):

```bash
# Aumentar límite de auth de 100 a 200 req/60s
gcloud compute security-policies rules update 200 \
    --security-policy=nordik-waf \
    --rate-limit-threshold-count=200
```

---

## 6. Rollback de emergencia

Si las reglas WAF están bloqueando tráfico legítimo masivamente:

```bash
# Opción A: Desactivar regla específica (preview mode)
gcloud compute security-policies rules update <PRIORITY> \
    --security-policy=nordik-waf \
    --preview

# Opción B: Desasociar completamente la política del backend
gcloud compute backend-services update nordik-api-backend \
    --no-security-policy

# Opción C: Cambiar regla específica a allow temporal
gcloud compute security-policies rules update <PRIORITY> \
    --security-policy=nordik-waf \
    --action=allow
```

---

## 7. Costos

| Concepto | Costo mensual |
|----------|---------------|
| Política base | $5.00 |
| Reglas preconfiguradas (5) | $5.00 ($1.00 c/u) |
| Protección adaptativa | $10.00 |
| Requests procesadas (~300k) | ~$0.23 |
| **Total** | **~$20.23/mes** |

Ver desglose completo en `infra/lb-cdn/architecture.md` §6.
