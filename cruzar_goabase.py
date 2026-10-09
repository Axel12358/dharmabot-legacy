#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cruza eventos de goabase (parties JSON) con nuestro CSV sin email.

Para cada fila sin email, busca por nombre la party de goabase equivalente
(corresponde al mismo evento físico) y, si hay match seguro:
  - rellena organizador REAL (solo si está vacío)
  - rellena email del organizador (solo si vacío) si lo tenemos minado
  - deja apuntado el website del organizador

Modo: python cruzar_goabase.py [--apply] [--preview]
"""
import argparse
import csv
import json
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

PROOT = Path('/Users/angelgarcia/dharmabot')
sys.path.insert(0, str(PROOT))
from core.csv_lock import csv_locked_rows  # noqa: E402

GOABASE_EMAILS = Path(PROOT) / 'goabase_org_emails.json'


def norm(s):
    s = (s or '').lower()
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    s = re.sub(r'\s*(?:party|festival|page|event|facebook|the|@)\s*$', '', s)
    return re.sub(r'[^a-z0-9]+', '', s)


from datetime import date as _date  # noqa: E402

_GENERIC = {'psychedelic', 'party', 'festival', 'rave', 'trance', 'fullmoon',
            'full moon', 'outdoor', 'indoor', 'techno', 'psychedelictrance'}


def fecha_ok(rows_fecha, p):
    try:
        d1 = _date.fromisoformat(p.get('dateStart') or '')
    except Exception:
        return False
    fd = (rows_fecha or '').strip()
    if not fd:
        return False
    try:
        d2 = _date.fromisoformat(fd[:10])
    except Exception:
        return False
    return abs((d1 - d2).days) <= 2


def town_ok(lugar, p):
    t = (p.get('nameTown') or '').strip()
    if not t or len(t) < 3:
        return False
    return t.lower() in ((lugar or '').lower())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--preview', action='store_true')
    args = ap.parse_args()

    try:
        gb = json.load(urllib.request.urlopen(
            'https://www.goabase.net/api/party/json/?limit=500', timeout=30))
    except Exception:
        print('ERR goabase'); return
    parties = gb.get('partylist', [])

    gb_emails = {}
    if GOABASE_EMAILS.exists():
        d = json.loads(GOABASE_EMAILS.read_text(encoding='utf-8'))
        gb_emails = {k: v['email'] for k, v in d.items() if v.get('email')
                     and '@' in v['email'] and 'linktr' not in v['email']}
    print(f'parties goabase: {len(parties)} | emails org goabase: {len(gb_emails)}')

    # índice: nombre normalizado -> party (sin duplicados por nombre)
    idx = {}
    for p in parties:
        k = norm(p.get('nameParty') or '')
        if k and len(k) >= 5 and k not in idx:
            idx[k] = p

    aplicadas_email = []
    aplicadas_org = []
    with csv_locked_rows(str(PROOT / 'eventos_encontrados.csv')) as (todas, fieldnames):
        for r in todas:
            if (r.get('email') or '').strip():
                continue
            ne = norm(r.get('nombre') or '')
            if len(ne) < 5:
                continue
            p = idx.get(ne)
            if p is None:
                for k, cand in idx.items():
                    if len(k) >= 7 and (k in ne or ne in k):
                        p = cand
                        break
            if p is None:
                continue
            # gate de confianza: genéricos exigen fecha (o pueblo); distintivos toleran nombre
            nlen = len(norm(p.get('nameParty') or ''))
            generico = any(g in (p.get('nameParty') or '').lower() for g in _GENERIC) or nlen < 12
            if generico:
                if not (fecha_ok(r.get('fecha'), p) or town_ok(r.get('lugar'), p)):
                    continue
            elif not (fecha_ok(r.get('fecha'), p) or town_ok(r.get('lugar'), p)):
                if nlen < 16:
                    continue
            org = (p.get('nameOrganizer') or '').strip()
            email = gb_emails.get(org.strip().lower())
            if args.preview and (email or not org):
                pass
            if not (r.get('organizador') or '').strip():
                if org and org.lower() not in ('n/a', ''):
                    r['organizador'] = org
                    aplicadas_org.append((r.get('nombre') or '')[:30])
            if email:
                r['email'] = email
                aplicadas_email.append((r.get('nombre') or '')[:30])
    print(f'filas con email rellenado: {len(aplicadas_email)}')
    for x in aplicadas_email[:15]:
        print('   +', x)
    print(f'filas con organizador real rellenado: {len(aplicadas_org)}')
    for x in aplicadas_org[:10]:
        print('   org+', x)


if __name__ == '__main__':
    main()