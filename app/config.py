"""THEMIS-LIVE · Configuración central del sistema."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Rutas del desafío oficial (copiadas del repo qualydata-org/desafio-futbol) ---
DATOS_DIR = Path(os.environ.get("THEMIS_DATOS", BASE_DIR / "datos"))
SALIDA_DIR = Path(os.environ.get("THEMIS_SALIDA", BASE_DIR / "salida"))
ENTREGA_DIR = Path(os.environ.get("THEMIS_ENTREGA", BASE_DIR / "entrega"))

ESCENARIO = DATOS_DIR / "escenario_practica.json"
PROVEEDORES = DATOS_DIR / "proveedores.json"
JUZGADOS = DATOS_DIR / "juzgados.json"
VERDAD = BASE_DIR / "evaluacion" / "verdad_practica.json"

# --- Conexión con el simulador ---
SIMULADOR_URL = os.environ.get("THEMIS_SIMULADOR", "http://127.0.0.1:8080")

# --- Comportamiento del motor ---
POLL_SEGUNDOS = float(os.environ.get("THEMIS_POLL", "0.2"))
MARGEN_GRACIA_MIN = 5.0
MAX_REINTENTOS_ISP = 8
VENTANA_REINTENTO_MIN = 0.35

# --- Sesión ---
OPERADOR = "THEMIS-LIVE · Unidad de Ciberdelitos Complejos"
