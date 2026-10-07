#!/usr/bin/env python3
"""Limpieza de coherencia del CSV principal (aditiva/normalizadora, nunca borra filas).

1. fecha  : dd.mm.yyyy / dd/mm/yyyy / d.m.yyyy / 'Saturday 26 September 2026' -> ISO;
            'weekend' y años fuera de 2025-2028 -> N/A (madarea para la cascada).
2. email  : URL copiada en la columna email -> se mueve a 'link' si link vacío,
            si no se vacía '' (madarea para la cascada). Solo se tocan valores
            que NO son emails válidos: nunca un email real.
3. continente/subcontinente : derivados desde país (mapa ES+EN) — rellena vacíos
            y corrige incoherencias (país = autoridad derivable).
4. subgenero : variantes ortográficas -> canónico ('psy trance'->'psytrance', etc.).

Escribe ATÓMICAMENTE vía core.csv_lock.csv_locked_rows + backup previo.
Uso: .venv/bin/python fix_coherencia.py [--dry-run]
"""
import csv
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.csv_lock import csv_locked_rows          # noqa: E402
from derivar_continente import PAIS_CONTINENTE     # noqa: E402

CSV = ROOT / "eventos_encontrados.csv"
DRY = "--dry-run" in sys.argv
VACIOS = {"", "N/A", "None", "nan", "NA", "NONE"}

MES = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
       "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
       "november": 11, "december": 12}
SUB_MAP = {"psy trance": "psytrance", "fullon": "full-on",
           "dark psy": "darkpsy", "goa trance": "goa"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
URL_RE = re.compile(r"^https?://", re.I)
RE_DOT = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")
RE_SLASH = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
RE_ISO = re.compile(r"^(\d{4})-\d{2}-\d{2}$")
RE_TXT = re.compile(r"^[A-Za-z]+ (\d{1,2}) ([A-Za-z]+) (\d{4})$")

# Valores detectados en 'pais' que son CIUDADES (extracción con ruido):
# no son países -> se preserva la ciudad en 'lugar' si está vacío y se limpia
# 'pais' (madada para el rellenado por gazetteer). Nunca se deriva continente
# de un valor de ciudad no verificable.
CITIES = {
    "Amsterdam", "Athens", "Barcelona", "Berlin", "Bologna", "Bordeaux",
    "Bristol", "Budapest", "Cape Town", "Casablanca", "Coimbra", "Copenhagen",
    "Düsseldorf", "Edinburgh", "Genoa", "Glasgow", "Helsingborg",
    "Johannesburg", "Leipzig", "Linköping", "Madrid", "Malmö", "Manchester",
    "Marseille", "Mexico City", "Milan", "Munich", "Málaga", "Naples",
    "Nantes", "Nairobi", "Nice", "Oslo", "Porto", "Prague", "Seoul",
    "Stuttgart", "Tel Aviv", "Tokyo", "Valencia", "Venice", "Vienna",
    "Zurich",
}

_MAP_CF = {k.casefold(): v for k, v in PAIS_CONTINENTE.items()}


def _iso(d: str, m: str, y: str) -> str:
    return f"{y}-{int(m):02d}-{int(d):02d}"


def fix_fecha(v: str) -> tuple[str, str]:
    s = (v or "").strip()
    if s in VACIOS:
        return s, ""
    m = RE_DOT.match(s) or RE_SLASH.match(s)
    if m:
        d, mo, y = m.groups()
        if int(y) <= 2028:
            return _iso(d, mo, y), "fecha->ISO"
        return "N/A", "fecha fuera de rango"
    m = RE_TXT.match(s)
    if m:
        d, mon, y = m.groups()
        mo = MES.get(mon.casefold())
        if mo and int(y) <= 2028:
            return f"{y}-{mo:02d}-{int(d):02d}", "fecha->ISO"
        return "N/A", "fecha fuera de rango"
    m = RE_ISO.match(s)
    if m:
        y = int(m.group(1))
        if not 2025 <= y <= 2028:
            return "N/A", "fecha fuera de rango"
        return s, ""
    if s.casefold() == "weekend":
        return "N/A", "fecha sin año"
    return "N/A", "fecha no interpretable"


def fix_email(row: dict) -> str:
    e = (row.get("email") or "").strip()
    if e in VACIOS or EMAIL_RE.match(e):
        return ""
    if URL_RE.match(e):
        lk = (row.get("link") or "").strip()
        if lk in VACIOS:
            row["link"] = e
            return "url->link"
        if lk.rstrip("/").casefold() == e.rstrip("/").casefold():
            return "url duplicada en link"
        return "url distinta (revisar)"
    return "email invalido"


def fix_geo(row: dict) -> str:
    pais = (row.get("pais") or "").strip()
    meta = _MAP_CF.get(pais.casefold())
    if not meta:
        return ""
    c, s = meta
    cont = (row.get("continente") or "").strip()
    sub = (row.get("subcontinente") or "").strip()
    if cont in VACIOS:
        row["continente"] = c
        row["subcontinente"] = s
        return "continente_vacio"
    if cont.casefold() != c.casefold():
        row["continente"] = c
        row["subcontinente"] = s
        return "continente_incoherente"
    if cont != c:
        row["continente"] = c
    if sub in VACIOS or sub in ("América", "Otro"):
        if sub.casefold() != s.casefold():
            row["subcontinente"] = s
            return "subcontinente_vacio"
    return ""


def main() -> None:
    if not CSV.exists():
        print("CSV no existe")
        sys.exit(1)

    stats: dict[str, int] = {}
    sin_mapa: set[str] = set()

    def bump(k: str) -> None:
        stats[k] = stats.get(k, 0) + 1

    with csv_locked_rows(CSV, timeout=300) as (rows, _fn):
        total = len(rows)
        # en dry-run se trabaja sobre copias: rows (y por tanto el fichero) intacto
        targets = [dict(r) for r in rows] if DRY else rows
        for r in targets:
            nv, act = fix_fecha(r.get("fecha", ""))
            if act:
                r["fecha"] = nv
                bump(act)
            act = fix_email(r)
            if act:
                r["email"] = ""
                bump(act)
            pais = (r.get("pais") or "").strip()
            if pais in CITIES:
                if (r.get("lugar") or "").strip() in VACIOS:
                    r["lugar"] = pais
                    bump("ciudad_pais->lugar")
                r["pais"] = ""
                bump("ciudad_pais_limpiada")
                pais = ""
            nk = fix_geo(r)
            if nk:
                bump(nk)
            elif pais and pais not in VACIOS and pais.casefold() not in _MAP_CF:
                sin_mapa.add(pais)
            sg = (r.get("subgenero") or "").strip().casefold()
            if sg in SUB_MAP:
                r["subgenero"] = SUB_MAP[sg]
                bump("subgenero_normalizado")
        if DRY:
            print("(dry-run: se descartan cambios)")

        bk = CSV.with_name(f"backup_coherencia_{int(time.time())}.csv")
        if not DRY:
            shutil.copy2(CSV, bk)
            print(f"Backup: {bk.name}")
        print(f"Filas: {total} (sin cambios en número)")
        for k in sorted(stats):
            print(f"  {k}: {stats[k]}")
        if sin_mapa:
            print("  países sin enlace en el mapa:", sorted(sin_mapa))

    # verificación post
    with open(CSV, encoding="utf-8") as f:
        rr = list(csv.DictReader(f))
    n = len(rr)

    def occ(col: str) -> tuple[int, float]:
        v = sum(1 for x in rr if (x.get(col) or "").strip() not in VACIOS)
        return v, 100.0 * v / n

    print("\n== Ocupación post ==")
    for col in ("organizador", "email", "fecha", "lugar", "pais", "continente",
                "subcontinente", "link", "subgenero", "tipo_lugar", "contactos"):
        v, p = occ(col)
        print(f"  {col:14} {v:5}/{n}  {p:5.1f}%")
    bad = [x["fecha"] for x in rr
           if (x["fecha"] or "").strip() not in VACIOS
           and not RE_ISO.match((x["fecha"] or "").strip())]
    oob = [x["fecha"] for x in rr
           if (x["fecha"] or "").strip() not in VACIOS
           and RE_ISO.match((x["fecha"] or "").strip())
           and not 2025 <= int(x["fecha"][:4]) <= 2028]
    print(f"fechas no-ISO: {len(bad)} | fechas fuera 2025-2028: {len(oob)}")
    bad_e = sum(1 for x in rr if (x["email"] or "").strip() not in VACIOS
                and not EMAIL_RE.match((x["email"] or "").strip()))
    print(f"emails invalidos: {bad_e}")


if __name__ == "__main__":
    main()
