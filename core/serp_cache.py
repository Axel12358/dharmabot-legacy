#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cache SQLite local de respuestas SERP (por motor|query).

Palanca 3 del asesor: entre rounds/semillas se repiten dorks; reutilizar
respuestas dentro de un TTL evita peticiones redundantes y baja la presión
sobre Google (el motor que se suspende con más facilidad).

Concurrencia: SQLite en WAL; varias instancias escriben y leen sin pisarse.
La DB vive en estado_runtime/ (gitignored).
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from typing import Dict, List, Optional

_TTL_SEG = 48 * 3600  # 48h
_LOCK = threading.Lock()

_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "estado_runtime", "cache_serp.sqlite3",
)


def _db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    con = sqlite3.connect(_DB_PATH, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            clave TEXT PRIMARY KEY,
            ts INTEGER NOT NULL,
            datos TEXT NOT NULL
        )
    """)
    return con


def clave(motor: str, query: str) -> str:
    h = hashlib.sha1(f"{motor}|{query}".encode("utf-8", "ignore")).hexdigest()
    return f"{motor}|{h}"


def cache_get(motor: str, query: str) -> Optional[List[Dict[str, str]]]:
    """Devuelve resultados cacheados si están dentro del TTL."""
    ck = clave(motor, query)
    try:
        con = _db()
        try:
            row = con.execute(
                "SELECT ts, datos FROM cache WHERE clave=?", (ck,)
            ).fetchone()
        finally:
            con.close()
        if not row:
            return None
        ts, datos = row
        if time_now() - ts > _TTL_SEG:
            return None
        return json.loads(datos)
    except Exception:
        return None


def cache_set(motor: str, query: str, resultados: List[Dict[str, str]]) -> None:
    if not resultados:
        return
    ck = clave(motor, query)
    try:
        con = _db()
        try:
            con.execute(
                "INSERT OR REPLACE INTO cache (clave, ts, datos) VALUES (?,?,?)",
                (ck, time_now(), json.dumps(resultados, ensure_ascii=False)),
            )
            con.commit()
        finally:
            con.close()
    except Exception:
        pass


def cache_purge_expired() -> int:
    """Limpia entradas viejas (mantiene la DB chica)."""
    try:
        con = _db()
        try:
            cur = con.execute(
                "DELETE FROM cache WHERE ? - ts > ?", (time_now(), _TTL_SEG)
            )
            con.commit()
            return cur.rowcount
        finally:
            con.close()
    except Exception:
        return 0


def _time_now() -> int:
    import time
    return int(time.time())


time_now = _time_now