#!/usr/bin/env python3
"""Asignador semántico de organizador para filas FB sin org.

Huella: embedding BAAI/bge-small-en-v1.5 (Hugging Face vía fastembed).
En vez de exigir nombre idéntico, asocia evento FB genérico con el
organizador local del MISMO país que mejor coincide por tema + señales:

  - coseno >= umbral (default 0.75)
  - mismo país
  - señales de validación (suben confianza):
    a) el org tiene OTROS eventos en la misma ci 'lugar' del FB  (venue_hit)
    b) el nombre FB contiene tokens del org
    c) reputación del org (>=3 eventos en dataset)

Solo rellena filas VACÍAS (nunca sobrescribe). El org viene SIEMPRE de
fuentes fiables (RA/Goabase/Setline/Meetup/Partyflock/Psytrance.pl).
DRY-RUN por defecto. --apply para escribir. Requiere HF cache.
"""
import argparse
import csv
import re
import sys
import numpy as np
from fastembed import TextEmbedding

sys.path.insert(0, '/Users/angelgarcia/dharmabot')
from loop_completar import es_org_slugderivado, _es_org_placeholder, tipo_organizador
from propagacion_caché_limpio import FUENTES_FIABLES
from core.csv_lock import csv_locked_rows

CACHE = '/var/folders/9d/qg43s0494tx2nlnrtfmt2y540000gn/T/opencode/hf_cache'
CSV = '/Users/angelgarcia/dharmabot/eventos_encontrados.csv'
MODELO = 'BAAI/bge-small-en-v1.5'
UMBRAL = 0.75


def norm(n):
    n = re.sub(r'\b(facebook|fb|event|events|party|festival|fiesta|gathering|open.?air|'
               r'202\d|edition|presents|presenta|by)\b', ' ', (n or ''), flags=re.I)
    n = re.sub(r'[\W_]+', ' ', n)
    return ' '.join(n.lower().split())


def emb_batch(model, texts):
    out = np.vstack(list(model.embed(texts, batch_size=64)))
    for i in range(len(out)):
        out[i] /= np.linalg.norm(out[i])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--umbral', type=float, default=UMBRAL)
    args = ap.parse_args()
    umbral = args.umbral

    with csv_locked_rows(CSV) as (todas, _):
        fiables = [r for r in todas if (r.get('fuente') or '').strip() in FUENTES_FIABLES
                   and (r.get('organizador') or '').strip().lower() not in ('', 'n/a')]
        fb_noorg = [r for r in todas if 'Facebook' in r.get('fuente', '')
                    and (r.get('organizador') or '').strip() in ('', 'N/A')]
        # reputación org -> nº filas en dataset
        reput = {}
        for r in todas:
            o = (r.get('organizador') or '').strip()
            if o and o.lower() not in ('', 'n/a'):
                reput[o.lower()] = reput.get(o.lower(), 0) + 1
        # venues donde toca cada org (ciudades de sus filas)
        org_ciudades = {}
        for r in todas:
            o = (r.get('organizador') or '').strip()
            c = (r.get('lugar') or '').strip()
            if o and o.lower() not in ('', 'n/a') and c and c.lower() not in ('', 'n/a'):
                org_ciudades.setdefault(o.lower(), set()).add(c.lower())

    print(f'fiables c/org: {len(fiables)} | FB sin org: {len(fb_noorg)}', flush=True)

    m = TextEmbedding(model_name=MODELO, cache_dir=CACHE)
    mtxt = [norm(r.get('nombre', '')) for r in fiables]
    memb = emb_batch(m, mtxt)
    by_pais = {}
    for r, v in zip(fiables, memb):
        by_pais.setdefault((r.get('pais') or '').strip().lower(), []).append((v, r))

    ftxt = [norm(r.get('nombre', '')) for r in fb_noorg]
    femb = emb_batch(m, ftxt)

    def org_lim(o):
        o = (o or '').strip()
        if not o or _es_org_placeholder(o) or es_org_slugderivado(o):
            return ''
        return o

    aplicables = {}     # idx fila -> (org, senal, cos, nombre_fb)
    for i, (r, v) in enumerate(zip(fb_noorg, femb)):
        if (r.get('organizador') or '').strip() not in ('', 'N/A'):
            continue
        cands = by_pais.get((r.get('pais') or '').strip().lower(), [])
        if not cands:
            continue
        scores = np.array([c[0] for c in cands]) @ v
        idx = int(np.argmax(scores))
        s = float(scores[idx])
        if s < umbral:
            continue
        mon = cands[idx][1]
        o = org_lim(mon.get('organizador', ''))
        if not o:
            continue
        fb_city = (r.get('lugar') or '').strip().lower()
        venue_hit = bool(fb_city and fb_city in org_ciudades.get(o.lower(), set()))
        rep = reput.get(o.lower(), 0)
        # token overlap fb<->org
        fb_tok = set(norm(r.get('nombre', '')).split())
        org_tok = set(norm(o).split())
        tok_hit = bool(fb_tok & org_tok and len(fb_tok & org_tok) >= 1)
        if not (venue_hit or rep >= 3 or tok_hit):
            continue
        senal = ('venue' if venue_hit else '') + ('|rep' if rep >= 3 else '') + ('|tok' if tok_hit else '')
        aplicables[i] = (o, senal, s, r.get('nombre', '')[:45], r.get('pais', ''))

    print(f'APLICABLES (umbral {umbral}): {len(aplicables)}', flush=True)
    from collections import Counter as _C
    sig = _C(a[1] for a in aplicables.values())
    print('señales:', dict(sig))
    # muestra
    for i, (o, sen, s, nm, pais) in list(aplicables.items())[:12]:
        print(f'  cos={s:.2f} [{sen}] {pais} | {nm!r} -> {o!r}')

    if args.apply and aplicables:
        gan_org = 0
        gan_email = 0
        cache_org_email = {}
        with csv_locked_rows(CSV) as (todas, _):
            org_email = {}
            for r in todas:
                fuente = (r.get('fuente') or '').strip()
                if fuente not in FUENTES_FIABLES:
                    continue
                o = (r.get('organizador') or '').strip()
                e = (r.get('email') or '').strip()
                if o and e and _es_email_ok(e):
                    org_email.setdefault(o.lower(), e)
            for ix, (o, sen, s, nm, pais) in aplicables.items():
                r = todas[ix]
                if (r.get('organizador') or '').strip() not in ('', 'N/A'):
                    continue
                r['organizador'] = o
                r['tipo_organizador'] = tipo_organizador(o)
                gan_org += 1
                e = org_email.get(o.lower())
                if e and (r.get('email') or '').strip() in ('', 'N/A'):
                    r['email'] = e
                    gan_email += 1
        print(f'APLICADO: {gan_org} orgs, {gan_email} emails')
    elif not args.apply:
        print('(dry-run — usa --apply para escribir)')


def _es_email_ok(e):
    import re as _re
    e = (e or '').strip().lower()
    if not e or not _re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]{2,}$', e):
        return False
    if e.split('@')[1] in ('gmail.com', 'hotmail.com', 'yahoo.com', 'outlook.com', 'mail.com'):
        return False
    if e[:10] in ('info@', 'contact@', 'hello@', 'hola@', 'web@', 'booking@'):
        return False
    return True


if __name__ == '__main__':
    main()