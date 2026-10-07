#!/usr/bin/env python3
"""Ráfaga turbo (1-off): barrido SERP paralelo por ciudad para organizadores
y Rama A de emails para los top organizadores sin contacto. Reutiliza los
módulos de loop_completar; es aditivo y no toca el checkpoint del loop."""
import collections
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from core.csv_lock import csv_locked_rows
from loop_completar import (
    minar_organizadores_fb_serp,
    minar_email_organizador,
    _aplicar_email_organizador,
    _es_org_placeholder,
    es_org_slugderivado,
    es_email_valido,
    tipo_organizador,
    _normalizar_link_fb,
    log,
)

CSV = ROOT / "eventos_encontrados.csv"


def _creible(org):
    o = (org or "").strip()
    if not o or _es_org_placeholder(o) or es_org_slugderivado(o):
        return False
    if re.fullmatch(r"[\w\s.\-']+", o) is None or len(o.split()) < 2 or len(o) < 5:
        return False
    if re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b", o, re.I):
        return False
    return True


def serp_orgs(ciudades, filas_por_ciudad):
    def trabajo(c):
        try:
            mapa = minar_organizadores_fb_serp([c], anios=filas_por_ciudad[c].get("anios"),
                                               subgeneros=filas_por_ciudad[c].get("subs"),
                                               max_por_ciclo=1)
        except Exception as e:
            log(f"  ⚠️ SERP {c}: {str(e)[:60]}"); mapa = {}
        return c, mapa

    total_mapa = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(trabajo, c): c for c in ciudades}
        for fut in as_completed(futs):
            c, mapa = fut.result()
            total_mapa.update(mapa)
            log(f"  SERP {c}: {len(mapa)} soles")
    return total_mapa


def aplicar_org(mapa):
    _slug_org = {}
    for _u, _o in mapa.items():
        m = re.search(r"facebook\.com/events/([^/?#]+)", _u.lower())
        if m:
            _slug_org.setdefault(m.group(1), _o)
    ganado = mejorado = 0
    with csv_locked_rows(CSV, timeout=300) as (todas, _fn):
        for r in todas:
            if "Facebook" not in r.get("fuente", ""):
                continue
            org_act = (r.get("organizador", "") or "").strip()
            if org_act and org_act.lower() != "n/a" and not es_org_slugderivado(org_act):
                continue
            rl = _normalizar_link_fb(r.get("link", "") or "")
            org = mapa.get(rl)
            if not org:
                m = re.search(r"facebook\.com/events/([^/?#]+)", rl.lower())
                if m:
                    org = _slug_org.get(m.group(1))
            if org and org.lower() != org_act.lower():
                if org_act and org_act.lower() != "n/a":
                    mejorado += 1
                else:
                    ganado += 1
                r["organizador"] = org
                r["tipo_organizador"] = tipo_organizador(org)
    return ganado, mejorado


def rama_a(orgs):
    def trabajo(o):
        try:
            em = minar_email_organizador(o, "")
        except Exception:
            em = ""
        if not em:
            return o, 0
        g = _aplicar_email_organizador(o, em)
        return o, g

    gan = 0
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(trabajo, o): o for o in orgs}
        for fut in as_completed(futs):
            o, g = fut.result()
            if g:
                gan += g
                log(f"  EMAIL {o} -> +{g}")
    return gan


def main():
    filas = list(__import__("csv").DictReader(open(CSV, encoding="utf-8")))

    # 1) ciudades con más filas FB sin org
    missing_org = [r for r in filas
                   if "Facebook" in r.get("fuente", "")
                   and not (r.get("organizador") or "").strip()
                   or "Facebook" in r.get("fuente", "")
                   and _es_org_placeholder((r.get("organizador") or "").strip())]
    por_ciudad = collections.defaultdict(list)
    for r in missing_org:
        y = (r.get("fecha") or "")[:4]
        if y.isdigit() and y >= "2024":
            por_ciudad[(r.get("lugar") or "").strip()].append(r)
    top = [c for c, rs in sorted(por_ciudad.items(), key=lambda kv: -len(kv[1])) if c][:15]
    info = {}
    for c in top:
        info[c] = {
            "anios": [a for a, _ in collections.Counter(x.get("fecha", "")[:4] for x in por_ciudad[c]).most_common(2)],
            "subs": [sg for sg, _ in collections.Counter(x.get("subgenero", "") for x in por_ciudad[c]).most_common(4) if sg and sg.lower() != "n/a"],
        }
    log(f"[turbo] top {len(top)} ciudades (faltan org): {', '.join(top[:6])}...")
    t0 = time.time()
    mapa = serp_orgs(top, info)
    gan, mej = aplicar_org(mapa) if mapa else (0, 0)
    log(f"[turbo] SERP: {len(mapa)} soles -> {gan} nuevos + {mej} mejorados ({time.time()-t0:.0f}s)")

    # 2) Rama A: top organizadores credibles sin email
    cnt = collections.Counter((r.get("organizador") or "").strip()
                              for r in filas
                              if not es_email_valido((r.get("email") or "").strip())
                              and _creible((r.get("organizador") or "").strip()))
    orgs = [o for o, c in cnt.most_common() if c >= 2][:25]
    log(f"[turbo] Rama A sobre {len(orgs)} organizadores sin email")
    gan2 = rama_a(orgs)
    log(f"[turbo] Rama A: +{gan2} emails")


if __name__ == "__main__":
    main()