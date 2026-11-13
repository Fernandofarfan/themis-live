# 🤖 PROMPT LISTO PARA COPIAR Y PEGAR EN TU OTRA IA (TRACK 1: STREAMING — THEMIS-LIVE)

Copiá todo el bloque de abajo y pegáselo directamente a tu otra IA (Cursor, Claude Code, Windsurf, Devin, etc.) estando dentro de la carpeta `Track-1-Streaming_THEMIS-LIVE`:

---

```markdown
Quiero que construyas de principio a fin el proyecto ganador para el Track "QualyData - Streaming" del Hackathon Argentina Space 2026, llamado **THEMIS-LIVE** (Plataforma Federal de Órdenes Judiciales en Vivo y Bloqueo Dinámico Antipiratería).

Antes de escribir código, lee atentamente el archivo `PLAN-MAESTRO-THEMIS-LIVE.md` que está en esta misma carpeta. Ahí tienes toda la ingeniería inversa del simulador oficial, del evaluador `verificar.py`, las trampas del escenario y la arquitectura exacta que debemos construir.

Ejecuta el plan completo siguiendo estos pasos sin detenerte hasta dejar todo probado y verificado:

1. **Clonar e integrar el repositorio oficial del desafío:**
   - Clona `https://github.com/qualydata-org/desafio-futbol` en una carpeta temporal y mueve/copia sus carpetas `simulador/`, `datos/`, `evaluacion/` y `ejemplos/` a la raíz de nuestro proyecto para que podamos correr `python simulador/servidor.py` y `python evaluacion/verificar.py` tal como lo hará el jurado.
   - Inspecciona `datos/escenario_practica.json`, `datos/proveedores.json`, `datos/juzgados.json` y `evaluacion/verificar.py` para asegurarte de contemplar todos los casos borde.

2. **Construir el backend y motor completo de THEMIS-LIVE en `app/`:**
   - `app/crypto_audit.py`:
     - Firma HMAC-SHA256 judicial exacta (`orden_id|tipo|objetivo|vence_min|juez_id` para órdenes y `LEVANTAR|orden_id|juez_id` para levantamientos) leyendo las claves desde `datos/juzgados.json`.
     - Cálculo de hash SHA-256 sobre la evidencia (`captura.contenido_b64`).
     - Registro de auditoría inalterable en formato JSONL con encadenamiento criptográfico (`seq`, `timestamp_iso`, `minuto_partido`, `evento`, `datos`, `prev_hash`, `hash`).
   - `app/detector_engine.py`:
     - Validación de marca de agua contra `marcas_de_agua_validas` de `GET /partido` (rechazar señales ajenas como `vod.resumenes-deportivos.test`).
     - Verificación de `licenciatarios` autorizados en `GET /partido` (jamás bloquear dominios ni IPs de `canalnorte.test` / `envivo.canalnorte.test`).
     - Análisis de Riesgo Colateral consultando `GET /dns-pasivo?ip=<ip_servidor>`: si la IP aloja cualquier dominio legítimo que no sea parte de los dominios piratas detectados, recomendar obligatoriamente bloqueo por `"dominio"` (`host_stream`); si la IP es exclusiva del pirata, recomendar bloqueo por `"ip"` (`ip_servidor`).
     - Generación de expedientes completos estructurados con evidencia forense, hashes, ASN, lista de dominios co-alojados, redes de promoción (`promocion`) y decisión justificada.
   - `app/orchestrator.py`:
     - Loop de monitoreo de alta velocidad contra el simulador (`http://localhost:8080` configurable por argumento/env).
     - Consulta `GET /estado` en cada ciclo para obtener `minuto_actual` y `jueces_de_turno[0]`, cambiando automáticamente de juez cuando cambia el turno en el minuto 50 (`jueza-laura-ficticia` -> `juez-martin-ejemplo`) para tener 0 órdenes fuera de turno.
     - Envío inteligente a todos los proveedores de `GET /proveedores`: si la recomendación del expediente es `"ip"` pero un proveedor solo tiene `["dominio"]` en `capacidades` (ej. `valle`), envía para ese proveedor una orden firmada con `tipo="dominio"` y `objetivo=host_stream` para lograr 100% de cobertura de clientes y 0 órdenes rechazadas.
     - Monitoreo continuo del estado de las órdenes enviadas: si una orden pasa a `"estado": "fallida"` (ej. proveedor `cumbre` con 35% de tasa de falla), reintenta de inmediato generando un nuevo `orden_id`, firmándolo con el juez de turno actual y reenviándolo hasta que quede `"aplicada"`.
     - Monitoreo de `GET /reclamos`: si aparece cualquier reclamo, verifica la orden afectada, la levanta de inmediato con `POST /proveedores/<pid>/ordenes/<oid>/levantar` firmando `LEVANTAR|orden_id|juez_id` con el juez de turno actual y, si corresponde, la reemplaza por un bloqueo quirúrgico por dominio. Incluye también una función de demostración para poder disparar y resolver un reclamo de prueba en la demo.

3. **Construir la Interfaz Web Tri-Vista (`app/server.py` + `app/static/index.html`):**
   - Crea un servidor FastAPI (o HTTP/WebSocket limpio) con una interfaz web moderna, oscura (estilo aeroespacial/ciberdefensa Argentina Space) con 3 vistas en pestañas:
     1. **Centro de Comando Federal (SOC en Vivo):** reloj del partido, juez de turno actual, métricas en tiempo real (streams detectados, falsos positivos filtrados, cobertura de clientes %, visibilidad residual), tarjetas de estado de cada ISP (`Aurora`, `Andina`, `FibraValle`, `Cumbre`), tabla de expedientes y explorador de la cadena de auditoría SHA-256.
     2. **App Mobile del Juez de Turno:** vista tipo smartphone mostrando el expediente forense claro, semáforo de daño colateral, modo Auto-Asistido / Manual y botón para probar el levantamiento de un reclamo con firma judicial.
     3. **Portal Público de Transparencia:** registro ciudadano de bloqueos activos/vencidos, juzgado interviniente, hashes de evidencia y canal de reclamos para sitios afectados.

4. **Generar todos los entregables obligatorios en `entrega/` y probar con el evaluador oficial:**
   - Crea `entrega/propuesta_normativa.md` usando la propuesta normativa completa del `PLAN-MAESTRO-THEMIS-LIVE.md`.
   - Crea un script `scripts/correr_partido_completo.py` que inicie `simulador/servidor.py` con `--acelerar 60`, corra el orquestador de `THEMIS-LIVE` durante todo el partido (hasta el minuto 110 incluyendo los 5 min de gracia), guarde en `entrega/expediente_ejemplo.json` y `entrega/registro_auditoria.jsonl` los artefactos generados, y ejecute `python evaluacion/verificar.py --log salida/registro.jsonl`.
   - Ejecuta el script, verifica en consola que `evaluacion/verificar.py` reporte **7 de 7 fases piratas bloqueadas, 0 daño colateral, 0 falsos positivos, 0 bloqueos IP post-partido, 0 órdenes rechazadas y 0 órdenes fuera de turno**, y escribe un `README.md` impecable listo para entregar en Hacki.
```
