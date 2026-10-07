#!/usr/bin/env python3
"""Propaga organizador desde email local-part/dominio tras verificación web de subagentes.

Solo toca filas FB sin organizador, bajo csv_lock.
"""
import argparse
import csv

sys_path = '/Users/angelgarcia/dharmabot'

# (local-part OR '::dominio') -> nombre canónico del organizador (verificado en web)
VERIFIED = {
    'baommusic': 'Baom',
    'goapartycircle': 'Goa Party Circle',
    'scene::suomisaundi.fi': 'Suomisaundi',
    'spinningshivaay': 'Spinning Shivaay',
    '19hzinfo': '19hz.info',
    'stepankotouc': 'Gondar',
    'stan::outrance.org': 'Outrance',
    'raphael::outrance.org': 'Outrance',
    'machinelf::tranceam.org': 'TranceAm',
    'pulsion.promotion': 'Pulsion Music',
    'alpha::interzone-pa.com': 'DJ Alpha',
    'lea::atelier-obskur.de': 'Atelier Obskur',
    'vip::trancebro.com': 'Trance, Bro!',
    'psyfi.festival': 'Psy-Fi Festival',
    'tamtam::psychedelicgratefulpunks.nl': 'Psychedelic Grateful Punks',
    'koen::dacru.be': 'Dacru Records',
    'resolutenyc': 'ReSolute',
    'psyience.fiction': 'Psyience Fiction Kollektiv',
    'projektorofficial': 'Projektor',
    'gatopsyticket': 'Gatopsy Festival',
    'pandora.um.collective': 'Pandora Music Collective',
    'max::dragondreaming.com.au': 'Dragon Dreaming Festival',
    'houseofchapora': 'House of Chapora',
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    import sys
    sys.path.insert(0, sys_path)
    from core.csv_lock import csv_locked_rows
    from loop_completar import tipo_organizador

    csv_path = f'{sys_path}/eventos_encontrados.csv'

    def key_for(r):
        e = (r.get('email') or '').strip().lower()
        if not e or '@' not in e:
            return None
        local, dom = e.split('@')[0], e.split('@')[1]
        if local in VERIFIED:
            return local
        if f'{local}::{dom}' in VERIFIED:
            return f'{local}::{dom}'
        return None

    with csv_locked_rows(csv_path) as (todas, _):
        aplic = []
        for r in todas:
            if (r.get('organizador') or '').strip() not in ('', 'N/A'):
                continue
            if 'Facebook' not in r.get('fuente', ''):
                continue
            k = key_for(r)
            if k:
                aplic.append((r, k))

        from collections import Counter
        print(f'filas FB sin org aplicables: {len(aplic)}')
        print(dict(Counter(VERIFIED[k] for _, k in aplic)))

        if args.apply:
            gan = 0
            for r, k in aplic:
                if (r.get('organizador') or '').strip() in ('', 'N/A'):
                    org = VERIFIED[k]
                    r['organizador'] = org
                    r['tipo_organizador'] = tipo_organizador(org)
                    gan += 1
            print(f'APLICADO: {gan} filas con organizador nuevo')
        else:
            print('(dry-run — --apply para escribir)')


if __name__ == '__main__':
    main()