#!/usr/bin/env python3
"""Aplica el catálogo-origen a filas con organizador/email vacíos.

Reglas (regla de oro del proyecto: nunca sobrescribir):
  - organizador: SOLO si está vacío/N/A  → match exacto venue(place) en mapa_venue_host.json
  - email:       SOLO si está vacío/N/A  → match exacto organizador en catalogo_org_email.json
  - tras asignar org por venue, se intenta email del mismo catálogo (misma fila).
  - Se revalidan org/email contra filtros de placeholder/basura antes de escribir.

DRY-RUN por defecto (solo cuenta y muestra). --apply escribe bajo lock.
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CSV_FILE = ROOT / "eventos_encontrados.csv"
OUT_CAT = ROOT / "catalogo_org_email.json"
OUT_VEN = ROOT / "mapa_venue_host.json"

_EMAIL_PLACEHOLDER = re.compile(
    r"company\.com|venue\.com|guest@|back-in-stock@|@placehold|@example|"
    r"\.domain\.cz|@domain\.|^email@|^info@$|^contact@$|n/?a|^[^@]+$", re.I)
_ORG_BASURA = re.compile(r"^\W*$|^\d+$|\b(n/a|na|tba|loading|facebook|instagram)\b", re.I)


def _vacio(v):
    return not v or (v or "").strip() in ("", "N/A", "n/a")


def _org_valido(o):
    o = (o or "").strip()
    return bool(o) and len(o) >= 3 and not _ORG_BASURA.search(o)


def _email_valido(e):
    e = (e or "").strip()
    return bool(e) and "@" in e and not _EMAIL_PLACEHOLDER.search(e)


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower()).strip(" .,;:!?")


def aplicar(escribir=False):
    """Re-aplica catálogo-origen y devuelve dict de conteos (no imprime)."""
    if not (OUT_CAT.exists() and OUT_VEN.exists()):
        return {"org": 0, "email": 0, "org_email": 0, "muestras": [],
                "error": "sin catálogo"}
    catalogo = json.loads(OUT_CAT.read_text(encoding="utf-8"))
    mapa = json.loads(OUT_VEN.read_text(encoding="utf-8"))

    from core.csv_lock import csv_locked_rows

    with csv_locked_rows(CSV_FILE, timeout=300) as (rows, fieldnames):
        trabajadas = list(rows) if escribir else [dict(r) for r in rows]
        gan_org = gan_email = gan_org_email = 0
        muestras = []
        for r in trabajadas:
            modo = None
            if _vacio(r.get("organizador") or ""):
                ven = _norm(r.get("lugar") or "")
                hit = mapa.get(ven)
                if hit and _org_valido(hit["org"]):
                    r["organizador"] = hit["org"]
                    modo = "venue"
                    gan_org += 1
            if _vacio(r.get("email") or "") and _org_valido(r.get("organizador") or ""):
                c = catalogo.get(_norm(r.get("organizador") or ""))
                if c and _email_valido(c["email"]):
                    r["email"] = c["email"]
                    if modo == "venue":
                        gan_org_email += 1
                    else:
                        gan_email += 1
            if not escribir and modo:
                muestras.append((modo, (r.get("nombre") or "")[:50],
                                 (r.get("lugar") or "")[:30], r.get("organizador")))
        if escribir:
            rows[:] = trabajadas
        return {"org": gan_org, "email": gan_email + gan_org_email,
                "org_email": gan_org_email, "muestras": muestras[:12]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="escribe bajo lock (por defecto: solo cuenta)")
    args = ap.parse_args()

    if not (OUT_CAT.exists() and OUT_VEN.exists()):
        print("Faltan catálogo/mapa — primero: python construir_catalogo_org_email.py")
        return 2
    res = aplicar(args.apply)
    print(f"DRY-RUN{' (apply)' if args.apply else ''}")
    print(f"  organizador por venue:  {res['org']}")
    print(f"  email por organizador:  {res['email']} (+{res['org_email']} en ven-org)")
    if not args.apply and res["muestras"]:
        print("  ejemplos:")
        for m in res["muestras"]:
            print("    -", m)
    return 0


if __name__ == "__main__":
    sys.exit(main())


if __name__ == "__main__":
    sys.exit(main())