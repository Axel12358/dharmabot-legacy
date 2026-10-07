#!/usr/bin/env python3
"""Burst online de emails: los N organizadores con más eventos sin email,
búsqueda DDG (minar_email_organizador), aplica con _aplicar_email_organizador.
"""
import csv, re, sys, argparse, collections
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from loop_completar import minar_email_organizador, _aplicar_email_organizador, _es_org_placeholder, es_org_slugderivado, es_email_valido

def _leer_snapshot():
    with open(ROOT / 'eventos_encontrados.csv', encoding='utf-8') as f:
        return list(csv.DictReader(f))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=60)
    ap.add_argument('--threads', type=int, default=8)
    args = ap.parse_args()
    rows = _leer_snapshot()
    cnt = collections.Counter()
    lug = {}
    for r in rows:
        if es_email_valido((r.get('email') or '').strip()):
            continue
        o = (r.get('organizador') or '').strip()
        if not o or _es_org_placeholder(o) or es_org_slugderivado(o):
            continue
        cnt[o] += 1
        lug.setdefault(o, (r.get('lugar') or '').strip())
    # solo orgs sin NINGÚN email ya resuelto
    orgs = [o for o, c in cnt.most_common(args.n)
            if not any(es_email_valido((r.get('email') or '').strip())
                       for r in rows if (r.get('organizador') or '').strip() == o)]
    print(f'orgs a buscar (sin ningún email): {len(orgs)}/{len(cnt)} | filas sin email: {sum(cnt.values())}')

    def task(o):
        try:
            em = minar_email_organizador(o, lug.get(o, ''))
        except Exception:
            em = ''
        if not em:
            return o, 0, em
        g = _aplicar_email_organizador(o, em)
        return o, g, em

    gan_total = 0; ok = 0
    with ThreadPoolExecutor(max_workers=args.threads) as ex:
        futs = {ex.submit(task, o): o for o in orgs}
        for fut in as_completed(futs):
            o, g, em = fut.result()
            if g:
                ok += 1; gan_total += g
                print(f'  {o} -> {em} (+{g})', flush=True)
            else:
                print(f'  {o}: sin email', flush=True)
    print(f'\nTOTAL: {ok} organizadores resueltos, {gan_total} filas actualizadas')

if __name__ == '__main__':
    main()