#!/usr/bin/env python3
"""Pasadas offline para empujar org/email (sin red, solo según lock + locks cortos).
A) Org: organizador desde caché de descripciones FB (cache_fb_desc_fechas.json)
   para filas sin org de escena psi.
B) Email: agregar emails válidos por organizador, y por host/slug de venue,
   aplicarlos a filas del mismo org/site sin email. Nunca sobrescribe.
"""
import csv, json, re, sys, collections
from pathlib import Path
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from core.csv_lock import csv_locked_rows
from core.fb_ids import extraer_id
from minar_fb_og import org_desde_desc, _ESCENA
from loop_completar import es_email_valido, _es_org_placeholder

CSV = ROOT / 'eventos_encontrados.csv'
DESC = ROOT / 'cache_fb_desc_fechas.json'

def _escena(sub):
    sub = (sub or '').strip().lower()
    if not sub or sub == 'n/a':
        return True
    return sub in _ESCENA or sub.endswith(('party', 'rave', 'festival', 'fest'))

def _org_key(o):
    o = (o or '').strip().lower()
    return re.sub(r'[^a-z0-9]+', '', o)

def _host_slug(link):
    m = re.search(r'facebook\.com/events/([^/?#]+)', (link or '').lower())
    return m.group(1) if m else None

def main():
    # --- A: org desde caché de descripciones ---
    descmap = {}
    if DESC.exists():
        descmap = json.loads(DESC.read_text(encoding='utf-8'))
    org_ids = {}
    for i, v in descmap.items():
        if isinstance(v, str) and not v.startswith('BACKUP:'):
            o = org_desde_desc(v)
            if o and o.lower().strip() not in ('facebook', ''):
                org_ids[i] = re.sub(r'\s+', ' ', o).strip()

    gan_o = 0
    with csv_locked_rows(CSV, timeout=300) as (rows, _fn):
        for r in rows:
            if (r.get('organizador') or '').strip().lower() in ('', 'n/a') and _escena(r.get('subgenero')):
                i = extraer_id(r.get('link', ''))
                o = org_ids.get(i)
                if o:
                    r['organizador'] = o
                    gan_o += 1
    print('A) organizadores aplicados desde caché desc:', gan_o)

    # --- B: email por organizador ---
    with csv_locked_rows(CSV, timeout=300) as (rows, _fn):
        cache_org = collections.defaultdict(collections.Counter)
        cache_host = collections.defaultdict(collections.Counter)
        for r in rows:
            em = (r.get('email') or '').strip()
            if not es_email_valido(em):
                continue
            ok = (r.get('organizador') or '').strip()
            if ok and not _es_org_placeholder(ok):
                cache_org[_org_key(ok)][em] += 1
            hs = _host_slug(r.get('link', ''))
            if hs:
                cache_host[hs][em] += 1
        best_org = {k: v.most_common(1)[0][0] for k, v in cache_org.items()}
        best_host = {k: v.most_common(1)[0][0] for k, v in cache_host.items()}
        gan_e = 0
        for r in rows:
            if (r.get('email') or '').strip():
                continue
            em = None
            ok = (r.get('organizador') or '').strip()
            if ok and not _es_org_placeholder(ok):
                em = best_org.get(_org_key(ok))
            if not em:
                hs = _host_slug(r.get('link', ''))
                em = best_host.get(hs) if hs else None
            if em and es_email_valido(em):
                r['email'] = em
                gan_e += 1
    print('B) emails propagados por organizador/venue:', gan_e)

if __name__ == '__main__':
    main()