#!/usr/bin/env python3
"""Sanea catalogo_org_email.json: vacía emails basura (footers/plantillas/artefactos)
conservando el organizador. Reversible: escribe backup .bak antes de guardar.

Uso:  python sanear_catalogo.py [--apply]
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, '/Users/angelgarcia/dharmabot')
from core.emails_guard import es_email_basura  # noqa: E402

CAT = Path('/Users/angelgarcia/dharmabot/catalogo_org_email.json')


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
        if es_email_basura(e):
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
