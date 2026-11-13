# Propuesta normativa · Régimen Federal de Órdenes Judiciales Dinámicas para el Bloqueo de Transmisiones Ilícitas en Vivo

**Proyecto:** THEMIS-LIVE · Hackathon Argentina Space 2026

**Marco legal aplicable.** El orden de bloqueo en vivo encuentra su base en el **art. 57 de la Ley 27.078** (deberes de los prestadores de servicios TIC) y opera bajo la doctrina **"Rodríguez, María Belén c/ Google Inc."** (CSJN, 28/10/2014): el intermediario no responde por contenidos de terceros sin orden judicial específica, y cuando media esa orden debe ejecutarla dentro del estándar técnico posible. Hoy esa ejecución llega por vías informales (Cámaras de proveedores, correo, teléfono) y sin trazabilidad; a los proveedores chicos no les alcanza. Este régimen formaliza el canal bajo control judicial permanente, tomando el modelo italiano (bloqueo AGCOM en 30 minutos, sin juez) y corrigiéndole el vicio conocido: ahí cayeron sitios legítimos; acá la orden nace en cabeza de un juez de turno con expediente digital y DNS pasivo como requisito de procedibilidad. El 1/11/2026, para el Superclásico, se pidió bloquear 182 dominios por una vía informal: el SFBD convierte ese esfuerzo en un procedimiento estándar, revisable y con cierre automático.

## 1. Objeto y orden marco con juez de turno digital

Crear, por resolución conjunta de ENACOM, el Ministerio de Justicia y JUFEJUS, el **Sistema Federal de Bloqueo Dinámico en Vivo (SFBD)**. Antes de cada torneo o evento, el titular de derechos o la fiscalía especializada (UFEIC) solicita una **orden marco preventiva**. Durante la ventana horaria del evento, un **juez de turno conectado a la plataforma** valida en tiempo real las ampliaciones dinámicas de objetivos (IPs y dominios) con firma digital, preservando el control judicial en cada bloqueo sin demoras de horas.

## 2. Registro federal único y API estándar de proveedores

Todo licenciatario TIC/ISP —grandes operadores, PyMEs y cooperativas de CABASE y CAPPI— debe mantener actualizado un endpoint técnico en el **Registro Federal de Proveedores** del SFBD, declarando su capacidad real de bloqueo (`DNS/dominio`, `IP` o ambas). Se reconoce la **asimetría tecnológica**: los proveedores que solo cuentan con resolución DNS propia cumplen con bloqueo por dominio (RPZ/DNS sinkhole), sin exigirles filtrado BGP costoso.

## 3. Estándar probatorio y prevención de daño colateral

Para llegar a la bandeja de firma del juez, el expediente digital debe acreditar automáticamente:

1. **Autenticidad de la señal:** marca de agua forense coincidente con la señal oficial y exclusión de licenciatarios autorizados en sus dominios.
2. **Servidor real de video:** host de transporte (HLS/DASH), IP y ASN; no alcanza con bloquear la página indexadora.
3. **Regla estricta anti-daño colateral:** consulta obligatoria de DNS pasivo. Si una IP aloja cualquier dominio ajeno a la infracción (CDN, proxy inverso o hosting compartido), **queda prohibido el bloqueo por IP** y se ordena el bloqueo por dominio del `host_stream`.
4. **Inmutabilidad:** sello de tiempo, hash SHA-256 de las capturas y registro de auditoría encadenado.

## 4. Plazos, caducidad automática y reclamos express

- **Ejecución:** notificada la orden firmada por API, cada ISP confirma su aplicación en un máximo de **5 minutos**, con reintento automático ante fallas.
- **Caducidad automática:** todo bloqueo por IP caduca de pleno derecho al finalizar el evento (minuto 105 / pitazo final); se prohíben los bloqueos permanentes de IPs dinámicas.
- **Reclamos:** canal inmediato para titulares afectados. Verificada la colisión en DNS pasivo, el juez de turno firma el levantamiento en menos de 5 minutos y lo sustituye por un bloqueo de dominio, registrando el incidente en el **Portal Público de Transparencia**.
- **Recurso:** el titular afectado tiene un plazo de **24 horas** para apelar ante el mismo juez de turno; si el DNS pasivo acreditó la colisión en el momento de la orden, la apelación tramita con efecto suspensivo de pleno derecho. Cada reclamo cerrado queda auditable públicamente en el Portal.
