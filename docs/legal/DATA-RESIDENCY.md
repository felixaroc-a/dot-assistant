# Residencia de Datos — Nordik-IA (Venezuela)

> **Fecha:** 2026-07-20  
> **Versión:** 1.0  
> **Alcance:** Análisis de residencia de datos, leyes aplicables y plan de cumplimiento para operación en Venezuela.

---

## 1. Dónde están los datos físicamente

| Dato | Ubicación | Proveedor | Región |
|------|-----------|-----------|--------|
| Datos de suscripción (`clientes_suscripcion`, `usage_tokens`) | PostgreSQL | Google Cloud SQL | `us-central1` (Iowa, USA) |
| Perfiles de usuario (`last_active_at`, preferencias) | Firestore | Google Firebase | `us-central1` (Iowa, USA) |
| Tokens OAuth (Gmail, Calendar) | Firestore (cifrados con Fernet) | Google Firebase | `us-central1` (Iowa, USA) |
| Mensajes de chat (`chat_messages`, `chat_conversations`) | PostgreSQL (cifrados con AES) | Google Cloud SQL | `us-central1` (Iowa, USA) |
| Automatizaciones y pipelines | Firestore | Google Firebase | `us-central1` (Iowa, USA) |
| Logs de aplicación | Logtail (Better Stack) | Better Stack | USA / Global |
| Backups | Google Cloud Storage | GCS | `us-central1` (Iowa, USA) |

> **Todos los datos residen en servidores de Google Cloud Platform en Estados Unidos (Iowa).**

---

## 2. Leyes aplicables en Venezuela

### 2.1 Ley de Infosistemas (Decreto 825, 2000)

- Promueve el uso de tecnologías de información, pero **no establece requisitos de residencia local de datos**.
- No exige que los datos de ciudadanos venezolanos permanezcan en servidores dentro del país.

### 2.2 Providencia 001/003 (SUDEBAN)

- Aplica a **entidades financieras reguladas** (bancos, aseguradoras).
- Nordik-IA **no es una entidad financiera** — no procesa pagos directamente, no almacena datos de tarjetas de crédito.
- Las recargas IA se hacen en tiendas físicas (puntos de venta); Nordik no toca datos financieros del usuario final.

### 2.3 Ley de Protección de Datos Personales (Proyecto)

- Venezuela **no tiene una ley de protección de datos personales equivalente al GDPR**.
- Existen proyectos de ley (ej. "Ley de Protección de Datos Personales") pero **no han sido promulgados** a julio 2026.
- El marco legal actual es limitado en cuanto a privacidad de datos.

### 2.4 Constitución de Venezuela (Art. 28, 48, 60)

- Derecho a la privacidad y al honor.
- Derecho de acceso a datos personales en registros oficiales o privados.
- Inviolabilidad de comunicaciones privadas.

---

## 3. Análisis de riesgo

### Riesgo bajo para fase inicial

| Factor | Evaluación | Riesgo |
|--------|-----------|--------|
| Regulación local | Sin ley de protección de datos específica | **Bajo** |
| Datos financieros | Nordik no almacena datos de tarjetas ni procesa pagos | **Bajo** |
| Datos sensibles | Chats y archivos (solo metadatos); tokens OAuth cifrados | **Bajo-Medio** |
| Jurisdicción USA | GCP cumple SOC 2, ISO 27001, HIPAA | **Mitigado** |
| Transferencia internacional | Venezuela → USA (sin restricción legal expresa) | **Bajo** |
| Encriptación | Datos sensibles cifrados en reposo (chats, OAuth) | **Mitigado** |
| Alcance geográfico | Solo Venezuela en fase inicial | **Bajo** |

### Riesgos a monitorear

1. **Si se promulga una ley de protección de datos en Venezuela**, será necesario reevaluar.
2. **Si Nordik expande a otros países** (Brasil, UE), aplicarán regulaciones más estrictas.
3. **Si Nordik comienza a procesar pagos directamente**, necesitará compliance PCI-DSS.

---

## 4. Recomendaciones para cumplimiento (fase actual)

### 4.1 Informar al usuario

La **Política de Privacidad** (`docs/legal/PRIVACY-POLICY.md`) ya incluye:
- Qué datos recolectamos
- Cómo los usamos
- Dónde se almacenan (GCP us-central1, USA)
- Cuánto tiempo se retienen (3 meses tras inactividad, política de purga D01)

### 4.2 Consentimiento explícito

Implementado en **L01** (Fase LEGAL):
- Checkbox "Acepto los términos y política de privacidad" durante el onboarding
- El usuario no puede usar la app sin aceptar

### 4.3 Derechos ARCO del usuario

Nordik-IA debe garantizar los derechos ARCO (Acceso, Rectificación, Cancelación, Oposición):

| Derecho | Cómo se cumple | Estado |
|---------|---------------|--------|
| **Acceso** | El usuario puede solicitar sus datos almacenados | Placeholder: email `soporte@nordikia.com` |
| **Rectificación** | El usuario puede corregir nombre, email, teléfono | Parcial: vía portal de autogestión (`/portal`) |
| **Cancelación** | El usuario puede solicitar eliminación de sus datos | Placeholder: email `soporte@nordikia.com` |
| **Oposición** | El usuario puede oponerse al tratamiento de sus datos | Placeholder: email `soporte@nordikia.com` |

> **Pendiente:** Implementar endpoint `POST /v1/me/export-data` para que el usuario descargue todos sus datos en formato JSON. Esto es requerido para cumplir con el derecho de acceso de forma automatizada.

### 4.4 Cómo el usuario puede solicitar sus datos

Actualmente, el usuario debe contactar a `soporte@nordikia.com` para:
- Solicitar una copia de todos sus datos
- Solicitar la rectificación de datos incorrectos
- Solicitar la eliminación de sus datos (derecho al olvido)
- Oponerse al tratamiento de sus datos para fines específicos

**Recomendación a futuro:** implementar un portal de autogestión que permita al usuario descargar y eliminar sus datos sin intervención manual.

### 4.5 Notificación de brechas de seguridad

En caso de una brecha de seguridad que comprometa datos personales:
1. Notificar a los usuarios afectados en un plazo máximo de 72 horas
2. Publicar un aviso en el portal de autogestión
3. Documentar el incidente en `docs/observability/incidents/`
4. Notificar a las autoridades venezolanas si la ley lo requiere (actualmente no hay obligación específica)

---

## 5. Plan futuro: Expansión a otros países

### 5.1 Brasil — LGPD (Lei Geral de Proteção de Dados)

Si Nordik se expande a Brasil, la **LGPD** exige:

1. **Base legal para el tratamiento** de datos (consentimiento, ejecución de contrato, interés legítimo)
2. **Residencia de datos**: No exige que los datos estén en Brasil, pero recomienda. Opción:
   - Abrir región GCP en **São Paulo** (`southamerica-east1`) para datos de usuarios brasileños
   - Mantener `us-central1` para el resto de LATAM
3. **DPO (Data Protection Officer)**: Designar un encargado de protección de datos en Brasil
4. **DPA (Data Processing Agreement)** con Google Cloud
5. **Registro de actividades de tratamiento** (ROPA)
6. **Evaluación de impacto** (DPIA) para tratamientos de alto riesgo

### 5.2 Unión Europea — GDPR

Si Nordik se expande a la UE, el **GDPR** exige:

1. **Base legal**: Consentimiento explícito + interés legítimo
2. **Residencia de datos**: Datos de ciudadanos UE deben residir en la UE o en países con "adequacy decision". Opciones:
   - Abrir región GCP en Europa (`europe-west1` en Bélgica, `europe-west3` en Frankfurt, `europe-west4` en Países Bajos)
   - Usar cláusulas contractuales estándar (SCC) para transferencias USA↔UE
3. **DPO**: Designar un Data Protection Officer en la UE
4. **DPA** con Google Cloud: Firmar el DPA estándar de GCP
5. **Derecho al olvido**: Eliminación completa de datos en <30 días
6. **Portabilidad de datos**: Exportación en formato estructurado (JSON/CSV)
7. **Registro de brechas**: Notificar a la autoridad de control en <72 horas
8. **Representante en la UE**: Designar un representante legal si Nordik no tiene establecimiento en la UE

### 5.3 Colombia — Ley 1581 de 2012 (Habeas Data)

Si Nordik se expande a Colombia:
1. **Autorización previa** del titular para tratamiento de datos
2. **Registro Nacional de Bases de Datos** (RNBD) ante la SIC
3. **Política de Tratamiento de Información** publicada
4. **Aviso de privacidad** visible en la app

---

## 6. Data Processing Agreement (DPA) con GCP

### Estado actual

Google Cloud Platform ya proporciona un **DPA estándar** como parte de sus términos de servicio. No se requiere un acuerdo separado — la aceptación de los ToS de GCP incluye automáticamente las cláusulas de procesamiento de datos.

### Enlace al DPA de GCP

- [Google Cloud Data Processing Addendum (CDPA)](https://cloud.google.com/terms/data-processing-addendum)
- Cubre: GDPR, CCPA, LGPD y otras regulaciones

### Certificaciones de GCP relevantes

| Certificación | Relevancia |
|---------------|-----------|
| SOC 2 Type II | Seguridad, disponibilidad y confidencialidad |
| ISO 27001 | Sistema de gestión de seguridad de la información |
| ISO 27017 | Controles específicos para servicios cloud |
| ISO 27018 | Protección de datos personales en cloud |
| HIPAA | Datos de salud (no aplica a Nordik actualmente) |
| PCI-DSS | Datos de tarjetas (no aplica a Nordik actualmente) |

---

## 7. Checklist de compliance

- [x] Política de Privacidad publicada (`docs/legal/PRIVACY-POLICY.md`)
- [x] Términos de Servicio publicados (`docs/legal/TERMS-OF-SERVICE.md`)
- [x] Consentimiento explícito en onboarding (checkbox L01)
- [x] Datos cifrados en reposo (chats con AES, OAuth con Fernet)
- [x] Conexiones TLS/HTTPS para datos en tránsito (I01)
- [ ] Exportación de datos automatizada para el usuario (`POST /v1/me/export-data`)
- [ ] Portal de autogestión para eliminación de datos (self-service)
- [ ] Procedimiento documentado de notificación de brechas
- [ ] DPA con GCP firmado (incluido en ToS — verificar con legal)
- [ ] Registro RNBD en Colombia (si se expande allá)

---

## 8. Referencias

- **Ley de Infosistemas (Venezuela):** Decreto 825, Gaceta Oficial N° 36.955, 22/05/2000
- **Providencia 001/003 (SUDEBAN):** Normas sobre servicios de tecnología de información
- **LGPD (Brasil):** Lei 13.709/2018
- **GDPR (UE):** Regulation (EU) 2016/679
- **GCP DPA:** https://cloud.google.com/terms/data-processing-addendum
- **GCP Compliance:** https://cloud.google.com/security/compliance
