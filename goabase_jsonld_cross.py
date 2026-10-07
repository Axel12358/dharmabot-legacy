#!/usr/bin/env python3
"""Consolida el directorio Goabase vía API JSON-LD y cruza contra el CSV.

Goabase (/api/party/jsonld/country/<CC> -> por-país; /api/party/jsonld/<id>
-> evento con organizer.email). Crossmatch con filas sin email/org usando
nombre normalizado + fecha real (Goabase SI trae fecha).

dry-run por defecto (--apply para escribir).
"""
import argparse
import csv
import json
import re
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from loop_completar import es_email_valido, _es_org_placeholder, es_org_slugderivado, tipo_organizador
from propagacion_caché_limpio import _email_utilizable
from core.csv_lock import csv_locked_rows

CSV_FILE = Path(__file__).parent / 'eventos_encontrados.csv'
UA = {'User-Agent': 'Mozilla/5.0 (Macintosh) DharmadhatuResearch/1.0'}

def get_json(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    raw = urllib.request.urlopen(req, timeout=timeout).read().decode('utf-8', 'ignore')
    return json.loads(raw)

def normalizar(n):
    n = re.sub(r"\b(party|festival|open air|facebook|fiesta|evento|event|gathering)\b", ' ', n, flags=re.I)
    n = re.sub(r'\b(\d{4}|\d{1,2}[/\-.]\d{1,2})\b', ' ', n)
    n = re.sub(r'[\W_]+', ' ', n)
    return sorted(set(w for w in n.lower().split() if len(w) >= 4))

def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(set(a) & set(b)) / len(set(a) | set(b))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--max-country', type=int, default=999)
    args = ap.parse_args()

    # 1) lista de países + eventos por país
    countries = get_json('https://www.goabase.net/api/party/jsonld/country/list')
    eventos = []   # (nombre_norm, fecha_YYYY-MM-DD, org, email, url, pais)
    n_country = 0
    for item in countries.get('itemListElement', []):
        n_country += 1
        if n_country > args.max_country:
            break
        cc_url = item['url']
        try:
            lst = get_json(cc_url)
        except Exception as e:
            print('  país ERROR', item['name'], str(e)[:50]); continue
        ids = [(el.get('url'), el.get('name')) for el in lst.get('itemListElement', [])]
        for ev_url, ev_name in ids:
            try:
                ev = get_json(ev_url)
            except Exception:
                continue
            org = ev.get('organizer', {}) or {}
            oname = (org.get('name', '') or '').strip()
            oemail = (org.get('email', '') or '').strip()
            fecha = (ev.get('startDate', '') or '')[:10]
            loc = (ev.get('location', {}) or {}).get('name', '') or ''
            if not oname or not fecha:
                continue
            eventos.append((normalizar(ev.get('name','') or ''), fecha, oname, oemail, ev.get('url',''), loc))
        time.sleep(0.2)
        if n_country % 5 == 0:
            print(f'  ...{n_country} países | {len(eventos)} eventos')

    # dedup por url
    seen = set()
    unicos = []
    for e in eventos:
        if e[4] in seen:
            continue
        seen.add(e[4]); unicos.append(e)
    eventos = unicos

    # caché org -> email dentro de goabase
    cache_org_email = {}
    for _, _, oname, oemail, _, _ in eventos:
        if _email_utilizable(oemail):
            cache_org_email.setdefault(oname.lower(), set()).add(oemail)

    print(f"\nGoabase consolidado: {len(eventos)} eventos, {len(cache_org_email)} orgs con email")

    # 2) cruz contra CSV
    with csv_locked_rows(CSV_FILE) as (todas, _):
        sin_email = [r for r in todas if (r.get('email') or '').strip() in ('', 'N/A')]
        target = [(r, normalizar(r.get('nombre', '') or ''), (r.get('fecha', '') or '')[:10]) for r in sin_email]
        # index por fecha para fast match
        by_fecha = defaultdict(list)
        for r, nt, f in target:
            by_fecha[f].append((r, nt))

        gan_email = 0
        gan_org = 0
        for (nt, fecha, oname, oemail, url, loc) in eventos:
            # buscar filas con misma fecha (o flexible: misma fecha o placeholder)
            candidatos = by_fecha.get(fecha, []) + by_fecha.get(fecha[:7] + '-01', [])  # formato placeholder
            for r, rname in candidatos:
                if (r.get('email') or '').strip() not in ('', 'N/A'):
                    continue
                j = jaccard(nt, rname)
                if j >= 0.55:
                    if not (r.get('organizador') or '').strip() or (r.get('organizador') or '').strip().lower() in ('', 'n/a'):
                        r['organizador'] = oname
                        r['tipo_organizador'] = tipo_organizador(oname)
                        gan_org += 1
                    if _email_utilizable(oemail):
                        r['email'] = oemail
                        gan_email += 1
        # propagar caché goabase email a filas con el MISMO org
        for r in todas:
            if (r.get('email') or '').strip():
                continue
            org = (r.get('organizador') or '').strip()
            if _es_org_placeholder(org) or es_org_slugderivado(org):
                continue
            cands = cache_org_email.get(org.lower())
            if cands:
                for e in cands:
                    if _email_utilizable(e):
                        r['email'] = e
                        gan_email += 1
                        break

        print(f"DRY-RUN" if not args.apply else "APLICADO")
        print(f"  orgs nuevos: {gan_org} | emails nuevos: {gan_email}")

    if not args.apply:
        print("usa --apply para escribir")

if __name__ == '__main__':
    main()