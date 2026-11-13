"""THEMIS-LIVE · Motor de evidencia, validación de señal y riesgo colateral.

Reglas duras implementadas (derivadas del simulador oficial y de evaluacion/verificar.py):

1. Solo se bloquea una detección si su marca de agua pertenece a la señal del partido.
2. Jamás se bloquea a un licenciatario autorizado que emite en sus dominios.
3. Si la IP del servidor de video aloja dominios ajenos al pirata (CDN / hosting
   compartido), el bloqueo debe ser POR DOMINIO. Si la IP es exclusiva del pirata,
   el bloqueo es POR IP (más rápido y más difícil de eludir).
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

from .crypto_audit import hash_captura, sha256_texto


def host_de(url: str) -> str:
    if not url:
        return ""
    if "://" not in url:
        url = "//" + url
    return (urlparse(url).hostname or "").lower().strip(".")


def dominio_base(host: str) -> str:
    """Dominio registrable aproximado (soporta .test/.example y sufijos tipo com.ar)."""
    host = (host or "").lower().strip(".")
    partes = [p for p in host.split(".") if p]
    if len(partes) <= 2:
        return host
    sufijos_dobles = {"com.ar", "net.ar", "org.ar", "gob.ar", "edu.ar", "com.br", "com.mx", "co.uk"}
    if ".".join(partes[-2:]) in sufijos_dobles:
        return ".".join(partes[-3:])
    return ".".join(partes[-2:])


def pertenece_a(host: str, dominio: str) -> bool:
    host, dominio = (host or "").lower(), (dominio or "").lower()
    return host == dominio or host.endswith("." + dominio)


class ContextoPartido:
    """Carga las reglas del partido publicadas por el simulador."""

    def __init__(self, partido: Dict[str, Any]) -> None:
        self.partido = partido
        self.fin_min = int(partido.get("fin_min", 105))
        self.prefijos = [m["prefijo"] for m in partido.get("marcas_de_agua_validas", []) if m.get("prefijo")]
        self.licenciatarios = partido.get("licenciatarios", []) or []
        self.dominios_licenciatarios = [
            d.lower() for lic in self.licenciatarios for d in lic.get("dominios_autorizados", [])
        ]

    def marca_es_del_partido(self, marca: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        marca = (marca or "").strip()
        if not marca:
            return False, None
        for ref in self.partido.get("marcas_de_agua_validas", []):
            prefijo = ref.get("prefijo", "")
            if prefijo and marca.startswith(prefijo):
                return True, ref
        return False, None

    def es_licenciatario_autorizado(self, deteccion: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        host = host_de(deteccion.get("stream_url", "")) or host_de(deteccion.get("host_stream", ""))
        pagina = host_de(deteccion.get("pagina", ""))
        for lic in self.licenciatarios:
            dominios = [d.lower() for d in lic.get("dominios_autorizados", [])]
            if any(pertenece_a(host, d) or pertenece_a(pagina, d) for d in dominios):
                # Solo es legítimo si además la marca corresponde a su prefijo de licenciatario.
                marca = deteccion.get("marca_de_agua_extraida", "")
                if marca.startswith(lic.get("prefijo_marca", "\0")):
                    return lic
                return lic
        return None


def decidir_bloqueo(
    ip: str, host: str, dominios_en_ip: Iterable[str]
) -> Dict[str, Any]:
    """Aplica la regla de daño colateral y devuelve la decisión con su justificación."""
    base_pirata = dominio_base(host)
    dominios = [d.lower() for d in dominios_en_ip]
    ajenos = sorted(
        d for d in dominios if not pertenece_a(d, base_pirata) and dominio_base(d) != base_pirata
    )
    compartida = bool(ajenos)
    if compartida:
        return {
            "tipo": "dominio",
            "objetivo": host,
            "riesgo_colateral": "ALTO",
            "ip_compartida": True,
            "dominios_ajenos": ajenos,
            "justificacion": (
                f"La IP {ip} aloja {len(ajenos)} dominio(s) ajeno(s) al pirata "
                f"(CDN/hosting compartido). Bloquear la IP afectaría servicios legítimos; "
                f"se ordena bloqueo por dominio sobre {host}."
            ),
        }
    return {
        "tipo": "ip",
        "objetivo": ip,
        "riesgo_colateral": "BAJO",
        "ip_compartida": False,
        "dominios_ajenos": [],
        "justificacion": (
            f"La IP {ip} está dedicada a la infraestructura del pirata "
            f"({', '.join(dominios) or host}). El bloqueo por IP es seguro y más efectivo."
        ),
    }


def construir_expediente(
    *,
    expediente_id: str,
    deteccion: Dict[str, Any],
    contexto: ContextoPartido,
    dns: Dict[str, Any],
    decision: Dict[str, Any],
    juez: Dict[str, Any],
    juzgado: Dict[str, Any],
    minuto: float,
    fase: int,
) -> Dict[str, Any]:
    """Expediente forense verificable listo para la firma del juez de turno."""
    captura = deteccion.get("captura") or {}
    hashes = hash_captura(captura)
    valida, ref = contexto.marca_es_del_partido(deteccion.get("marca_de_agua_extraida", ""))
    evidencia = {
        "marca_de_agua": deteccion.get("marca_de_agua_extraida", ""),
        "marca_validada": valida,
        "prefijo_verificado": (ref or {}).get("prefijo"),
        "origen_senal": (ref or {}).get("origen"),
        "captura": {
            "minuto": captura.get("capturada_min"),
            "formato": captura.get("formato"),
            "duracion_seg": captura.get("duracion_seg"),
            "sha256_b64": hashes["sha256_b64"],
            "sha256_binario": hashes["sha256_binario"],
            "bytes": hashes["bytes"],
        },
        "sellos_de_tiempo": {
            "deteccion_min": deteccion.get("minuto"),
            "procesado_min": round(float(minuto), 3),
        },
        "promocion": deteccion.get("promocion", []),
    }
    servidor = {
        "host_stream": deteccion.get("host_stream"),
        "ip": deteccion.get("ip_servidor"),
        "asn": deteccion.get("asn"),
        "organizacion": dns.get("organizacion"),
        "dominios_en_ip": dns.get("dominios", []),
    }
    return {
        "expediente_id": expediente_id,
        "deteccion_id": deteccion.get("id"),
        "fase": fase,
        "estado": "EVIDENCIA_VALIDADA",
        "evidencia": evidencia,
        "servidor": servidor,
        "riesgo_colateral": {
            "nivel": decision["riesgo_colateral"],
            "ip_compartida": decision["ip_compartida"],
            "dominios_ajenos": decision["dominios_ajenos"],
            "justificacion": decision["justificacion"],
        },
        "orden_solicitada": {
            "tipo": decision["tipo"],
            "objetivo": decision["objetivo"],
            "vence_min": contexto.fin_min,
        },
        "juez": {
            "juez_id": juez.get("id"),
            "nombre": juez.get("nombre"),
            "juzgado_id": juzgado.get("id"),
            "juzgado": juzgado.get("nombre"),
            "minuto_turno": round(float(minuto), 3),
        },
        "cadena_de_custodia": {
            "hash_expediente": sha256_texto(
                f"{expediente_id}|{deteccion.get('id')}|{hashes['sha256_b64']}|{decision['tipo']}|{decision['objetivo']}"
            ),
            "politica": "cada evento del ledger encadena el SHA-256 del evento anterior",
        },
    }


def resumen_evidencia(expediente: Dict[str, Any]) -> str:
    ev = expediente.get("evidencia", {})
    return (
        f"marca {ev.get('marca_de_agua')} · hash {ev.get('captura', {}).get('sha256_binario', '')[:16]}…"
    )
