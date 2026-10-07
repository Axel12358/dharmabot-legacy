#!/usr/bin/env python3
"""Aplicador semantico/token para filas FB sin org.

TIER A: el titulo del evento contiene >=2 tokens raros del organizador
         y NINGUNO es nombre de ciudad/pais (evita falsos como
         'Say No More Madrid' <- 'FIN DE AÑO EN NUEVA YORK').
TIER B: organizador con rep>=5 que toca en la CIUDAD EXACTA del evento
         (criterio 'cuantas fiestas hace y donde'). Por defecto solo
         aplica si el org cubre >=3 ciudades distintas (scene-wide, no
         venue-unico como 'phanganparty' quien de hecho organice la isla).

DRY-RUN por defecto. --apply para escribir. Solo rellena vacios.
"""
import argparse
import csv
import re
import sys

sys.path.insert(0, '/Users/angelgarcia/dharmabot')
from propagacion_caché_limpio import FUENTES_FIABLES
from loop_completar import _es_org_placeholder, es_org_slugderivado, tipo_organizador
from core.csv_lock import csv_locked_rows

CSV = '/Users/angelgarcia/dharmabot/eventos_encontrados.csv'

CIUDADES = set('''madrid barcelona london berlin paris lisbon zurich amsterdam prague vienna
munich hamburg stuttgart dublin bristol glasgow edinburgh manchester liverpool birmingham
tulum miami new york los angeles san francisco melbourne sydney byron bay adelaide perth
moscow warsaw krakow milan rome bogota buenos aires sao paulo rio cancun playa del carmen
riviera maya canggu bali bangkok phuket tokyo osaka seoul bombay mumbai delhi bangalore
johannesburg capetown santiago lima tokio istanbul athens thessaloniki lyon nice marseille
bordeaux leipzig cologne frankfurt dusseldorf dortmund essen groningen amsterdam rotterdam
ubud petra riga tallinn helsinki oslo stockholm gothenburg copenhagen antwerp brussels
athens crete lamu zanzibar marrakech cairo tangier tulum koh phangan samui chiang mai
khao san pattaya goa ancón manizales medellin quito bogota lima asuncion montevideo
santiago valparaiso melbourne byron twyrod saints turkus fungale'''.split())

NOM_PROPIO = set('''arba aspartik axel bayfort b1 bloober blue current fuzzy lofi oido fuerte
dark net notte obliq patrulla ekibling narner offbeat unbeat axial euphoria'''.split())
FUENTE_STR = set('resident advisor goabase setline partyflock psytrance.pl meetup'.split())

def norm(n):
    n = re.sub(r'\b(facebook|fb|event|events|party|festival|fiesta|gathering|open.?air|'
               r'202\d|edition|presents|presenta|by|night|days|edition|time|club|crew|'
               r'sunday|saturday|friday|vol|edition|teaser)\b', ' ', (n or ''), flags=re.I)
    n = re.sub(r'[\W_]+', ' ', n)
    return ' '.join(n.lower().split())

MESES = set('january february march april may june july august september october november december'.split())
DIAS = set('monday tuesday wednesday thursday friday saturday sunday'.split())

def es_ciudad(t):
    return t in CIUDADES or t in MESES or t in DIAS

def es_fecha_like(o):
    return bool(re.search(r'\b\d{1,2}(st|nd|rd|th)?\b', o)) or '20' in o if o else False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--min-tokens', type=int, default=2)
    ap.add_argument('--rep-min', type=int, default=3)
    ap.add_argument('--rep-phangan', type=int, default=1)  # 0 desactiva TIER B
    args = ap.parse_args()

    with csv_locked_rows(CSV) as (todas, _):
        fiables = [r for r in todas if (r.get('fuente') or '').strip() in FUENTES_FIABLES
                   and (r.get('organizador') or '').strip().lower() not in ('', 'n/a')]
        fb_noorg = [r for r in todas if 'Facebook' in r.get('fuente', '')
                    and (r.get('organizador') or '').strip() in ('', 'N/A')]

        orgs = {}
        for r in fiables:
            o = (r.get('organizador') or '').strip()
            if not o or _es_org_placeholder(o) or es_org_slugderivado(o):
                continue
            if es_fecha_like(o.lower()):
                continue
            if len([t for t in norm(o).split() if t in FUENTE_STR]):
                continue
            oc = o.lower()
            info = orgs.setdefault(oc, {'name': o, 'tokens': norm(o).split(), 'count': 0,
                                        'ciudades': set(), 'emails': set()})
            info['count'] += 1
            c = (r.get('lugar') or '').strip().lower()
            if c and c not in ('', 'n/a'):
                info['ciudades'].add(c)
            e = (r.get('email') or '').strip()
            if e and '@' in e:
                info['emails'].add(e)

        # TIER A: 2+ tokens raros del org en el titulo, ninguno ciudad
        tierA = {}
        for r in fb_noorg:
            if (r.get('organizador') or '').strip() not in ('', 'N/A'):
                continue
            nombre = norm(r.get('nombre', ''))
            if not nombre:
                continue
            ntok = set(nombre.split())
            for oc, info in orgs.items():
                raros = [t for t in info['tokens'] if t and not es_ciudad(t)]
                if len(raros) < args.min_tokens:
                    continue
                if set(raros).issubset(ntok):
                    tierA.setdefault(r['link'], (info['name'], info['count'], info['emails']))
        # TIER B: org que toca la ciudad exacta del evento
        tierB = {}
        if args.rep_phangan >= 0:
            for r in fb_noorg:
                if (r.get('organizador') or '').strip() not in ('', 'N/A'):
                    continue
                ciudad = (r.get('lugar') or '').strip().lower()
                p = (r.get('pais') or '').strip()
                if not ciudad:
                    continue
                for oc, info in orgs.items():
                    if ciudad in info['ciudades'] and info['count'] >= args.rep_phangan:
                        # requiere que cubra >=2 ciudades (scene-wide)
                        if len(info['ciudades']) >= 2:
                            tierB.setdefault(r['link'], (info['name'], info['count'], info['emails']))

    apli = {}
    for d in (tierA, tierB):
        for k, v in d.items():
            apli.setdefault(k, v)
    print(f'TIER A: {len(tierA)} | TIER B: {len(tierB)} | union: {len(apli)}')
    seen_orgs = {v[0] for v in apli.values()}
    print(f'organizadores unicos: {len(seen_orgs)}')
    for o, c, mails in sorted({(v[0], v[1], tuple(sorted(v[2]))) for v in apli.values()}):
        print(f'   {o!r} (rep={c}, emails={len(mails)})')

    if args.apply:
        gan_org = 0
        gan_email = 0
        bylink = {r['link']: r for r in todas}
        for link, (o, c, mails) in apli.items():
            r = bylink.get(link)
            if r is None:
                continue
            if (r.get('organizador') or '').strip() not in ('', 'N/A'):
                continue
            r['organizador'] = o
            r['tipo_organizador'] = tipo_organizador(o)
            gan_org += 1
            if mails and (r.get('email') or '').strip() in ('', 'N/A'):
                r['email'] = sorted(mails)[0]
                gan_email += 1
        print(f'APLICADO: {gan_org} orgs, {gan_email} emails')
    else:
        print('(dry-run — usa --apply para escribir)')


if __name__ == '__main__':
    main()