# THEMIS-LIVE

**Plataforma federal de órdenes judiciales en vivo y bloqueo dinámico antipiratería con daño colateral cero.**

Track: **QualyData · Streaming** — Hackathon Argentina Space 2026 (Salta, 11 al 13 de noviembre).

---

## Qué resuelve

Un partido dura 105 minutos; un sitio pirata cambia de dominio o de servidor en minutos. THEMIS-LIVE automatiza el circuito completo exigido por el desafío:

```
detección → expediente forense → juez de turno → todos los ISPs → confirmación
          → reintento ante fallas → vencimiento automático → reclamos → auditoría
```

Además de correr el circuito, THEMIS-LIVE demuestra **por qué** cada decisión es correcta: cada bloqueo queda respaldado por un expediente con hashes SHA-256, la verificación de la marca de agua, el análisis de DNS pasivo y una cadena de auditoría inalterable.

## Decisiones de diseño (y las trampas del escenario que resuelven)

| Riesgo del escenario | Decisión de THEMIS-LIVE |
| --- | --- |
| Detección de un stream que no es el partido | La marca de agua se compara contra los prefijos válidos de `GET /partido`. Si no coincide, se descarta y **no se bloquea**. |
| Licenciatario autorizado emitiendo legalmente | Se excluyen sus dominios autorizados. Cero falsos positivos. |
| CDN / hosting compartido (bloquear IP tira sitios legítimos) | Se consulta `GET /dns-pasivo?ip=`. Si hay dominios ajenos, se ordena **bloqueo por dominio**; si la IP es dedicada, **bloqueo por IP**. |
| ISP que solo acepta bloqueos por dominio (`valle`) | La orden se adapta por proveedor: mismo expediente, tipo de bloqueo compatible con sus capacidades. Cero órdenes rechazadas. |
| ISP inestable que falla (`cumbre`) | Se monitorea el estado de cada orden; ante `fallida` se reenvía con **nuevo `orden_id`** firmado por el juez de turno vigente. |
| Cambio de turno judicial a mitad del partido | Cada firma consulta `GET /estado` y usa al juez de turno actual. Cero órdenes fuera de turno. |
| Bloqueos que quedan activos después del partido | `vence_min = fin_min`: el simulador los vence automáticamente al minuto 105. |
| Reclamos de sitios legítimos | Se verifica el reclamo, se levanta la orden con firma `LEVANTAR|orden_id|juez_id` y se reemplaza por un bloqueo quirúrgico por dominio. |

## Arquitectura

```
themis-live/
├── app/
│   ├── config.py             rutas y parámetros
│   ├── crypto_audit.py       firmas HMAC-SHA256 + ledger encadenado SHA-256
│   ├── detector_engine.py    validación de señal, licenciatarios, riesgo colateral, expedientes
│   ├── orchestrator.py       loop en vivo: detecciones, órdenes, reintentos, reclamos
│   ├── dashboard_server.py   servidor web stdlib + /api/state
│   └── static/index.html     SPA con SOC, consola móvil del juez y portal de transparencia
├── scripts/
│   ├── correr_partido_completo.py   corre el partido y ejecuta el verificador oficial
│   └── demo_reclamo.py              demuestra un reclamo resuelto (para el video)
├── simulador/  datos/  evaluacion/  (código y datos oficiales del desafío)
├── entrega/
│   ├── expediente_ejemplo.json
│   ├── registro_auditoria.jsonl
│   ├── propuesta_normativa.md
│   ├── resultado_verificacion.json
│   └── resumen_corrida.json
└── README.md
```

## Cómo correrlo

Requiere **Python 3.9+** y solo la biblioteca estándar.

```bash
# Partido completo (110 minutos simulados) + verificación oficial + exportación
python scripts/correr_partido_completo.py --acelerar 60

# Sin dashboard
python scripts/correr_partido_completo.py --acelerar 120 --sin-dashboard

# Viernes 13 (conectando a la instancia externa del simulador que asigne la organización)
python scripts/correr_partido_completo.py --url http://IP_DEL_SIMULADOR:8080

# Levantar solo el dashboard sobre la última corrida guardada
python -m app.dashboard_server --puerto 8090
```

Mientras corre, el dashboard queda en `http://127.0.0.1:8090` con tres vistas:

1. **Mesa de situación:** cronómetro, juez de turno, métricas, estado de cada ISP, expedientes y cadena de auditoría.
2. **Consola del juez:** vista móvil con el expediente, semáforo de riesgo colateral y firma.
3. **Registro público:** qué se bloqueó, con qué evidencia, por orden de quién y hasta cuándo.

Al finalizar, el script ejecuta el evaluador oficial:

```bash
python evaluacion/verificar.py --log salida/registro.jsonl
```

### Resultado sobre el escenario de práctica

```
fases piratas bloqueadas ......... 7 de 7
clientes cubiertos por fase ...... 100 %
visibilidad residual promedio .... 3.9 %
daño colateral ................... 0
falsos positivos ................. 0
bloqueos IP activos post-partido . 0
órdenes rechazadas ............... 0
órdenes fuera de turno ........... 0
```

## Supuestos

- El simulador es la única fuente de verdad y todos sus datos son ficticios.
- La firma HMAC-SHA256 es la simplificación de firma judicial provista por el desafío.
- El juez puede operar en modo **auto-asistido** (pre-autorización de expedientes que cumplen todos los checks) o **manual interactivo** desde la consola móvil; el modo no altera la validez legal del registro.
- `vence_min = fin_min`: ningún bloqueo por IP sobrevive al partido.

## Código preexistente

- `simulador/`, `datos/`, `evaluacion/` y `ejemplos/` provienen del repositorio oficial `qualydata-org/desafio-futbol` y **no fueron modificados**.
- Todo lo que está en `app/`, `scripts/` y `entrega/` fue desarrollado durante el hackathon.
- Sin dependencias externas: solo biblioteca estándar de Python.
