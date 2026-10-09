#!/usr/bin/env python3
"""Sanea catalogo_org_email.json: vacía emails basura (footers/plantillas/artefactos)
conservando el organizador. Reversible: escribe backup .bak antes de guardar.

Uso:  python sanear_catalogo.py [--apply]
"""
import argparse
import json
import re
import shutil
from pathlib import Path

CAT = Path('/Users/angelgarcia/dharmabot/catalogo_org_email.json')

JUNK_RE = re.compile(
    r'^u003[ce]'
    r'|^scams@|^reportphishing@|^abuse@'
    r'|legal@partyx\.info'
    r'|khalti\.com'
    r'|newcastleherald\.com\.au'
    r'|support\.yandex'
    r'|@email\.(fr|nl)$|@community\.org$'
    r'|@example\.(com|org)$|@dominio\.|@correo\.'
    r'|^(votre|jouw|you|your)@',
    re.I,
)
DEFAULT_MASIVO = 'alteredstatepsy@gmail.com'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    cat = json.loads(CAT.read_text(encoding='utf-8'))
    tocados = []
    for k, v in cat.items():
        if not isinstance(v, dict):
            continue
        e = (v.get('email') or '').strip()
        if not e:
            continue
        if JUNK_RE.search(e.lower()) or e.lower() == DEFAULT_MASIVO:
            tocados.append((k, e))
            v['email'] = ''

    print(f'entradas con email basura a vaciar: {len(tocados)}')
    for k, e in tocados[:40]:
        print(f'   {k}  <- {e}')
    if not args.apply:
        print('(dry-run — usa --apply)')
        return
    shutil.copy2(CAT, CAT.with_suffix('.json.bak'))
    CAT.write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'APLICADO: {len(tocados)} emails vaciados en el catálogo (backup .json.bak)')


if __name__ == '__main__':
    main()
