#!/usr/bin/env python3
"""Genera PROPUESTAS de organizador (y email) para filas sin organizador del
catálogo minable. NO escribe en el CSV: produce `propuestas_org.jsonl` para
revisión humana.

Combina evidencia SERP real (`buscar_org_para_evento`) con un LLM opcional
(`core.mcp_clasificar._llm_generate`) que solo extrae el organizador si la
evidencia lo nombra. Cada propuesta lleva su `fuente_url` y `confianza`.
"""
import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from loop_completar import (
    es_nombre_gen_org, buscar_org_para_evento, minar_email_organizador,
    es_email_valido, _es_org_placeholder, es_org_slugderivado,
)
from serp_worker import search as ddg_search

try:
    from core.mcp_clasificar import _llm_generate
except Exception:
    _llm_generate = None

ROOT = Path(__file__).resolve().parent
CSV = ROOT / "eventos_encontrados.csv"
OUT = ROOT / "propuestas_org.jsonl"

SYS = ("Eres un extractor de datos de eventos musicales (psytrance). Dado un "
       "evento y resultados de búsqueda reales, devuelve SOLO JSON con el "
       "organizador/promotor si la EVIDENCIA lo nombra claramente. No inventes. "
       'Si no aparece, usa organizador="".')


def _vacio(c):
    return (c or "").strip() in ("", "N/A")


def _es_fb(r):
    return (r.get("fuente") or "").lower().startswith("facebook")


def _clave(r):
    return f"{(r.get('nombre') or '').strip().lower()}|{(r.get('lugar') or '').strip().lower()}"


def _org_ok(org):
    if not org or not (3 <= len(org) <= 45) or len(org.split()) > 4:
        return False
    try:
        if _es_org_placeholder(org) or es_org_slugderivado(org):
            return False
    except Exception:
        pass
    return True


def _evidencia(nombre, lugar):
    q = f'"{nombre[:70]}" {lugar} psytrance'.strip()
    try:
        res = ddg_search(q, timeout=20)
    except Exception:
        return []
    out = []
    for r in (res.get("results") or [])[:5]:
        out.append({
            "titulo": (r.get("titulo") or "")[:120],
            "url": (r.get("url") or "")[:180],
            "snippet": (r.get("snippet") or "")[:200],
        })
    return out


def _llm_prop(nombre, lugar, fecha, ev):
    if not _llm_generate or not ev:
        return None
    bloque = "\n".join(f"- {e['titulo']} | {e['url']} | {e['snippet']}" for e in ev)
    prompt = (f"Evento: {nombre}\nCiudad: {lugar}\nFecha: {fecha}\n"
              f"Resultados de búsqueda reales:\n{bloque}\n\n"
              'Devuelve SOLO JSON: {"organizador":"","fuente_url":"",'
              '"confianza":"alta|media|baja","motivo":""}')
    try:
        txt = _llm_generate(prompt, system=SYS, temperature=0.05) or ""
    except Exception:
        return None
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _proponer(r, usar_llm=True):
    nombre = r.get("nombre") or ""
    lugar = r.get("lugar") or ""
    fecha = r.get("fecha") or ""
    ev = _evidencia(nombre, lugar)
    llm = _llm_prop(nombre, lugar, fecha, ev) if usar_llm else None

    org, fuente, conf, metodo = "", "", "", ""
    if llm and _org_ok(llm.get("organizador") or ""):
        org = (llm.get("organizador") or "").strip()
        fuente = (llm.get("fuente_url") or "").strip()
        conf = (llm.get("confianza") or "media").lower()
        metodo = "llm"
    if not org:
        try:
            s = buscar_org_para_evento(r)
        except Exception:
            s = ""
        if _org_ok(s):
            org, conf, metodo = s, "media", "serp"
    if not _org_ok(org):
        return None

    email = ""
    if org and _vacio(r.get("email")):
        try:
            email = minar_email_organizador(org, lugar)
            if email and not es_email_valido(email):
                email = ""
        except Exception:
            email = ""

    prop = {
        "clave": _clave(r),
        "link": r.get("link") or "",
        "nombre": nombre,
        "lugar": lugar,
        "fecha": fecha,
        "organizador": org,
        "email": email,
        "fuente_url": fuente or next((e["url"] for e in ev), ""),
        "confianza": conf if conf in ("alta", "media", "baja") else "media",
        "metodo": metodo,
    }
    return prop


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, default=40, help="máx. filas a procesar")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--sin-llm", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    import csv
    rows = list(csv.DictReader(open(CSV, encoding="utf-8")))
    resid = {id(r) for r in rows
             if _es_fb(r) and es_nombre_gen_org(r.get("nombre") or "")}
    sin = [r for r in rows if id(r) not in resid and _vacio(r.get("organizador"))]

    visto, pend = set(), []
    for r in sin:
        k = _clave(r)
        if k and k not in visto:
            visto.add(k)
            pend.append(r)
    pend = pend[:args.limite]
    print(f"minables sin org: {len(sin)} | únicas: {len(visto)} | procesando: {len(pend)} "
          f"| LLM={'no' if args.sin_llm else 'sí'}")

    props = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for p in pool.map(lambda r: _proponer(r, not args.sin_llm), pend):
            if p:
                props.append(p)
                print(f"  + {p['nombre'][:42]:42s} → {p['organizador'][:30]:30s} "
                      f"[{p['confianza']}/{p['metodo']}]")

    with open(args.out, "w", encoding="utf-8") as f:
        for p in props:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"\npropuestas útiles: {len(props)}/{len(pend)} → {args.out}")


if __name__ == "__main__":
    main()
