#!/usr/bin/env python3
"""Propaga organizador por PÁGINA de Facebook: filas sin org cuya página
creadora ya tiene org en otra fila (misma clave de URL).

Claves soportadas:
  facebook.com/events/<slug>/<id>     -> slug (página creadora del evento)
  facebook.com/<pagina>/events/<id>   -> <pagina>

Nunca sobrescribe; solo llena '' / 'N/A'. Dry-run por defecto, --apply escribe.
"""
import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT = Path(__file__).parent
sys.path.insert(0, str(PROJECT))
from core.csv_lock import csv_locked_rows
from loop_completar import _es_org_placeholder

CSV_FILE = PROJECT / 'eventos_encontrados.csv'

PAT_EVENTS_SLUG = re.compile(r'facebook\.com/events/([a-zA-Z0-9.\-_]{3,})/\d{5,}', re.I)
PAT_PAGE_EVENTS = re.compile(r'facebook\.com/([a-zA-Z0-9.\-_]{3,})/events/\d{5,}', re.I)


def clave_pagina(link: str):
    u = (link or '').lower()
    if 'facebook.com' not in u:
        return None
    m = PAT_EVENTS_SLUG.search(u)
    if m and not m.group(1).isdigit():
        return m.group(1)
    m = PAT_PAGE_EVENTS.search(u)
    if m and m.group(1) not in ('events', 'watch', 'groups', 'pages'):
        return m.group(1)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='escribir cambios')
    args = ap.parse_args()

    with csv_locked_rows(CSV_FILE, timeout=300) as (rows, _):
        votos = defaultdict(Counter)
        for r in rows:
            org = (r.get('organizador') or '').strip()
            if not org or _es_org_placeholder(org):
                continue
            k = clave_pagina(r.get('link'))
            if k:
                votos[k][org] += 1
        mejor = {k: c.most_common(1)[0][0] for k, c in votos.items()}

        aplic = []
        for r in rows:
            org = (r.get('organizador') or '').strip()
            if org and not _es_org_placeholder(org):
                continue
            k = clave_pagina(r.get('link'))
            if k and k in mejor:
                aplic.append((r, mejor[k]))

        print(f"Páginas con org conocido: {len(mejor)} | filas aplicables: {len(aplic)}")
        for r, nuevo in aplic[:8]:
            print(f"  {(r.get('nombre') or '')[:40]:40} -> {nuevo}")

        if not args.apply:
            print('(dry-run — --apply para escribir)')
            return

        n = 0
        for r, nuevo in aplic:
            r['organizador'] = nuevo
            n += 1
        print(f'✅ Aplicados: {n} organizadores por página')


if __name__ == '__main__':
    main()
