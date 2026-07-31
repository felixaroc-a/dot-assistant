# Política de Privacidad de Nordik IA (DOT)

**Última actualización:** Julio 2026

---

## 1. Introducción

En Nordik IA valoramos tu privacidad. Esta Política de Privacidad explica qué datos personales recolectamos, cómo los usamos, dónde los almacenamos y qué derechos tienes sobre ellos. Al usar DOT, aceptas las prácticas descritas en este documento.

Si tienes preguntas, escríbenos a **[soporte@nordikia.com](mailto:soporte@nordikia.com)**.

---

## 2. Datos que recolectamos

Para que DOT funcione correctamente, recolectamos los siguientes datos:

| Dato | Propósito |
|------|-----------|
| **Cédula de identidad** | Identificación única del usuario, autenticación y control de licencia. |
| **Nombre completo** | Personalización de la experiencia y comunicación contigo. |
| **Correo electrónico** | Contacto, recuperación de cuenta y notificaciones del servicio. |
| **Historial de chat** | Procesar tus conversaciones con la IA y mejorar las respuestas. |
| **Metadatos de archivos** | Nombre, tipo y tamaño de los archivos que subes o generas. **No leemos el contenido** de tus documentos salvo que tú los compartas explícitamente en el chat. |
| **Consumo de IA** | Cantidad de tokens y costo en dólares consumidos por tus interacciones con la IA. Se usa para aplicar el límite mensual de consumo ($7.50 USD/mes). |
| **Datos técnicos** | Versión de la app, sistema operativo y tipo de pendrive (para diagnóstico y compatibilidad). |

**No recolectamos:** contraseñas (se validan con hash, nunca se almacenan en texto plano), ubicación GPS, contactos de tu dispositivo ni datos de otros programas de tu PC.

---

## 3. Finalidad del tratamiento

Usamos tus datos exclusivamente para:

1. **Funcionamiento del producto:** procesar tus mensajes con la IA, ejecutar automatizaciones y sincronizar tus conversaciones entre sesiones.
2. **Personalización:** recordar tu nombre, preferencias de idioma e integraciones que hayas configurado.
3. **Facturación y control de consumo:** verificar tu suscripción activa y aplicar el límite de consumo de IA.
4. **Soporte técnico:** diagnosticar errores y ayudarte cuando contactas a nuestro equipo.
5. **Mejora del producto:** analizar patrones de uso agregados (sin identificarte) para mejorar DOT.

**No vendemos, alquilamos ni compartimos tus datos personales con terceros** con fines publicitarios o comerciales.

---

## 4. Dónde se almacenan tus datos

Tus datos se almacenan en servidores de **Google Cloud Platform (GCP)** ubicados en **Estados Unidos (región us-central1)**.

Utilizamos dos tipos de almacenamiento:

- **Firestore (NoSQL):** perfiles de usuario, tokens de integraciones y configuraciones.
- **PostgreSQL:** datos de suscripción, facturación y consumo de IA.

Todos los datos en tránsito viajan cifrados con **TLS 1.3**. Los tokens de integraciones de terceros (Google) se almacenan cifrados con **Fernet (AES-128-CBC)**.

---

## 5. Período de retención

Conservamos tus datos mientras tu suscripción esté activa. Si tu cuenta queda inactiva:

| Estado | Período | Acción |
|--------|---------|--------|
| Inactividad (sin abrir la app) | **3 meses** | Tus datos personales y conversaciones se purgan automáticamente. |
| No pago | **90 días** de gracia | Conservamos tus datos. Al día 91 sin pago, se purgan. |
| Cuenta activa | Indefinido | Tus datos se conservan mientras tengas una suscripción vigente. |

La **purga automática** elimina: historial de chat, metadatos de archivos, configuraciones de integraciones y datos de perfil. Los registros de facturación se conservan por **5 años** por obligación legal venezolana.

---

## 6. Derechos del usuario (ARCO)

Como usuario de DOT, tienes los siguientes derechos sobre tus datos personales:

| Derecho | Qué significa | Cómo ejercerlo |
|---------|---------------|----------------|
| **Acceso** | Puedes solicitar una copia de todos tus datos. | Escríbenos a soporte@nordikia.com |
| **Rectificación** | Puedes corregir datos inexactos (nombre, email). | Desde la app o contactando soporte |
| **Cancelación** | Puedes solicitar la eliminación de tus datos. | Escríbenos a soporte@nordikia.com |
| **Oposición** | Puedes oponerte al tratamiento de tus datos para fines específicos. | Escríbenos a soporte@nordikia.com |

Responderemos a tu solicitud en un plazo máximo de **15 días hábiles**.

---

## 7. Seguridad

Implementamos medidas técnicas y organizativas para proteger tus datos:

- Cifrado en tránsito (TLS 1.3) y en reposo (AES-256).
- Autenticación de doble factor: cédula + contraseña + llave física (pendrive USB).
- Rotación automática de tokens de acceso (JWT) cada 4 minutos.
- Firestore con reglas de seguridad que limitan el acceso solo a tus propios datos.
- Purga automática de datos tras inactividad (ver §5).

En caso de una brecha de seguridad que afecte tus datos personales, te notificaremos en un plazo máximo de **72 horas** desde que tengamos conocimiento del incidente.

---

## 8. Transferencia internacional de datos

Al usar DOT, aceptas que tus datos sean transferidos y almacenados en Estados Unidos (GCP us-central1). Aunque Venezuela no cuenta con una ley equivalente al GDPR europeo, aplicamos estándares internacionales de protección de datos.

Si en el futuro expandimos el servicio a otros países, revisaremos y adaptaremos esta política para cumplir con las leyes locales aplicables (LGPD en Brasil, GDPR en Europa, etc.).

---

## 9. Cambios a esta política

Nos reservamos el derecho de modificar esta Política de Privacidad. Te notificaremos por correo electrónico y mediante un aviso en la app con al menos **15 días** de anticipación antes de que los cambios entren en vigor. El uso continuado de DOT después de la fecha de entrada en vigor constituye tu aceptación de los cambios.

---

## 10. Contacto

**Nordik IA**  
Email: [soporte@nordikia.com](mailto:soporte@nordikia.com)  
Venezuela

Para ejercer tus derechos ARCO o reportar incidentes de seguridad, usa el correo de soporte con el asunto correspondiente.
