"""Reanudación del motor tras un reinicio abrupto.

Reconstruye el estado del orquestador leyendo el ledger de auditoría (que ya está
en disco y es la fuente de verdad encadenada). Permite que THEMIS-LIVE retome un
partido en curso sin duplicar expedientes ni órdenes.

Uso: ThemisOrchestrator(..., reanudar=True) + Ledger(..., reanudar=True).

El ledger NO se trunca cuando reanudar=True; la cadena de hashes continúa.
Los eventos reconstruidos son parciales (expedientes mínimos): toda decisión
futura sigue pasando por las mismas reglas de validación.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .orchestrator import Orden


def reconstruir(ruta_auditoria: Path) -> Dict[str, Any]:
    vistas: set = set()
    por_stream: Dict[Tuple[str, str], str] = {}
    fases: Dict[Tuple[str, str], int] = {}
    stream_de: Dict[str, Tuple[str, str]] = {}
    exp_min: Dict[str, Dict[str, Any]] = {}
    ordenes: Dict[Tuple[str, str], Orden] = {}
    desc_sen = desc_lic = 0
    reclamos: List[dict] = []
    reclamos_vistos: set = set()
    detecciones = 0

    if not Path(ruta_auditoria).exists():
        return _vacio()

    for linea in Path(ruta_auditoria).read_text(encoding="utf-8").splitlines():
        if not linea.strip():
            continue
        e = json.loads(linea)
        ev = e.get("evento", "")
        d = e.get("datos", {}) or {}

        # Todo evento con deteccion_id marca la detección como vista
        did = d.get("deteccion_id")
        if did:
            if did not in vistas:
                detecciones += 1
            vistas.add(did)

        if ev == "deteccion_descartada":
            if d.get("motivo") == "licenciatario_autorizado":
                desc_lic += 1
            else:
                desc_sen += 1
        elif ev == "expediente_creado":
            exp_id = d["expediente_id"]
            ip = str(d.get("ip", ""))
            host = str(d.get("host", ""))
            clave = (ip, host)
            por_stream[clave] = exp_id
            stream_de[exp_id] = clave
            fases[clave] = fases.get(clave, 0) + 1
            exp_min[exp_id] = {
                "expediente_id": exp_id,
                "deteccion_id": did,
                "detecciones": [did] if did else [],
                "reconstruido_reanudacion": True,
                "servidor": {"host_stream": host, "ip": ip,
                             "asn": str(d.get("asn", "")),
                             "organizacion": "reanudado desde el ledger"},
                "juez": {"nombre": d.get("juez_id", ""), "juzgado":
                         str(d.get("juzgado_id", ""))},
                "orden_solicitada": {"tipo": d.get("tipo_bloqueo", ""),
                                     "objetivo": d.get("objetivo", "")},
                "evidencia": {"captura": {"sha256_binario": d.get("hash_captura", "")},
                              "marca_de_agua": d.get("marca", "")},
                "cadena_de_custodia": {
                    "hash_expediente": d.get("hash_captura", ""),
                    "reemison_republica_no_requerida": True},
            }
        elif ev == "orden_emitida":
            exp_id = d.get("expediente_id", "")
            ip, host = stream_de.get(exp_id, ("", ""))
            pprov = d.get("proveedor", "")
            ordenes[(pprov, d.get("orden_id", ""))] = Orden(
                orden_id=d.get("orden_id", ""),
                orden_base=d.get("orden_id", ""),
                proveedor=pprov, expediente_id=exp_id,
                tipo=d.get("tipo", ""), objetivo=d.get("objetivo", ""),
                vence_min=int(d.get("vence_min", 105)),
                juez_id=d.get("juez_id", ""), juzgado_id=d.get("juzgado_id", ""),
                firma=d.get("firma_hmac", ""), host=host, ip=ip,
                enviada_min=float(e.get("minuto_partido", 0.0)),
            )
        elif ev == "orden_aplicada":
            reg = ordenes.get((d.get("proveedor"), d.get("orden_id")))
            if reg:
                reg.estado = "aplicada"
                reg.confirmada = True
                reg.aplicada_min = float(e.get("minuto_partido", 0.0))
        elif ev == "orden_fallida_sin_reintento":
            reg = ordenes.get((d.get("proveedor"), d.get("orden_id")))
            if reg:
                reg.estado = "fallida"
                reg.retry = 999
        elif ev == "orden_fallida":
            reg = ordenes.get((d.get("proveedor"), d.get("orden_id")))
            if reg:
                reg.estado = "fallida"
        elif ev == "orden_vencida":
            reg = ordenes.get((d.get("proveedor"), d.get("orden_id")))
            if reg:
                reg.estado = "vencida"
        elif ev == "reclamo_emitido":
            clave = d.get("reclamo_id") or f"{e.get('minuto_partido')}|{d.get('dominio','')}"
            reclamos_vistos.add(clave)
            reclamos.append(d)
        elif ev == "reclamo_resuelto":
            reclamos_vistos.add(d.get("reclamo_id", ""))
            reclamos.append(d)

    return {
        "detecciones_vistas": vistas,
        "expediente_por_stream": por_stream,
        "fases": fases,
        "expedientes": exp_min,
        "ordenes": ordenes,
        "descartes_senal": desc_sen,
        "descartes_licenciatario": desc_lic,
        "reclamos": reclamos,
        "reclamos_vistos": reclamos_vistos,
        "detecciones_total": detecciones,
    }


def _vacio() -> Dict[str, Any]:
    return {
        "detecciones_vistas": set(),
        "expediente_por_stream": {},
        "fases": {},
        "expedientes": {},
        "ordenes": {},
        "descartes_senal": 0,
        "descartes_licenciatario": 0,
        "reclamos": [],
        "reclamos_vistos": set(),
        "detecciones_total": 0,
    }
