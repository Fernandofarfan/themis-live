"""THEMIS-LIVE · Demostración de un reclamo ciudadano resuelto en vivo.

Simula un error operativo (una orden por IP sobre un hosting compartido), deja que el
sitio legítimo reclame y muestra la resolución automática: levantamiento firmado por el
juez de turno y reemplazo por un bloqueo quirúrgico por dominio.

Uso:
    python scripts/demo_reclamo.py --acelerar 40
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

ENTORNO = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

from app import config  # noqa: E402
from app.crypto_audit import Ledger, firmar, mensaje_orden  # noqa: E402
from app.orchestrator import Orden, SimClient, ThemisOrchestrator  # noqa: E402


def esperar(url: str, timeout: float = 40.0) -> dict:
    inicio = time.time()
    while time.time() - inicio < timeout:
        try:
            with urllib.request.urlopen(url + "/estado", timeout=1.5) as r:
                return json.loads(r.read())
        except Exception:
            time.sleep(0.3)
    raise RuntimeError("simulador no disponible")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--acelerar", type=float, default=40.0)
    ap.add_argument("--puerto", type=int, default=8081)
    ap.add_argument("--hasta-min", type=float, default=24.0)
    args = ap.parse_args()

    config.SALIDA_DIR.mkdir(parents=True, exist_ok=True)
    log = config.SALIDA_DIR / "registro_demo_reclamo.jsonl"
    cmd = [sys.executable, str(RAIZ / "simulador" / "servidor.py"),
           "--escenario", str(RAIZ / "datos" / "escenario_practica.json"),
           "--datos", str(RAIZ / "datos"), "--acelerar", str(args.acelerar),
           "--puerto", str(args.puerto), "--log", str(log)]
    sim = subprocess.Popen(cmd, cwd=str(RAIZ), stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, env=ENTORNO)
    try:
        esperar(f"http://127.0.0.1:{args.puerto}")
        cliente = SimClient(f"http://127.0.0.1:{args.puerto}")
        ledger = Ledger(config.SALIDA_DIR / "auditoria_demo_reclamo.jsonl")
        orch = ThemisOrchestrator(cliente, ledger, config.SALIDA_DIR / "expedientes_demo.json")
        hilo = threading.Thread(target=orch.run, kwargs={"hasta_min": args.hasta_min}, daemon=True)
        hilo.start()

        # Esperar a que exista el expediente del stream alojado en CDN compartida.
        exp = None
        inicio = time.time()
        while time.time() - inicio < 60:
            for e in list(orch.expedientes.values()):
                if "golazo" in (e["servidor"]["host_stream"] or ""):
                    exp = e
                    break
            if exp:
                break
            time.sleep(0.2)
        if not exp:
            raise RuntimeError("no se abrió el expediente de demostración")

        # Error operativo deliberado: bloqueo por IP sobre un hosting compartido.
        juez, juzgado = orch._juez_de_turno()
        orden = {
            "orden_id": "demo-error-ip-01",
            "expediente_id": exp["expediente_id"],
            "tipo": "ip",
            "objetivo": exp["servidor"]["ip"],
            "vence_min": int(orch.ctx.fin_min),
            "juzgado_id": juzgado["id"],
            "juez_id": juez["id"],
        }
        orden["firma"] = firmar(juez["clave_firma_demo"], mensaje_orden(orden))
        http, resp = cliente.post("/proveedores/aurora/ordenes", orden)
        print(f"[DEMO] orden IP deliberada sobre hosting compartido -> HTTP {http}", flush=True)
        if http in (200, 201, 202):
            orch.ordenes[("aurora", orden["orden_id"])] = Orden(
                orden_id=orden["orden_id"], orden_base=orden["orden_id"], proveedor="aurora",
                expediente_id=orden["expediente_id"], tipo="ip", objetivo=orden["objetivo"],
                vence_min=orden["vence_min"], juez_id=juez["id"], juzgado_id=juzgado["id"],
                firma=orden["firma"], host=exp["servidor"]["host_stream"],
                ip=exp["servidor"]["ip"], enviada_min=orch.minuto,
            )

        hilo.join(timeout=120)
        reporte = {
            "proyecto": "THEMIS-LIVE · demo de reclamo",
            "descripcion": "Se fuerza un bloqueo por IP sobre un hosting compartido; "
                           "el sitio legítimo reclama y THEMIS-LIVE levanta la orden con firma "
                           "judicial y la reemplaza por un bloqueo por dominio.",
            "expediente": exp["expediente_id"],
            "reclamos": orch.reclamos,
            "eventos_reclamo": [e for e in ledger.eventos
                                if e["evento"] in ("reclamo_resuelto", "orden_levantada",
                                                   "orden_emitida", "deteccion_descartada")],
            "integridad_ledger": ledger.verificar(),
        }
        (config.ENTREGA_DIR / "demo_reclamo.json").write_text(
            json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8")
        ledger.exportar(config.SALIDA_DIR / "auditoria_demo_reclamo.jsonl")
        print("\n[DEMO] reclamos:", json.dumps(orch.reclamos, ensure_ascii=False, indent=2), flush=True)
        print("[DEMO] reporte en entrega/demo_reclamo.json", flush=True)
        return 0
    finally:
        if sim.poll() is None:
            sim.terminate()
            try:
                sim.wait(timeout=5)
            except subprocess.TimeoutExpired:
                sim.kill()


if __name__ == "__main__":
    raise SystemExit(main())
