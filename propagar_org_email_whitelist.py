#!/usr/bin/env python3
"""Propaga organizador desde email local-part (nombre propio del organizador real).

Lista blanca: emails cuyo local-part es un colectivo/festival/DJ de la escena verificable.
Estrategia del usuario: si el nombre del contacto (email) es nombre propio, ES el organizador.
Solo toca filas FB sin organizador, bajo csv_lock.
"""
import argparse
import csv
import sys

sys.path.insert(0, '/Users/angelgarcia/dharmabot')
from core.csv_lock import csv_locked_rows
from loop_completar import tipo_organizador

CSV = '/Users/angelgarcia/dharmabot/eventos_encontrados.csv'

# local-part del email -> nombre formateado del organizador
WHITELIST = {
    'spiritgust': 'Spiritgust Festival',
    'psytribeusa': 'PsyTribe USA',
    'nycpsytrancefamily': 'NYC Psytrance Family',
    'alteredstatepsy': 'Altered State',
    'eargasmaticteam': 'Eargasmatic',
    'alienchaosmusic': 'Alien Chaos Music',
    'djlydianexus': 'DJ Lydianexus',
    'theflyingmystic': 'Flying Mystic',
    'darkpzy0': 'Dark pzy',
    'shantiplanti': 'Shanti Planti',
    'koskarri': 'Koskarri',
    'shop-spiritbase': 'Spirit Base Festival',
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    with csv_locked_rows(CSV) as (todas, _):
        aplic = []
        for r in todas:
            if (r.get('organizador') or '').strip() not in ('', 'N/A'):
                continue
            if 'Facebook' not in r.get('fuente', ''):
                continue
            e = (r.get('email') or '').strip().lower()
            if not e or '@' not in e:
                continue
            local = e.split('@')[0]
            if local in WHITELIST:
                aplic.append(r)

        print(f'filas FB sin org aplicables (whitelist de emails): {len(aplic)}')
        from collections import Counter
        print(dict(Counter(WHITELIST[e.split("@")[0]] for r in aplic
                           for e in [(r.get('email') or '').strip().lower()])))

        if args.apply:
            gan = 0
            for r in aplic:
                local = (r.get('email') or '').strip().lower().split('@')[0]
                if (r.get('organizador') or '').strip() in ('', 'N/A'):
                    r['organizador'] = WHITELIST[local]
                    r['tipo_organizador'] = tipo_organizador(WHITELIST[local])
                    gan += 1
            print(f'APLICADO: {gan} filas con organizador nuevo')
        else:
            print('(dry-run — --apply para escribir)')


if __name__ == '__main__':
    main()