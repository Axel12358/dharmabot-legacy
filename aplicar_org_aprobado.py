#!/usr/bin/env python3
"""Aplica SOLO las propuestas APROBADAS (`decisiones_org.json`) al CSV.

Guardarraíles: bajo `csv_locked_rows`, rellena únicamente campos vacíos
(organizador y/o email); nunca sobrescribe; escribe `aplicado=1` en las
decisiones para no reaplicar. Dry-run por defecto.
"""
import argparse
import json
from pathlib import Path

from core.csv_lock import csv_locked_rows

ROOT = Path(__file__).resolve().parent
CSV = ROOT / "eventos_encontrados.csv"
PROPS = ROOT / "propuestas_org.jsonl"
DEC = ROOT / "decisiones_org.json"


def _vacio(c):
    return (c or "").strip() in ("", "N/A")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    props = [json.loads(l) for l in PROPS.read_text(encoding="utf-8").splitlines() if l.strip()]
    dec = json.loads(DEC.read_text(encoding="utf-8")) if DEC.exists() else {}

    aprobadas = [props[int(i)] for i, v in dec.items()
                 if v == "aprobado" and not dec.get(f"aplicado:{i}")]
    if not aprobadas:
        print("Nada aprobado pendiente de aplicar.")
        return

    por_clave = {p["clave"]: p for p in aprobadas}
    g_org = g_email = 0
    detalle = []
    with csv_locked_rows(CSV, timeout=300) as (rows, _fn):
        trabajadas = list(rows) if args.apply else [dict(r) for r in rows]
        for r in trabajadas:
            k = f"{(r.get('nombre') or '').strip().lower()}|{(r.get('lugar') or '').strip().lower()}"
            p = por_clave.get(k)
            if not p:
                continue
            if _vacio(r.get("organizador")) and p.get("organizador"):
                r["organizador"] = p["organizador"]
                g_org += 1
            if _vacio(r.get("email")) and p.get("email"):
                r["email"] = p["email"]
                g_email += 1
            detalle.append((p["nombre"][:40], p.get("organizador", ""), p.get("confianza", "")))
        if args.apply:
            rows[:] = trabajadas
            for i, v in dec.items():
                if v == "aprobado":
                    dec[f"aplicado:{i}"] = True
            DEC.write_text(json.dumps(dec, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"{'APLICADO' if args.apply else 'DRY-RUN'} | organizador +{g_org} | email +{g_email}")
    for d in detalle[:15]:
        print("  -", d)


if __name__ == "__main__":
    main()
