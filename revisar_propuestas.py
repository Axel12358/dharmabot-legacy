#!/usr/bin/env python3
"""Revisión humana de `propuestas_org.jsonl` → `decisiones_org.json`.

Interactivo (por lotes): a=aprobar, r=rechazar, s=saltar, q=guardar y salir.
No interactivo:
  --listar N        muestra las primeras N propuestas
  --aprobar-alta    aprueba en bloque todas las de confianza alta (no decididas)
Reanudable: nunca re-pregunta lo ya decidido.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROPS = ROOT / "propuestas_org.jsonl"
DEC = ROOT / "decisiones_org.json"


def _cargar():
    props = []
    if PROPS.exists():
        for ln in PROPS.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                props.append(json.loads(ln))
    dec = {}
    if DEC.exists():
        dec = json.loads(DEC.read_text(encoding="utf-8"))
    return props, dec


def _guardar(dec):
    DEC.write_text(json.dumps(dec, ensure_ascii=False, indent=1), encoding="utf-8")


def _fila(p):
    return (f"{p['nombre'][:44]:44s} | {p['lugar'][:16]:16s} | "
            f"{p['organizador'][:30]:30s} | {p['confianza']:5s} | {p.get('fuente_url','')[:40]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listar", type=int, default=0)
    ap.add_argument("--aprobar-alta", action="store_true")
    ap.add_argument("--lote", type=int, default=20)
    args = ap.parse_args()
    props, dec = _cargar()
    if not props:
        print("Sin propuestas. Corre primero: python llm_atribuir_org.py")
        return

    if args.listar:
        print(f"total: {len(props)} | mostrando {args.listar}")
        for p in props[:args.listar]:
            print(" ", _fila(p))
        return

    if args.aprobar_alta:
        n = 0
        for i, p in enumerate(props):
            if dec.get(str(i)):
                continue
            if p["confianza"] == "alta":
                dec[str(i)] = "aprobado"
                n += 1
        _guardar(dec)
        print(f"aprobadas en bloque (alta): {n}. Total decididas: {len(dec)}/{len(props)}")
        return

    pend = [i for i in range(len(props)) if str(i) not in dec]
    print(f"total {len(props)} | pendientes {len(pend)} | lote {args.lote}")
    for j in range(0, len(pend), args.lote):
        lote = pend[j:j + args.lote]
        for i in lote:
            p = props[i]
            print(f"\n[{i}] {p['nombre']}\n    ciudad: {p['lugar']}  fecha: {p['fecha']}"
                  f"\n    org propuesto: {p['organizador']}  email: {p.get('email','') or '—'}"
                  f"\n    fuente: {p.get('fuente_url','') or '—'}  confianza: {p['confianza']}")
        for i in lote:
            while True:
                k = input(f"[{i}] a/r/s/q > ").strip().lower()
                if k in ("a", "r", "s", "q"):
                    break
            if k == "q":
                _guardar(dec)
                print(f"guardado. decididas {len(dec)}/{len(props)}")
                return
            if k == "a":
                dec[str(i)] = "aprobado"
            elif k == "r":
                dec[str(i)] = "rechazado"
            else:
                dec[str(i)] = "saltado"
        _guardar(dec)
        print(f"lote guardado. decididas {len(dec)}/{len(props)}")
    _guardar(dec)
    print("revisión completa.")


if __name__ == "__main__":
    main()
