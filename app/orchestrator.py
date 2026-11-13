"""THEMIS-LIVE · Orquestador en tiempo real contra el simulador oficial.

Circuitо completo: detección → evidencia → juez de turno → ISPs → confirmación →
reintento → vencimiento → reclamos → auditoría encadenada.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import config
from .crypto_audit import (
    Ledger,
    firmar,
    mensaje_levantamiento,
    mensaje_orden,
)
from .detector_engine import (
    ContextoPartido,
    construir_expediente,
    decidir_bloqueo,
    dominio_base,
    host_de,
)


class SimClient:
    def __init__(self, base: str, timeout: float = 6.0) -> None:
        self.base = base.rstrip("/")
        self.timeout = timeout

    def _req(self, metodo: str, ruta: str, cuerpo: Optional[dict] = None) -> Tuple[int, Any]:
        datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
        req = urllib.request.Request(
            self.base + ruta, data=datos, method=metodo,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as err:
            try:
                return err.code, json.loads(err.read() or b"{}")
            except Exception:
                return err.code, {"error": "respuesta no JSON"}
        except Exception as exc:  # red caída / simulador apagado
            return 0, {"error": str(exc)}

    def get(self, ruta: str) -> Any:
        _, data = self._req("GET", ruta)
        return data

    def post(self, ruta: str, cuerpo: dict) -> Tuple[int, Any]:
        return self._req("POST", ruta, cuerpo)


@dataclass
class Orden:
    orden_id: str
    orden_base: str
    proveedor: str
    expediente_id: str
    tipo: str
    objetivo: str
    vence_min: int
    juez_id: str
    juzgado_id: str
    firma: str
    host: str
    ip: str
    enviada_min: float
    estado: str = "enviada"
    aplicada_min: Optional[float] = None
    finalizada_min: Optional[float] = None
    retry: int = 0
    motivo: str = ""
    confirmada: bool = False

    def como_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("firma", None)
        return d


class ThemisOrchestrator:
    def __init__(self, client: SimClient, ledger: Ledger, guardar_expedientes: Path,
                 verbose: bool = True, reanudar: bool = False) -> None:
        self.client = client
        self.ledger = ledger
        self.verbose = verbose
        self.guardar_expedientes = Path(guardar_expedientes)
        self.partido = client.get("/partido")
        self.ctx = ContextoPartido(self.partido)
        self.proveedores = client.get("/proveedores") or []
        self.juzgados = self._cargar_juzgados()
        self.clientes_totales = sum(int(p.get("clientes", 0)) for p in self.proveedores)

        self.detecciones_vistas: set = set()
        self.detecciones: List[Dict[str, Any]] = []
        self.expedientes: Dict[str, Dict[str, Any]] = {}
        self.expediente_por_stream: Dict[Tuple[str, str], str] = {}
        self.fases: Dict[Tuple[str, str], int] = {}
        self.ordenes: Dict[Tuple[str, str], Orden] = {}
        self.reclamos: List[Dict[str, Any]] = []
        self.reclamos_vistos: set = set()
        self.ultimo_lote_min = -1.0
        self.ultimo_reclamo_min = -1.0
        self.minuto = 0.0
        self.jueces_ahora: List[str] = []
        self.descartes_senal = 0
        self.descartes_licenciatario = 0
        self.errores_envio = 0
        self.reintentos = 0
        self.finalizado = False
        self._lock = threading.RLock()
        self._exportado = False
        self.contexto_extra = {}

        if reanudar:
            from . import resume
            estado = resume.reconstruir(self.ledger.ruta)
            self.detecciones_vistas = estado["detecciones_vistas"]
            self.expediente_por_stream = estado["expediente_por_stream"]
            self.fases = estado["fases"]
            self.expedientes = estado["expedientes"]
            self.ordenes = estado["ordenes"]
            self.descartes_senal = estado["descartes_senal"]
            self.descartes_licenciatario = estado["descartes_licenciatario"]
            self.reclamos = estado["reclamos"]
            self.reclamos_vistos = estado["reclamos_vistos"]
            self.detecciones = [{"id": d} for d in self.detecciones_vistas]
            if self.verbose:
                print(f"[THEMIS] reanudacion: {len(self.expedientes)} expedientes, "
                      f"{len(self.ordenes)} ordenes, {len(self.detecciones_vistas)} detecciones vistas",
                      flush=True)

    # ------------------------------------------------------------------ helpers
    def log(self, msg: str) -> None:
        if self.verbose:
            seguro = msg.encode("ascii", "replace").decode("ascii")
            print(f"[THEMIS {self.minuto:6.2f}] {seguro}", flush=True)

    def _cargar_juzgados(self) -> Dict[str, Any]:
        ruta = Path(config.JUZGADOS)
        if not ruta.exists():
            return {}
        data = json.loads(ruta.read_text(encoding="utf-8"))
        indice = {}
        for juzgado in data.get("juzgados", []):
            for juez in juzgado.get("jueces", []):
                indice[juez["id"]] = {"juez": juez, "juzgado": juzgado}
        return indice

    def _juez_de_turno(self) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        estado = self.client.get("/estado") or {}
        turnos = estado.get("jueces_de_turno") or []
        if not turnos:
            return None, None
        self.jueces_ahora = list(turnos)
        entrada = self.juzgados.get(turnos[0])
        if not entrada:
            return None, None
        return entrada["juez"], entrada["juzgado"]

    def _firmar_orden(self, orden: Dict[str, Any], clave: str) -> str:
        return firmar(clave, mensaje_orden(orden))

    def _proveedor(self, pid: str) -> Dict[str, Any]:
        for p in self.proveedores:
            if p.get("id") == pid:
                return p
        return {}

    # --------------------------------------------------------------- detecciones
    def _procesar_lote(self, ahora: float) -> None:
        lote = self.client.get(f"/detecciones?desde={self.ultimo_lote_min}") or {}
        self.ultimo_lote_min = float(lote.get("minuto_actual", ahora))
        for det in lote.get("detecciones", []):
            det_id = det.get("id")
            if not det_id or det_id in self.detecciones_vistas:
                continue
            self.detecciones_vistas.add(det_id)
            self.detecciones.append(det)
            self._evaluar_deteccion(det, ahora)

    def _evaluar_deteccion(self, det: Dict[str, Any], ahora: float) -> None:
        marca = det.get("marca_de_agua_extraida", "")
        valida, ref = self.ctx.marca_es_del_partido(marca)

        # Regla 1: si la marca no es la señal del partido, no se bloquea.
        if not valida:
            self.descartes_senal += 1
            self.ledger.registrar(
                "deteccion_descartada", ahora, deteccion_id=det.get("id"),
                motivo="marca_de_agua_ajena_al_partido",
                marca=marca, host=det.get("host_stream"),
                detalle="Evidencia no corresponde a la señal oficial; no se genera orden.",
            )
            self.log(f"descartada {det.get('id')} (marca ajena al partido)")
            return

        # Regla 2: licenciatario autorizado en sus propios dominios, jamás se bloquea.
        lic = self.ctx.es_licenciatario_autorizado(det)
        if lic:
            self.descartes_licenciatario += 1
            self.ledger.registrar(
                "deteccion_descartada", ahora, deteccion_id=det.get("id"),
                motivo="licenciatario_autorizado",
                marca=marca, host=det.get("host_stream"),
                licenciatario=lic.get("nombre"),
                detalle="Transmisión legal en dominio autorizado; no se genera orden.",
            )
            self.log(f"descartada {det.get('id')} (licenciatario {lic.get('nombre')})")
            return

        ip = str(det.get("ip_servidor", "")).strip()
        host = str(det.get("host_stream", "")).strip() or host_de(det.get("stream_url", ""))
        clave_stream = (ip, host)

        # Evidencia suplementaria de un expediente ya abierto.
        if clave_stream in self.expediente_por_stream:
            exp_id = self.expediente_por_stream[clave_stream]
            exp = self.expedientes[exp_id]
            exp.setdefault("detecciones", []).append(det.get("id"))
            self.ledger.registrar(
                "evidencia_agregada", ahora, expediente_id=exp_id, deteccion_id=det.get("id"),
                marca=marca, host=host, ip=ip,
            )
            return

        # DNS pasivo → regla de daño colateral.
        dns = self.client.get(f"/dns-pasivo?ip={ip}") or {}
        decision = decidir_bloqueo(ip, host, dns.get("dominios", []))

        juez, juzgado = self._juez_de_turno()
        if not juez or not juzgado:
            self.ledger.registrar(
                "error_operativo", ahora, deteccion_id=det.get("id"),
                motivo="sin_juez_de_turno_disponible",
            )
            return

        fase = self.fases.get(clave_stream, 0) + 1
        self.fases[clave_stream] = fase
        exp_num = len(self.expedientes) + 1
        exp_id = f"EXP-2026-{exp_num:04d}"
        expediente = construir_expediente(
            expediente_id=exp_id, deteccion=det, contexto=self.ctx, dns=dns,
            decision=decision, juez=juez, juzgado=juzgado, minuto=ahora, fase=fase,
        )
        expediente["detecciones"] = [det.get("id")]
        self.expedientes[exp_id] = expediente
        self.expediente_por_stream[clave_stream] = exp_id
        self.ledger.registrar(
            "expediente_creado", ahora, expediente_id=exp_id, deteccion_id=det.get("id"),
            host=host, ip=ip, asn=det.get("asn"), marca=marca,
            tipo_bloqueo=decision["tipo"], objetivo=decision["objetivo"],
            riesgo_colateral=decision["riesgo_colateral"],
            dominios_ajenos=decision["dominios_ajenos"],
            hash_captura=expediente["evidencia"]["captura"]["sha256_binario"],
        )
        self.log(
            f"expediente {exp_id}: {host} ({ip}) → bloqueo {decision['tipo']} "
            f"[{decision['riesgo_colateral']}]"
        )
        self._despachar(expediente, decision, juez, juzgado, ahora)

    # ------------------------------------------------------------------ despacho
    def _despachar(self, expediente: Dict[str, Any], decision: Dict[str, Any],
                   juez: Dict[str, Any], juzgado: Dict[str, Any], ahora: float,
                   host: Optional[str] = None, ip: Optional[str] = None,
                   sufijo: str = "") -> None:
        exp_id = expediente["expediente_id"]
        host = host or expediente["servidor"]["host_stream"]
        ip = ip or expediente["servidor"]["ip"]
        exp_num = exp_id.split("-")[-1]
        proveedores = self.client.get("/proveedores") or self.proveedores
        for prov in proveedores:
            pid = prov.get("id")
            caps = prov.get("capacidades", [])
            tipo, objetivo = decision["tipo"], decision["objetivo"]
            motivo_adaptacion = ""
            if tipo == "ip" and "ip" not in caps:
                tipo, objetivo = "dominio", host
                motivo_adaptacion = f"{pid} no aplica bloqueos por IP; se adapta a dominio"
            elif tipo == "dominio" and "dominio" not in caps:
                tipo, objetivo = "ip", ip
                motivo_adaptacion = f"{pid} no aplica bloqueos por dominio; se adapta a IP"
            orden_base = f"ord-{exp_num}-{pid}{sufijo}"
            self._enviar_orden(
                orden_base=orden_base, proveedor=pid, expediente_id=exp_id,
                tipo=tipo, objetivo=objetivo, host=host, ip=ip,
                motivo_adaptacion=motivo_adaptacion, ahora=ahora,
            )

    def _enviar_orden(self, *, orden_base: str, proveedor: str, expediente_id: str,
                      tipo: str, objetivo: str, host: str, ip: str,
                      motivo_adaptacion: str, ahora: float,
                      retry: int = 0) -> bool:
        juez, juzgado = self._juez_de_turno()
        if not juez or not juzgado:
            return False
        orden_id = orden_base if retry == 0 else f"{orden_base}-r{retry}"
        vence = int(self.ctx.fin_min)
        if vence <= ahora:
            self.ledger.registrar(
                "orden_omitida", ahora, proveedor=proveedor, orden_id=orden_id,
                motivo="el partido ya finalizó; no corresponde emitir nuevos bloqueos",
            )
            return False
        orden = {
            "orden_id": orden_id,
            "expediente_id": expediente_id,
            "tipo": tipo,
            "objetivo": objetivo,
            "vence_min": vence,
            "juzgado_id": juzgado["id"],
            "juez_id": juez["id"],
        }
        orden["firma"] = self._firmar_orden(orden, juez.get("clave_firma_demo", ""))
        estado_http, respuesta = self.client.post(f"/proveedores/{proveedor}/ordenes", orden)
        registro = Orden(
            orden_id=orden_id, orden_base=orden_base, proveedor=proveedor,
            expediente_id=expediente_id, tipo=tipo, objetivo=objetivo,
            vence_min=vence, juez_id=juez["id"], juzgado_id=juzgado["id"],
            firma=orden["firma"], host=host, ip=ip, enviada_min=round(ahora, 3),
            retry=retry,
        )
        if estado_http in (200, 201, 202):
            self.ordenes[(proveedor, orden_id)] = registro
            self.ledger.registrar(
                "orden_emitida", ahora, proveedor=proveedor, orden_id=orden_id,
                expediente_id=expediente_id, tipo=tipo, objetivo=objetivo,
                vence_min=vence, juez_id=juez["id"], juzgado_id=juzgado["id"],
                firma_hmac=orden["firma"], adaptacion_capacidades=motivo_adaptacion,
                hash_expediente=self.expedientes.get(expediente_id, {}).get(
                    "cadena_de_custodia", {}).get("hash_expediente"),
            )
            self.log(
                f"orden {orden_id} → {proveedor} [{tipo}:{objetivo}]"
                + (f" ({motivo_adaptacion})" if motivo_adaptacion else "")
            )
            return True

        self.errores_envio += 1
        registro.estado = "rechazada"
        registro.motivo = str(respuesta.get("error", respuesta))
        self.ordenes[(proveedor, orden_id)] = registro
        self.ledger.registrar(
            "orden_rechazada", ahora, proveedor=proveedor, orden_id=orden_id,
            expediente_id=expediente_id, http=estado_http, motivo=registro.motivo,
        )
        self.log(f"RECHAZADA {orden_id} en {proveedor}: {registro.motivo}")
        return False

    # ---------------------------------------------------------------- monitoreo
    def _monitorear_ordenes(self, ahora: float) -> None:
        proveedores_con_ordenes = {pid for (pid, _) in self.ordenes}
        for pid in list(proveedores_con_ordenes):
            lista = self.client.get(f"/proveedores/{pid}/ordenes")
            if not isinstance(lista, list):
                continue
            for item in lista:
                oid = item.get("orden_id")
                registro = self.ordenes.get((pid, oid))
                if registro is None:
                    continue
                estado = item.get("estado", "")
                if estado == "aplicada" and not registro.confirmada:
                    registro.estado = "aplicada"
                    registro.confirmada = True
                    registro.aplicada_min = float(item.get("aplicada_min") or ahora)
                    self.ledger.registrar(
                        "orden_aplicada", registro.aplicada_min, proveedor=pid,
                        orden_id=oid, expediente_id=registro.expediente_id,
                        tipo=registro.tipo, objetivo=registro.objetivo,
                        minutos_desde_envio=round(registro.aplicada_min - registro.enviada_min, 2),
                    )
                    self.log(f"✔ aplicada {oid} en {pid} al min {registro.aplicada_min:.2f}")
                elif estado == "fallida" and registro.retry < config.MAX_REINTENTOS_ISP:
                    registro.estado = "fallida"
                    registro.motivo = item.get("motivo", "")
                    if ahora >= self.ctx.fin_min - 0.1:
                        self.ledger.registrar(
                            "orden_fallida_sin_reintento", ahora, proveedor=pid, orden_id=oid,
                            expediente_id=registro.expediente_id,
                            motivo="partido finalizado; el bloqueo caduca de todos modos",
                        )
                        registro.retry = config.MAX_REINTENTOS_ISP
                        continue
                    self.reintentos += 1
                    siguiente = registro.retry + 1
                    registro.retry = config.MAX_REINTENTOS_ISP  # esta orden no se reintenta de nuevo
                    self.ledger.registrar(
                        "orden_fallida", ahora, proveedor=pid, orden_id=oid,
                        expediente_id=registro.expediente_id, motivo=registro.motivo,
                        accion="reenviar con nuevo orden_id firmado por el juez de turno",
                    )
                    self.log(f"fallo {oid} en {pid}; reintentando")
                    self._enviar_orden(
                        orden_base=registro.orden_base, proveedor=pid,
                        expediente_id=registro.expediente_id, tipo=registro.tipo,
                        objetivo=registro.objetivo, host=registro.host, ip=registro.ip,
                        motivo_adaptacion="", ahora=ahora, retry=siguiente,
                    )
                elif estado in ("vencida", "levantada") and registro.estado != estado:
                    registro.estado = estado
                    registro.finalizada_min = float(item.get("finalizada_min") or ahora)
                    self.ledger.registrar(
                        f"orden_{estado}", registro.finalizada_min, proveedor=pid,
                        orden_id=oid, expediente_id=registro.expediente_id,
                        tipo=registro.tipo, objetivo=registro.objetivo,
                    )

    def _afecta_dominio(self, orden: Orden, dominio: str) -> bool:
        if not dominio:
            return False
        if orden.tipo == "dominio":
            return orden.objetivo == dominio
        if orden.tipo == "ip":
            exp = self.expedientes.get(orden.expediente_id) or {}
            dominios = exp.get("servidor", {}).get("dominios_en_ip", [])
            return dominio in dominios
        return False

    def _monitorear_reclamos(self, ahora: float) -> None:
        lote = self.client.get(f"/reclamos?desde={self.ultimo_reclamo_min}") or {}
        self.ultimo_reclamo_min = float(lote.get("minuto_actual", ahora))
        for reclamo in lote.get("reclamos", []):
            rid = reclamo.get("id")
            if not rid or rid in self.reclamos_vistos:
                continue
            self.reclamos_vistos.add(rid)
            proveedor = reclamo.get("proveedor")
            dominio = reclamo.get("dominio")
            registro = self.ordenes.get((proveedor, reclamo.get("orden_id")))
            if registro is None:
                # La API de reclamos no siempre informa la orden: se resuelve por dominio afectado.
                candidatos = [
                    o for o in self.ordenes.values()
                    if o.proveedor == proveedor and o.estado in ("enviada", "aplicada")
                    and self._afecta_dominio(o, dominio)
                ]
                candidatos.sort(key=lambda o: (o.estado == "aplicada", o.aplicada_min or o.enviada_min))
                registro = candidatos[-1] if candidatos else None
            resultado = {
                "id": rid, "dominio": dominio,
                "proveedor": proveedor,
                "orden_id": registro.orden_id if registro else reclamo.get("orden_id"),
                "minuto": reclamo.get("minuto"),
                "mensaje": reclamo.get("mensaje"), "estado": "en revisión",
            }
            if registro is None:
                resultado["estado"] = "sin orden asociada"
                self.reclamos.append(resultado)
                continue
            juez, juzgado = self._juez_de_turno()
            if not juez:
                resultado["estado"] = "sin juez de turno"
                self.reclamos.append(resultado)
                continue
            firma = firmar(juez.get("clave_firma_demo", ""),
                           mensaje_levantamiento(registro.orden_id, juez["id"]))
            http, resp = self.client.post(
                f"/proveedores/{registro.proveedor}/ordenes/{registro.orden_id}/levantar",
                {"juez_id": juez["id"], "firma": firma,
                 "motivo": f"Reclamo {rid} verificado: {reclamo.get('dominio')} afectado por error"},
            )
            if http in (200, 201, 202):
                registro.estado = "levantada"
                resultado["estado"] = "levantada y reemplazada"
                self.ledger.registrar(
                    "reclamo_resuelto", ahora, reclamo_id=rid,
                    dominio=reclamo.get("dominio"), proveedor=registro.proveedor,
                    orden_levantada=registro.orden_id, juez_id=juez["id"],
                    firma_levantamiento=firma,
                    accion="levantamiento firmado + bloqueo quirúrgico por dominio",
                )
                self._reemplazar_por_dominio(registro, juez, juzgado, ahora)
                self.log(f"⚖ reclamo {rid} resuelto: {reclamo.get('dominio')}")
            else:
                resultado["estado"] = f"error al levantar: {resp.get('error', http)}"
            self.reclamos.append(resultado)

    def _reemplazar_por_dominio(self, registro: Orden, juez: Dict[str, Any],
                                juzgado: Dict[str, Any], ahora: float) -> None:
        if registro.tipo == "dominio" or not registro.host:
            return
        exp = self.expedientes.get(registro.expediente_id)
        if not exp:
            return
        decision = {"tipo": "dominio", "objetivo": registro.host, "riesgo_colateral": "CONTROLADO"}
        self._despachar(exp, decision, juez, juzgado, ahora,
                        host=registro.host, ip=registro.ip, sufijo="-precisa")

    # ---------------------------------------------------------------- métricas
    def cobertura_pct(self, expediente_id: str) -> float:
        pids = {
            o.proveedor for o in self.ordenes.values()
            if o.expediente_id == expediente_id and o.estado in ("enviada", "aplicada", "vencida", "levantada")
            and o.aplicada_min is not None
        }
        if not self.clientes_totales:
            return 0.0
        return round(100.0 * sum(int(self._proveedor(p).get("clientes", 0)) for p in pids)
                     / self.clientes_totales, 1)

    def estado_dashboard(self) -> Dict[str, Any]:
        with self._lock:
            exp_list = []
            for exp in self.expedientes.values():
                exp_list.append({
                    "expediente_id": exp["expediente_id"],
                    "deteccion_id": exp.get("deteccion_id"),
                    "host": exp["servidor"]["host_stream"],
                    "ip": exp["servidor"]["ip"],
                    "asn": exp["servidor"]["asn"],
                    "organizacion": exp["servidor"]["organizacion"],
                    "tipo": exp["orden_solicitada"]["tipo"],
                    "objetivo": exp["orden_solicitada"]["objetivo"],
                    "riesgo": exp["riesgo_colateral"]["nivel"],
                    "dominios_ajenos": exp["riesgo_colateral"]["dominios_ajenos"],
                    "justificacion": exp["riesgo_colateral"]["justificacion"],
                    "hash": exp["evidencia"]["captura"]["sha256_binario"],
                    "marca": exp["evidencia"]["marca_de_agua"],
                    "juez": exp["juez"]["nombre"],
                    "juzgado": exp["juez"]["juzgado"],
                    "cobertura_pct": self.cobertura_pct(exp["expediente_id"]),
                    "ordenes": [
                        o.como_dict() for o in self.ordenes.values()
                        if o.expediente_id == exp["expediente_id"]
                    ],
                })
            ordenes = [o.como_dict() for o in self.ordenes.values()]
            return {
                "proyecto": "THEMIS-LIVE",
                "tagline": "Plataforma federal de órdenes judiciales en vivo",
                "partido": self.partido.get("nombre"),
                "fin_min": self.ctx.fin_min,
                "minuto": self.minuto,
                "finalizado": self.finalizado,
                "jueces_de_turno": self.jueces_ahora,
                "proveedores": self.proveedores,
                "clientes_totales": self.clientes_totales,
                "metricas": {
                    "detecciones": len(self.detecciones),
                    "descartes_senal": self.descartes_senal,
                    "descartes_licenciatario": self.descartes_licenciatario,
                    "expedientes": len(self.expedientes),
                    "ordenes": len(self.ordenes),
                    "aplicadas": sum(1 for o in self.ordenes.values() if o.confirmada),
                    "fallidas": sum(1 for o in self.ordenes.values() if o.estado == "fallida"),
                    "reintentos": self.reintentos,
                    "reclamos": len(self.reclamos),
                    "errores_envio": self.errores_envio,
                },
                "expedientes": exp_list,
                "ordenes": ordenes,
                "reclamos": self.reclamos,
                "auditoria": {
                    "eventos": len(self.ledger.eventos),
                    "ultimo_hash": self.ledger.ultimo_hash,
                    "integridad": self.ledger.verificar(),
                    "ultimos": self.ledger.eventos[-12:],
                },
            }

    # --------------------------------------------------------------------- run
    def run(self, hasta_min: Optional[float] = None, timeout_real: Optional[float] = None) -> None:
        limite = float(hasta_min if hasta_min is not None else self.ctx.fin_min + config.MARGEN_GRACIA_MIN + 0.5)
        inicio_real = time.time()
        try:
            while True:
                estado = self.client.get("/estado") or {}
                if not estado:
                    time.sleep(0.2)
                    continue
                with self._lock:
                    self.minuto = float(estado.get("minuto_actual", self.minuto))
                    self.jueces_ahora = list(estado.get("jueces_de_turno") or self.jueces_ahora)
                self._procesar_lote(self.minuto)
                self._monitorear_ordenes(self.minuto)
                self._monitorear_reclamos(self.minuto)
                if self.minuto >= limite:
                    break
                if timeout_real is not None and (time.time() - inicio_real) > timeout_real:
                    self.ledger.registrar("timeout_operativo", self.minuto,
                                          motivo=f"se alcanzó el límite real de {timeout_real}s")
                    break
                time.sleep(config.POLL_SEGUNDOS)
        finally:
            self.finalizado = True
            self.exportar()
            self.log("corrida finalizada y artefactos exportados")

    def exportar(self) -> None:
        if self._exportado:
            return
        self._exportado = True
        self.guardar_expedientes.parent.mkdir(parents=True, exist_ok=True)
        datos = {
            "proyecto": "THEMIS-LIVE",
            "partido": self.partido.get("nombre"),
            "expedientes": list(self.expedientes.values()),
            "ordenes": [o.como_dict() for o in self.ordenes.values()],
            "reclamos": self.reclamos,
            "resumen": {
                "detecciones": len(self.detecciones),
                "descartes_senal": self.descartes_senal,
                "descartes_licenciatario": self.descartes_licenciatario,
                "expedientes": len(self.expedientes),
                "ordenes": len(self.ordenes),
                "aplicadas": sum(1 for o in self.ordenes.values() if o.confirmada),
                "reintentos": self.reintentos,
                "reclamos": len(self.reclamos),
                "integridad_ledger": self.ledger.verificar(),
            },
        }
        self.guardar_expedientes.write_text(
            json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        self.contexto_extra["exportado_iso"] = datetime.now(timezone.utc).isoformat()
