# 🛡️ PLAN MAESTRO DE INGENIERÍA — PROYECTO `THEMIS-LIVE`
**Track:** QualyData — Streaming (Bloqueo en vivo de transmisiones ilegales)  
**Evento:** Hackathon Argentina Space 2026 (11, 12 y 13 de Noviembre · Salta)  
**Premio del Track:** USD 2.000 (1.º USD 1.000 | 2.º USD 600 | 3.º USD 400)  
**Repositorio Oficial del Desafío:** `https://github.com/qualydata-org/desafio-futbol`

---

## 1. Identidad del Proyecto (Para Hacki y el Pitch)

* **Nombre del Proyecto:** **THEMIS-LIVE**
* **Tagline (Subtítulo corto):** *Plataforma Federal de Órdenes Judiciales en Vivo y Bloqueo Dinámico Antipiratería con Daño Colateral Cero.*
* **Pitch en 30 segundos:**
  > *"En Argentina un partido dura 105 minutos, pero un stream pirata cambia de IP y dominio en segundos. Hoy el bloqueo depende de un solo juzgado enviando mails manuales a cámaras empresariales: llega tarde a los ISPs chicos y, cuando bloquea una IP de CDN, tira abajo sitios legítimos. **THEMIS-LIVE** es la primera plataforma federal que automatiza la cadena de custodia forense, analiza el DNS pasivo en milisegundos para elegir quirúrgicamente entre bloqueo por IP o por dominio según la capacidad de cada ISP, permite al juez de turno firmar con un clic desde su celular y audita en tiempo real la aplicación, el reintento ante fallos y el vencimiento automático al minuto 105."*

---

## 2. Ingeniería Inversa del Simulador y del Evaluador Oficial (`verificar.py`)

El jurado evalúa el proyecto ejecutando nuestro sistema contra `simulador/servidor.py` y pasando el archivo `salida/registro.jsonl` por `evaluacion/verificar.py`.  
Conocer exactamente cómo funciona por dentro el código del simulador y del evaluador nos permite garantizar **puntaje perfecto en todas las métricas**:

### 2.1. Cómo puntúa `evaluacion/verificar.py` y la Rúbrica (100 Puntos)
1. **Circuito Completo (25 pts):** Expediente → Juez de turno → Todos los proveedores → Confirmación (`aplicada`) → Vencimiento al final del partido (`fin_min = 105`).
2. **Validez e Integridad de la Evidencia (25 pts):**
   * Verifica que la señal bloqueada sea realmente del partido y pirata.
   * El expediente debe contener: verificación de marca de agua, identificación del servidor de video (`host_stream`, `ip_servidor`, `asn`), análisis de DNS pasivo, hash SHA-256 de `captura.contenido_b64`, sello de tiempo y encadenamiento criptográfico en el registro de auditoría (hash del evento anterior + evento actual).
3. **Control de Daño Colateral y Falsos Positivos (20 pts):**
   * **CERO Falsos Positivos:** En `escenario_practica.json` aparecen detecciones trampa:
     * Un **licenciatario oficial** (`canal-norte`, ej. `envivo.canalnorte.test`) que tiene marca de agua válida del partido pero transmite desde un dominio autorizado en `GET /partido`. **Jamás debe bloquearse.**
     * Un **stream ajeno / VOD** (`resumenes`, ej. `vod.resumenes-deportivos.test`) cuya `marca_de_agua_extraida` está vacía o no coincide con los prefijos válidos de `GET /partido`. **Jamás debe bloquearse.**
   * **CERO Daño Colateral:** `verificar.py` revisa para cada orden `aplicada`:
     * Si `tipo == "ip"`, busca todos los dominios en `dns_pasivo[ip]`. Si hay **un solo dominio legítimo** en esa IP (como ocurre en CDNs o hosting compartido, ej. `198.51.100.20` o `192.0.2.50`), lo penaliza como `bloqueos_con_dano_colateral`.
     * **Regla de Oro de Decisión IP vs. Dominio:**
       Consultamos `GET /dns-pasivo?ip=<ip_servidor>`.
       * ¿Todos los dominios alojados en esa IP pertenecen al conjunto de dominios piratas detectados (o al mismo dominio raíz del stream pirata, ej. `*.pelotaya.test` / `*.tribuna-pirata.test`)?
         * **SÍ (IP dedicada al pirata):** El bloqueo ideal es `tipo = "ip"`, `objetivo = ip_servidor`.
         * **NO (IP compartida con otros dominios / CDN):** El bloqueo obligatorio es `tipo = "dominio"`, `objetivo = host_stream`.
4. **Trampa de Capacidades por Proveedor (Evitar `ordenes_rechazadas`):**
   * En `datos/proveedores.json` hay 4 proveedores:
     * `aurora` (3.8M clientes): acepta `["ip", "dominio"]`, demora 0.5 min, tasa falla 0%.
     * `andina` (1.2M clientes): acepta `["ip", "dominio"]`, demora 2.0 min, tasa falla 0%.
     * `valle` (FibraValle, 140k clientes): **SOLO ACEPTA `["dominio"]`**, demora 6.0 min, tasa falla 0%.
     * `cumbre` (Cooperativa Cumbre, 60k clientes): acepta `["ip", "dominio"]`, demora 3.0 min, **tasa falla 35%**.
   * **Regla Crítica de Adaptación por ISP:**
     Si el motor decide que para un stream corresponde bloqueo por `ip`, al enviarle la orden a un proveedor cuyas `capacidades` **no incluyen `"ip"`** (como `valle`), el servidor devuelve `422 Unprocessable Entity` y registra un evento `orden_rechazada` (que resta puntos en `verificar.py`).
     * **Solución:** Para cada proveedor `p`, si el bloqueo recomendado es `"ip"` pero `"ip" not in p["capacidades"]`, **transformar automáticamente la orden para ese proveedor específico a `tipo = "dominio"` y `objetivo = host_stream`** (con su propia firma judicial válida). ¡Así cubrimos el 100% de los clientes sin un solo rechazo!
5. **Trampa de Proveedor Inestable (`cumbre` con 35% de fallas):**
   * Cuando un proveedor recibe la orden (`202 Accepted`), tarda `demora_min` en aplicarla. Pasado ese tiempo, en `cumbre` el 35% de las órdenes pasan a `"estado": "fallida"`.
   * **Solución:** Nuestro worker de monitoreo debe consultar periódicamente `GET /proveedores/<id>/ordenes` (cada 0.3 segundos reales). Si detecta cualquier orden en `"estado": "fallida"`, genera inmediatamente un **nuevo `orden_id`** (ej. `ord-0001-r1`), lo firma con el juez de turno actual y lo reenvía hasta que quede en `"estado": "aplicada"`.
6. **Trampa del Cambio de Turno Judicial a Mitad del Partido:**
   * En `datos/juzgados.json`:
     * Del minuto `-60` al `50`: está de turno `jueza-laura-ficticia` (`jg-centro-3`, clave `demo-clave-laura-0b7e`).
     * Del minuto `50` al `240`: está de turno `juez-martin-ejemplo` (`jg-norte-1`, clave `demo-clave-martin-4c21`).
   * Si firmamos una orden en el minuto 50.1 con la Jueza Laura, el servidor la acepta pero la marca con `juez_de_turno: false`, y `verificar.py` la escracha en `ordenes_firmadas_fuera_de_turno`.
   * **Solución:** Antes de firmar **cualquier** orden o levantamiento (incluso un reintento), consultar siempre `GET /estado` → tomar `jueces_de_turno[0]` y buscar su `juzgado_id` y `clave_firma_demo` en `datos/juzgados.json`.
7. **Trampa de `vence_min` y Bloqueos Post-Partido:**
   * `vence_min` debe ser un `int` (`int(partido["fin_min"])`, es decir, `105`).
   * Si una detección o reintento ocurre cerca del final, verificar que `vence_min > minuto_actual`. Al minuto 105 el simulador vence automáticamente todas las órdenes con `vence_min = 105`, logrando `0` en `bloqueos_ip_activos_post_partido`.
8. **Atención de Reclamos (`GET /reclamos`):**
   * Si por cualquier motivo (o durante una prueba demostrativa) se emite un reclamo en `GET /reclamos?desde=<min>`, el sistema debe:
     1. Identificar la orden activa que afectó a `reclamo["dominio"]` en `reclamo["proveedor"]`.
     2. Enviar `POST /proveedores/<pid>/ordenes/<orden_id>/levantar` con cuerpo `{"juez_id": juez_turno, "firma": hmac("LEVANTAR|orden_id|juez_id"), "motivo": "Reclamo verificado de sitio legitimo afectado: <dominio>"}`.
     3. Reemplazar inmediatamente esa orden por una orden de `tipo = "dominio"` apuntando únicamente al `host_stream` pirata.

---

## 3. Arquitectura Técnica a Construir

Construiremos una solución modular en **Python 3.10+ (FastAPI + Uvicorn + SQLite/JSONL + Frontend Web Moderno en HTML/Tailwind/JS integrado)** que no requiera compilaciones complejas y levante con un solo comando.

### Estructura del Repositorio a Entregar

```text
themis-live/
├── simulador/                      # (Copiado intacto del repo oficial desafio-futbol)
│   └── servidor.py
├── datos/                          # (Copiado intacto del repo oficial desafio-futbol)
│   ├── escenario_practica.json
│   ├── proveedores.json
│   └── juzgados.json
├── evaluacion/                     # (Copiado intacto del repo oficial desafio-futbol)
│   ├── verificar.py
│   └── verdad_practica.json
├── app/                            # NUESTRA PLATAFORMA THEMIS-LIVE
│   ├── __init__.py
│   ├── config.py                   # Parámetros, rutas y carga de claves judiciales
│   ├── crypto_audit.py             # Firma HMAC-SHA256 judicial + Hash SHA-256 de capturas + Ledger encadenado (Merkle/Hash-chain)
│   ├── detector_engine.py          # Análisis de marca de agua, filtro de licenciatarios y motor de Riesgo Colateral con DNS pasivo
│   ├── orchestrator.py             # Loop en tiempo real contra el simulador (detecciones, firmas, envíos a ISPs, retries y reclamos)
│   ├── server.py                   # API FastAPI + WebSockets/SSE + Servidor de las 3 interfaces web
│   └── static/
│       └── index.html              # SPA con 3 pestañas: 1) SOC En Vivo, 2) App Mobile del Juez de Turno, 3) Portal Público de Transparencia
├── entrega/                        # CARPETA OBLIGATORIA DE ENTREGA DÍA 3
│   ├── expediente_ejemplo.json     # Exportación automática de un expediente completo con evidencia y hashes
│   ├── registro_auditoria.jsonl    # Registro inalterable con cadena de hashes de toda la corrida
│   └── propuesta_normativa.md      # Propuesta normativa de 1 página lista para el jurado
├── scripts/
│   └── correr_partido_completo.py  # Script one-command que levanta simulador + THEMIS-LIVE, corre todo el partido, exporta entrega/ y ejecuta verificar.py
├── requirements.txt
└── README.md
```

---

## 4. Detalle de los Algoritmos Clave de `THEMIS-LIVE`

### 4.1. Algoritmo de Validación de Señal y Anti-Falsos Positivos (`detector_engine.py`)
Al iniciar el partido, consultar `GET /partido`:
```json
{
  "id": "LP26-FECHA12-FINAL",
  "fin_min": 105,
  "marcas_de_agua_validas": ["LP26-PRA-OFI-"],
  "licenciatarios": [
    {"id": "canal-norte", "nombre": "Canal Norte (licenciatario)", "dominios_autorizados": ["canalnorte.test", "envivo.canalnorte.test"]}
  ]
}
```
Para cada detección `d` recibida de `GET /detecciones?desde=<ultimo_min>`:
1. **Check 1 (Marca de agua):** ¿`d["marca_de_agua_extraida"]` empieza con alguno de los prefijos en `marcas_de_agua_validas`?
   * Si NO → Clasificar como `DESCARTADO_SENAL_AJENA` (registrar en auditoría que no se bloquea por no ser la señal oficial).
2. **Check 2 (Licenciatario autorizado):** ¿`d["host_stream"]` o el host de `d["pagina"]` coincide o es subdominio de algún dominio en `dominios_autorizados` de `licenciatarios`?
   * Si SÍ → Clasificar como `DESCARTADO_LICENCIATARIO_OFICIAL` (registrar en auditoría que es transmisión legal).
3. **Check 3 (Deduplicación de fase activa):** Si ya tenemos órdenes activas o en curso para el par `(d["ip_servidor"], d["host_stream"])`, asociar la nueva detección como evidencia suplementaria del expediente existente sin duplicar órdenes en los ISPs.

### 4.2. Algoritmo Exacto de Riesgo Colateral (`detector_engine.py`)
Para una detección pirata confirmada con `ip = d["ip_servidor"]` y `host = d["host_stream"]`:
1. Consultar `GET /dns-pasivo?ip=<ip>`. Devuelve `dominios_en_ip: List[str]`, `asn`, `organizacion`.
2. Extraer el **dominio base** (registrable domain) del `host_stream` y de `d["pagina"]` (por ejemplo, de `s1.pelotaya.test` el dominio base es `pelotaya.test`; de `x9.tribuna-pirata.test` es `tribuna-pirata.test`).
3. Para cada `dom` en `dominios_en_ip`:
   * Verificar si `dom` comparte el dominio base de este stream pirata (o de otro stream pirata ya confirmado por marca de agua).
4. **Regla de decisión:**
   * Si **todos** los dominios en `dominios_en_ip` son subdominios del sitio pirata → `riesgo_colateral = "BAJO (IP Dedicada)"` → `tipo_recomendado = "ip"`, `objetivo_recomendado = ip`.
   * Si existe **al menos un dominio** en `dominios_en_ip` que no pertenece al sitio pirata (ej. diarios, comercios, otros sitios detrás de una CDN o hosting compartido) → `riesgo_colateral = "ALTO (IP Compartida / CDN)"` → `tipo_recomendado = "dominio"`, `objetivo_recomendado = host`.

### 4.3. Modos de Operación del Juez (Automático + Interactivo Mobile)
Para ganar tanto en **velocidad automática (`verificar.py`)** como en la **demo en vivo ante el jurado**:
* **`MODO_JUEZ = "AUTO_ASISTIDO"` (por defecto para la corrida de evaluación):** El juez de turno pre-autoriza la firma digital instantánea sobre expedientes que cumplan 100% los checks criptográficos de marca de agua y riesgo colateral cero, logrando un tiempo de bloqueo (`primer_bloqueo_min`) igual a la latencia mínima teórica del ISP (0.4 - 0.5 minutos de partido) y **Visibilidad Residual mínima (< 3%)**.
* **`MODO_JUEZ = "MANUAL_INTERACTIVO"` (toggle en vivo en la UI para el video/pitch):** Las órdenes entran en una bandeja de notificación tipo WhatsApp/Push en la vista celular del juez de turno, donde el juez toca **"Aprobar y Firmar con Clave Judicial"** o **"Levantar por Reclamo"**.

---

## 5. Propuesta Normativa de 1 Página (Lista para `entrega/propuesta_normativa.md`)

El reglamento exige incluir en `entrega/` una propuesta normativa de 1 página (vale 15 puntos junto con la claridad). La IA debe guardar exactamente este documento pulido en `entrega/propuesta_normativa.md`:

```markdown
# Propuesta Normativa: Régimen Federal de Órdenes Judiciales Dinámicas para Bloqueo de Transmisiones Ilícitas en Vivo

## 1. Objeto y Alcance Federal (Orden Marco y Turno Judicial Digital)
Se propone la creación, mediante Resolución Conjunta de ENACOM, el Ministerio de Justicia y el Consejo de la Magistratura / Junta Federal de Cortes (JUFEJUS), del **Sistema Federal de Bloqueo Dinámico en Vivo (SFBD)**.
- **Habilitación previa por evento:** El titular de derechos o la fiscalía especializada (ej. UFEIC) solicita antes del torneo o fecha una **Orden Marco Preventiva**.
- **Juez de Turno en Plataforma:** Durante la ventana horaria del evento deportivo, un magistrado de turno conectado al SFBD valida en tiempo real las ampliaciones dinámicas de objetivos (IPs y dominios) con firma digital, preservando el control jurisdiccional en cada bloqueo sin demorar horas.

## 2. Registro Federal Único y API Estándar de Proveedores (ISPs)
- **Registro Obligatorio en ENACOM:** Todo licenciatario de servicios TIC / ISP (grandes operadores, PyMEs y cooperativas agrupadas en CABASE y CAPPI) debe mantener actualizado un endpoint técnico en el Registro Federal de Proveedores del SFBD, declarando su capacidad técnica de bloqueo (`DNS/Dominio`, `Enrutamiento/IP` o ambos).
- **Asimetría Tecnológica Reconocida:** Los proveedores pequeños o cooperativas que solo cuenten con resolución DNS propia podrán cumplir la manda aplicando exclusivamente bloqueos por dominio (RPZ/DNS Sinkhole), sin exigirles equipamiento de filtrado BGP/IP costoso.

## 3. Estándar Probatorio Forense y Prevención de Daño Colateral
Para que un objetivo sea elevado a la bandeja de firma del juez de turno, el expediente digital deberá acreditar automáticamente:
1. **Autenticidad de Señal:** Extracción de marca de agua forense (*watermarking*) coincidente con la señal oficial del evento y exclusión automática de dominios pertenecientes a licenciatarios autorizados.
2. **Identificación del Servidor de Video:** Determinación del host de transporte de video (HLS/DASH) y su IP/ASN, evitando bloqueos ineficaces sobre páginas meramente indexadoras.
3. **Regla Estricta Anti-Daño Colateral (DNS Pasivo):** Consulta obligatoria de co-alojamiento (DNS pasivo). Si una dirección IP aloja cualquier dominio ajeno a la infracción (CDNs, proxys inversos o hosting compartido), **queda prohibido el bloqueo por IP**, debiendo ordenarse exclusivamente el bloqueo por nombre de dominio (`host_stream`).
4. **Inmutabilidad:** Sello de tiempo, hash SHA-256 de los fragmentos capturados y registro en cadena de auditoría inalterable.

## 4. Plazos de Ejecución, Caducidad Automática y Vía Rápida de Reclamos
- **Ejecución y Reintento:** Notificada la orden firmada vía API, los ISPs disponen de un plazo máximo de 5 minutos para confirmar su aplicación automática.
- **Caducidad Automática (*Sunset Clause*):** Todo bloqueo dispuesto sobre direcciones IP caducará de pleno derecho y se levantará automáticamente al finalizar el evento en vivo (minuto 105 / pitazo final), prohibiéndose los bloqueos permanentes de IPs dinámicas.
- **Mecanismo Express de Reclamos (Desbloqueo en < 5 min):** Cualquier titular de un servicio legítimo afectado contará con un canal de reclamo inmediato en la plataforma. Verificada la colisión en DNS pasivo, el juez de turno firmará el levantamiento inmediato de la IP y su sustitución por bloqueo de dominio, registrando todo el incidente en el **Portal Público de Transparencia**.
```

---

## 6. Plan de Trabajo Paso a Paso para la IA Ejecutora

1. **Paso 1 — Clonar y preparar entorno:** Clonar `https://github.com/qualydata-org/desafio-futbol` o copiar sus carpetas `simulador/`, `datos/`, `evaluacion/` y `ejemplos/` en la raíz del proyecto.
2. **Paso 2 — Construir el Núcleo (`app/crypto_audit.py` y `app/detector_engine.py`):**
   * Implementar firma HMAC-SHA256 exacta (`orden_id|tipo|objetivo|vence_min|juez_id` y `LEVANTAR|orden_id|juez_id`).
   * Implementar ledger de auditoría encadenado (cada línea JSONL tiene `prev_hash` y `hash` SHA-256).
   * Implementar validación de marca de agua, exclusión de licenciatarios y consulta a `/dns-pasivo?ip=` para decidir `"ip"` vs `"dominio"`.
3. **Paso 3 — Construir el Orquestador Resiliente (`app/orchestrator.py`):**
   * Polling de `/estado`, `/detecciones`, `/reclamos` y estado de órdenes en cada proveedor.
   * Adaptación automática de tipo de bloqueo según `proveedor["capacidades"]` (`valle` recibe `"dominio"` siempre).
   * Reintento automático inmediato con nuevo `orden_id` cuando `cumbre` (o cualquier ISP) reporta `"estado": "fallida"`.
   * Selección dinámica del juez de turno según el minuto actual en `/estado`.
   * Levantamiento firmado automático ante cualquier reclamo en `/reclamos` (más un endpoint de "Simular Reclamo y Resolución en Vivo" para lucirse en el video de 3 minutos).
4. **Paso 4 — Construir Backend FastAPI y Dashboard Tri-Vista (`app/server.py` y `app/static/index.html`):**
   * Vista 1: **Centro de Operaciones Federal (SOC)** con cronómetro del partido, mapa de streams detectados, estado de los 4 ISPs en tiempo real, cobertura de clientes (%) y log criptográfico.
   * Vista 2: **Consola Mobile del Juez de Turno** (simulando la pantalla de un smartphone con el turno activo de la Dra. Laura o el Dr. Martín, expediente resumido y firma).
   * Vista 3: **Portal Ciudadano de Transparencia y Reclamos** (tabla pública de órdenes, hashes, vencimientos y formulario de reclamo).
5. **Paso 5 — Corrida de Verificación y Generación de `entrega/`:**
   * Ejecutar `scripts/correr_partido_completo.py` con `--acelerar 60` (para que los 110 minutos simulados corran en ~2 minutos reales).
   * Ejecutar `python evaluacion/verificar.py --log salida/registro.jsonl` y confirmar:
     * `fases_piratas_bloqueadas`: **7 de 7** (100%).
     * `bloqueos_con_dano_colateral`: **0**.
     * `bloqueos_falsos_positivos`: **0**.
     * `bloqueos_ip_activos_post_partido`: **0**.
     * `ordenes_rechazadas`: **0**.
     * `ordenes_firmadas_fuera_de_turno`: **0**.
   * Exportar automáticamente `entrega/expediente_ejemplo.json`, `entrega/registro_auditoria.jsonl` y `entrega/propuesta_normativa.md`.
