#!/usr/bin/env python3
"""Propaga organizador por email: fila sin org cuyo email ya tiene org en otra fila,
VALIDADO porque el nombre del org hace match con el nombre del evento (tokens raros
en comun). Dry-run por defecto; --apply para escribir bajo csv_lock.
"""
import argparse
import csv
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, '/Users/angelgarcia/dharmabot')
from loop_completar import _es_org_placeholder, es_org_slugderivado, tipo_organizador
from core.csv_lock import csv_locked_rows

CSV = '/Users/angelgarcia/dharmabot/eventos_encontrados.csv'
GENERICOS = set('''party rave festival festival open air gathering ceremony ritual celebration night
woods forest jungle techno psytrance goa trance psychedelic trance progressive darkpsy music events
club dance club night openair open opens air smoke sound system rave trance nocturna musica
die el la les le the of and or'''.split())


def es_fecha_like(o):
    return bool(re.search(r'\b\d{1,2}(st|nd|rd|th)?\b', (o or ''))) or ('20' in o)


def legit(o):
    o = (o or '').strip()
    if not o or _es_org_placeholder(o) or es_org_slugderivado(o) or es_fecha_like(o.lower()):
        return False
    if o.lower() in ('john doe', 'facebook (dorks)', 'fomo events and old monk entertainments on saturday'):
        return False
    return True


def em_ok(e):
    e = (e or '').strip().lower()
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]{2,}$', e):
        return False
    d = e.split('@')[1]
    for b in ('entreprise', 'sciencing', 'readymag', 'teliportme', 'travel', 'realviews',
              'venue.com', 'tab.travel', 'leadiq', 'delhihospital', 'informa', 'exemplo'):
        if b in d:
            return False
    return True


def tokens_raros(t):
    t = re.sub(r'[\W_]+', ' ', (t or '')).lower()
    return set(x for x in t.split() if x not in GENERICOS and len(x) >= 3)


def norm_nombre(n):
    return re.sub(r'[\W_]+', ' ', (n or '')).lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--min-overlap', type=int, default=1)
    args = ap.parse_args()

    with csv_locked_rows(CSV) as (todas, _):
        emap = defaultdict(Counter)
        for r in todas:
            e = (r.get('email') or '').strip().lower()
            o = (r.get('organizador') or '').strip()
            if em_ok(e) and legit(o):
                emap[e][o] += 1

        org_of = {}
        for e, c in emap.items():
            best = c.most_common(1)[0]
            tot = sum(c.values())
            if (best[1] >= 2 and best[1] / tot >= 0.60) or tot == 1:
                org_of[e] = best[0]

        aplic = []
        for r in todas:
            if (r.get('organizador') or '').strip() not in ('', 'N/A'):
                continue
            e = (r.get('email') or '').strip().lower()
            if not em_ok(e) or e not in org_of:
                continue
            o = org_of[e]
            # validacion: match nombre org <-> nombre evento
            ro = tokens_raros(o)
            rn = tokens_raros(r.get('nombre', ''))
            if len(ro & rn) >= args.min_overlap:
                aplic.append((e, o, r.get('nombre', '')[:55], r.get('fuente', '')[:18]))

    print(f'PROPAGABLES con match nombre-org x nombre-evento: {len(aplic)}')
    print(f'organizadores unicos: {len(set(a[1] for a in aplic))}')
    for e, o, nm, fu in aplic[:20]:
        print(f'  {e!r} -> {o!r} | {nm!r} | {fu}')

    if args.apply and aplic:
        byid = {id(r): r for r in todas}
        gan = 0
        for r in todas:
            e = (r.get('email') or '').strip().lower()
            if (r.get('organizador') or '').strip() in ('', 'N/A') and e in org_of:
                ro = tokens_raros(org_of[e])
                rn = tokens_raros(r.get('nombre', ''))
                if len(ro & rn) >= args.min_overlap:
                    r['organizador'] = org_of[e]
                    r['tipo_organizador'] = tipo_organizador(org_of[e])
                    gan += 1
        print(f'APLICADO: {gan} filas con organizador nuevo')
    elif not args.apply:
        print('(dry-run — --apply para escribir)')


if __name__ == '__main__':
    main()