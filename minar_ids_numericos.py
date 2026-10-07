#!/usr/bin/env python3
"""Minería SERP por ID numérico de evento FB (page hosts de eventos reales).

Cubre los ~845 FB matriz cuyo link es facebook.com/events/<ID numérico>.
Dork: 'facebook.com/events/<ID> event' — el snippet típicamente no trae
organizador (FB no indexa "hosted by"), pero a veces sí "Event by X on".
Primero probamos la URL directa (redirect a página pública). dry-run por defecto.
"""
import argparse
import csv
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from loop_completar import _normalizar_link_fb, _limpiar_org_fb, ddg_search, tipo_organizador
from loop_completar import _FB_SNIPPET_PAT, _FB_SNIPPET_PAT2
from core.csv_lock import csv_locked_rows

CSV_FILE = Path(__file__).parent / 'eventos_encontrados.csv'

def sluglink(r):
    m = re.search(r'facebook\.com/events/([^/?#]+)', (r.get('link') or '').lower())
    return m.group(1) if m else ''

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--max', type=int, default=200, help='máx IDs a intentar')
    ap.add_argument('--limpar', action='store_true', help='limpiar cache entre exec')
    args = ap.parse_args()

    with csv_locked_rows(CSV_FILE) as (todas, _):
        sin = [r for r in todas if 'Facebook' in r.get('fuente','')
               and (r.get('organizador') or '').strip() in ('', 'N/A')
               and sluglink(r).isdigit()]

    ids_unicos = {}
    for r in sin:
        sid = sluglink(r)
        ids_unicos.setdefault(sid, []).append(r)

    total = len(ids_unicos)
    print(f"IDs numéricos sin org: {total} (procesando {min(args.max, total)})")

    resultados = {}  # sid -> org
    for i, sid in enumerate(list(ids_unicos)[:args.max]):
        dorks = [
            f'facebook.com/events/{sid} event',
        ]
        org = ''
        for d in dorks:
            try:
                res = ddg_search(d, timeout=22)
            except Exception:
                continue
            for r in res.get('results', []):
                u = _normalizar_link_fb(r.get('url','') or '')
                if f'/events/{sid}' not in u:
                    continue
                sn = (r.get('snippet','') or '')
                m = _FB_SNIPPET_PAT.search(sn) or _FB_SNIPPET_PAT2.search(sn)
                if m:
                    org = _limpiar_org_fb(m.group('org'))
                if org:
                    break
            if org:
                break
            time.sleep(0.6)
        if org:
            resultados[sid] = org
        if (i+1) % 25 == 0:
            print(f"  ...{i+1}/{min(args.max,total)} | resueltos {len(resultados)}")

    print(f"Resueltos: {len(resultados)}/{min(args.max,total)} IDs")

    if args.apply and resultados:
        gan = 0
        ids_ok = set(resultados)
        with csv_locked_rows(CSV_FILE) as (todas, _):
            for r in todas:
                if 'Facebook' not in r.get('fuente',''): continue
                if (r.get('organizador') or '').strip() not in ('','N/A'): continue
                sid = sluglink(r)
                if sid in ids_ok:
                    r['organizador'] = resultados[sid]
                    r['tipo_organizador'] = tipo_organizador(resultados[sid])
                    gan += 1
        print(f"✅ Aplicados: {gan}")
    else:
        print("DRY-RUN — usa --apply para escribir")
        for sid, org in list(resultados.items())[:10]:
            print(f"  {sid} -> {org}")

if __name__ == '__main__':
    main()