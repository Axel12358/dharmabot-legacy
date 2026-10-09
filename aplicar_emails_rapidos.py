#!/usr/bin/env python3
"""Aplica emails YA CONOCIDOS por organizador (agencias_escena + catálogo)
a todas las filas sin email. Solo rellena vacíos; nunca pisa ni borra.

Sumenta sin restar. Reversible de facto: los emails reales quedan si se
decide lo contrario (basta re-vaciarlas con depurar_emails_masivos).
"""
import csv, json, sys
sys.path.insert(0, '/Users/angelgarcia/dharmabot')
from core.csv_lock import csv_locked_rows
from core.emails_guard import es_email_basura

CSV = '/Users/angelgarcia/dharmabot/eventos_encontrados.csv'


def _email_ok(e):
    e = (e or '').strip()
    if not e or '@' not in e or es_email_basura(e):
        return False
    return True


def main():
    pares = {}

    for p in ('agencias_bookings_escena.csv',):
        try:
            with open('/Users/angelgarcia/dharmabot/' + p, encoding='utf-8') as f:
                for r in csv.DictReader(f):
                    o = (r.get('organizador') or '').strip().lower()
                    e = (r.get('email') or '').strip()
                    if o and _email_ok(e) and len(o) >= 3:
                        pares.setdefault(o, e)
        except FileNotFoundError:
            print('sin', p)

    try:
        cat = json.load(open('/Users/angelgarcia/dharmabot/catalogo_org_email.json', encoding='utf-8'))
        for k, v in cat.items():
            o = (k or '').strip().lower()
            e = (v or {}).get('email') if isinstance(v, dict) else None
            if o and _email_ok(e):
                pares.setdefault(o, e.strip())
    except FileNotFoundError:
        print('sin catalogo')

    print(f'pares org→email disponibles: {len(pares)}')

    n = 0
    by = {}
    with csv_locked_rows(CSV) as (todas, fieldnames):
        for r in todas:
            if (r.get('email') or '').strip():
                continue
            o = (r.get('organizador') or '').strip().lower()
            e = pares.get(o)
            if e:
                r['email'] = e
                n += 1
                by[e] = by.get(e, 0) + 1
    print(f'APLICADO: {n} celdas llenadas con emails conocidos por organizador')
    for e, c in sorted(by.items(), key=lambda x: -x[1])[:8]:
        print(f'  {e:44} x{c}')


if __name__ == '__main__':
    main()