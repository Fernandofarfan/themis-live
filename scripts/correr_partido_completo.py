"""THEMIS-LIVE · Corrida completa y verificable de punta a punta.

Uso:
    python scripts/correr_partido_completo.py --acelerar 60
    python scripts/correr_partido_completo.py --acelerar 120 --sin-dashboard
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

ENTORNO = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

from app import config  # noqa: E402
from app.crypto_audit import Ledger  # noqa: E402
from app.orchestrator import SimClient, ThemisOrchestrator  # noqa: E402
from app.dashboard_server import Dashboard  # noqa: E402


def esperar_simulador(url: str, timeout: float = 40.0) -> dict:
    inicio = time.time()
    while time.time() - inicio < timeout:
        try:
            with urllib.request.urlopen(url + "/estado", timeout=1.5) as resp:
                return json.loads(resp.read())
        except Exception:
            time.sleep(0.3)
    raise RuntimeError("El simulador no respondió a tiempo")


def main() -> int:
    ap = argparse.ArgumentParser(description="THEMIS-LIVE · partido completo contra el simulador oficial")
    ap.add_argument("--url", type=str, default="",
                    help="URL de un simulador externo ya levantado (ej. el del jurado el viernes 13)")
    ap.add_argument("--acelerar", type=float, default=60.0,
                    help="minutos simulados por minuto real (60 = partido en ~2 min)")
    ap.add_argument("--puerto", type=int, default=8080)
    ap.add_argument("--dashboard", type=int, default=8090)
    ap.add_argument("--sin-dashboard", action="store_true")
    ap.add_argument("--timeout-real", type=float, default=1200.0)
    args = ap.parse_args()

    config.SALIDA_DIR.mkdir(parents=True, exist_ok=True)
    config.ENTREGA_DIR.mkdir(parents=True, exist_ok=True)
    log_sim = config.SALIDA_DIR / "registro.jsonl"
    url_sim = args.url.rstrip("/") if args.url else f"http://127.0.0.1:{args.puerto}"

    sim = None
    if not args.url:
        if log_sim.exists():
            log_sim.unlink()
        cmd = [
            sys.executable, str(RAIZ / "simulador" / "servidor.py"),
            "--escenario", str(RAIZ / "datos" / "escenario_practica.json"),
            "--datos", str(RAIZ / "datos"),
            "--acelerar", str(args.acelerar),
            "--puerto", str(args.puerto),
            "--log", str(log_sim),
        ]
        print("[THEMIS] iniciando simulador oficial:", " ".join(cmd), flush=True)
        sim = subprocess.Popen(cmd, cwd=str(RAIZ), stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                               errors="replace", env=ENTORNO)
    else:
        print(f"[THEMIS] conectando a simulador externo: {url_sim}", flush=True)
    dashboard = None
    try:
        estado = esperar_simulador(url_sim)
        print(f"[THEMIS] simulador listo · fin_min={estado['fin_min']} · jueces={estado['jueces_de_turno']}", flush=True)

        ledger = Ledger(config.SALIDA_DIR / "auditoria_themis.jsonl")
        cliente = SimClient(url_sim)
        orch = ThemisOrchestrator(cliente, ledger, config.SALIDA_DIR / "expedientes.json")
        if not args.sin_dashboard:
            dashboard = Dashboard(orch, args.dashboard).start()

        limite = float(orch.ctx.fin_min) + config.MARGEN_GRACIA_MIN + 0.5
        print(f"[THEMIS] operando hasta el minuto {limite:.1f} (aceleracion x{args.acelerar:g})", flush=True)
        orch.run(hasta_min=limite, timeout_real=args.timeout_real)

        # Dejar que el simulador escriba el cierre de ventana (minuto 110).
        time.sleep(0.6)
        orch.minuto = float((cliente.get("/estado") or {}).get("minuto_actual", limite))
        orch.finalizado = True
        orch.exportar()
        print("[THEMIS] exportando entregables...", flush=True)

        datos = json.loads((config.SALIDA_DIR / "expedientes.json").read_text(encoding="utf-8"))
        primer = datos["expedientes"][0] if datos["expedientes"] else {}
        (config.ENTREGA_DIR / "expediente_ejemplo.json").write_text(
            json.dumps(primer, ensure_ascii=False, indent=2), encoding="utf-8")
        ledger.exportar(config.ENTREGA_DIR / "registro_auditoria.jsonl")

        resultado = {}
        if not args.url and log_sim.exists():
            verificacion = subprocess.run(
                [sys.executable, str(RAIZ / "evaluacion" / "verificar.py"),
                 "--log", str(log_sim), "--json"],
                cwd=str(RAIZ), capture_output=True, text=True, encoding="utf-8",
                errors="replace", env=ENTORNO)
            salida_json = (verificacion.stdout or "").strip()
            try:
                resultado = json.loads(salida_json)
            except Exception:
                resultado = {"error": "no se pudo parsear verificar.py", "crudo": salida_json,
                             "stderr": verificacion.stderr}
            (config.ENTREGA_DIR / "resultado_verificacion.json").write_text(
                json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")

            legible = subprocess.run(
                [sys.executable, str(RAIZ / "evaluacion" / "verificar.py"), "--log", str(log_sim)],
                cwd=str(RAIZ), capture_output=True, text=True, encoding="utf-8",
                errors="replace", env=ENTORNO)
            print("\n" + "=" * 78)
            print("VERIFICACION OFICIAL (evaluacion/verificar.py)")
            print("=" * 78)
            print(legible.stdout or legible.stderr)

        resumen = {
            "proyecto": "THEMIS-LIVE",
            "partido": datos.get("partido"),
            "resumen_motor": datos.get("resumen"),
            "metricas_juez": resultado.get("resumen"),
            "fases": resultado.get("fases"),
            "dano_colateral": resultado.get("dano_colateral"),
            "falsos_positivos": resultado.get("falsos_positivos"),
            "post_partido": resultado.get("post_partido"),
            "reclamos": resultado.get("reclamos"),
        }
        (config.ENTREGA_DIR / "resumen_corrida.json").write_text(
            json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[THEMIS] entregables en:", config.ENTREGA_DIR, flush=True)
        return 0
    finally:
        if dashboard:
            dashboard.stop()
        if sim is not None:
            if sim.poll() is None:
                sim.terminate()
                try:
                    sim.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    sim.kill()
            try:
                salida = sim.stdout.read() if sim.stdout else ""
                if salida and "Traceback" in salida:
                    print(salida, flush=True)
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
