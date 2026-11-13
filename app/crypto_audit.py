"""THEMIS-LIVE · Núcleo de integridad: firmas judiciales HMAC y ledger encadenado."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def firmar(clave: str, mensaje: str) -> str:
    """Firma HMAC-SHA256 en hexadecimal, idéntica a la que valida el simulador."""
    return hmac.new(clave.encode("utf-8"), mensaje.encode("utf-8"), hashlib.sha256).hexdigest()


def mensaje_orden(orden: Dict[str, Any]) -> str:
    return "|".join(
        str(orden[k]) for k in ("orden_id", "tipo", "objetivo", "vence_min", "juez_id")
    )


def mensaje_levantamiento(orden_id: str, juez_id: str) -> str:
    return f"LEVANTAR|{orden_id}|{juez_id}"


def sha256_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def hash_captura(captura: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Huella forense de la captura: hash del binario y del contenedor base64."""
    if not captura:
        return {"sha256_b64": "", "sha256_binario": "", "bytes": "0"}
    b64 = str(captura.get("contenido_b64", ""))
    try:
        import base64

        crudo = base64.b64decode(b64, validate=False)
    except Exception:
        crudo = b""
    return {
        "sha256_b64": sha256_texto(b64),
        "sha256_binario": hashlib.sha256(crudo).hexdigest(),
        "bytes": str(len(crudo)),
    }


class Ledger:
    """Registro de auditoría inalterable: cada evento encadena el hash del anterior."""

    GENESIS = "0" * 64

    def __init__(self, ruta: Path, reanudar: bool = False) -> None:
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._prev = self.GENESIS
        self._seq = 0
        self._eventos = []
        if reanudar and self.ruta.exists() and self.ruta.stat().st_size > 0:
            for linea in self.ruta.read_text(encoding="utf-8").splitlines():
                if not linea.strip():
                    continue
                e = json.loads(linea)
                self._eventos.append(e)
                self._seq = int(e.get("seq", self._seq + 1))
                self._prev = e.get("hash", self._prev)
        else:
            self.ruta.write_text("", encoding="utf-8")

    @property
    def ultimo_hash(self) -> str:
        return self._prev

    @property
    def eventos(self) -> list:
        return list(self._eventos)

    def registrar(self, evento: str, minuto: float, **datos: Any) -> Dict[str, Any]:
        with self._lock:
            self._seq += 1
            cuerpo = {
                "seq": self._seq,
                "timestamp_iso": datetime.now(timezone.utc).isoformat(),
                "minuto_partido": round(float(minuto), 3),
                "evento": evento,
                "operador": "THEMIS-LIVE",
                "datos": datos,
                "prev_hash": self._prev,
            }
            crudo = json.dumps(cuerpo, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            cuerpo["hash"] = sha256_texto(crudo)
            self._prev = cuerpo["hash"]
            linea = json.dumps(cuerpo, ensure_ascii=False)
            with self.ruta.open("a", encoding="utf-8") as f:
                f.write(linea + "\n")
            self._eventos.append(cuerpo)
            return cuerpo

    def verificar(self) -> Dict[str, Any]:
        """Recalcula la cadena completa y devuelve el resultado de integridad."""
        prev = self.GENESIS
        total = 0
        for ev in self._eventos:
            total += 1
            cuerpo = {k: v for k, v in ev.items() if k != "hash"}
            if cuerpo.get("prev_hash") != prev:
                return {"integro": False, "eventos": total, "roto_en": ev.get("seq")}
            crudo = json.dumps(cuerpo, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if sha256_texto(crudo) != ev.get("hash"):
                return {"integro": False, "eventos": total, "roto_en": ev.get("seq")}
            prev = ev["hash"]
        return {"integro": True, "eventos": total, "ultimo_hash": prev}

    def exportar(self, destino: Path) -> Path:
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in self._eventos) + "\n",
            encoding="utf-8",
        )
        return destino
