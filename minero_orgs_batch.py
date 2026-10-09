#!/usr/bin/env python3
"""Minero BATCH de emails por organizador.

Cola = organizadores de goabase (103) + organizadores descubiertos de Eventbrite.
Para cada uno: DDG (email/contact) + web del org (homepage/contacto). Guarda el
progreso en org_emails_minados.json (incremental). Luego --apply cruza por name
normalizado y rellena SOLO filas sin email. Nunca pisa.

Integra el mismo criterio central (core.emails_guard) que el loop.
"""
import argparse
import json
import re
import sys
import threading
import time
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROOT = Path('/Users/angelgarcia/dharmabot')
sys.path.insert(0, str(PROOT))
from serp_worker import search as ddg_search  # noqa: E402
from core.emails_guard import es_email_basura  # noqa: E402

OUT = PROOT / 'org_emails_minados.json'

_UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                     'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'}
_MAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
_skips = re.compile(r'\b(image|static|webmaster@example|noreply|no-reply|support@example|'
                    r'example\.com|example\.org|abuse@|security@|press@eventbrite|'
                    r'orders@eventbrite|charity@eventbrite|ebhelp@eventbrite)\b', re.I)
free_mail = re.compile(r'@(gmail|hotmail|outlook|yahoo|live|gmx|mail\.com)\.')


def _email_valido(e):
    e = (e or '').strip().lower()
    if not e or e.count('@') != 1 or len(e) > 60:
        return False
    if es_email_basura(e) or _skips.search(e):
        return False
    return True


def _fetch(url, timeout=14):
    try:
        req = urllib.request.Request(url, headers=_UA)
        return urllib.request.urlopen(req, timeout=timeout).read().decode('utf-8', 'ignore')
    except Exception:
        return ''


def _emails_html(html):
    out = []
    for m in _MAIL_RE.findall(html or ''):
        e = m.strip('.-').lower()
        if _email_valido(e):
            out.append(e)
    return out


def _mejor(grupo):
    vivos = [e for e in grupo if _email_valido(e)]
    if not vivos:
        return ''
    # preferir dominio propio/corporativo sobre free-mail
    libres = [e for e in vivos if not free_mail.search(e)]
    if libres:
        return libres[0]
    return vivos[0]


def minar_org(org):
    emails = []
    try:
        res = ddg_search(f'"{org}" email contact', timeout=22)
        for r in (res.get('results') or [])[:5]:
            u0 = (r.get('url') or '')
            if not u0 or re.search(r'(facebook|instagram|twitter|tiktok|youtube|'
                                   r'eventbrite|wikipedia|imdb|linkedin)\\.', u0, re.I):
                continue
            h = _fetch(u0)
            emails += _emails_html(h)
    except Exception:
        pass
    if not emails:
        try:
            res = ddg_search(f'"{org}" psytrance promoter booking', timeout=22)
            for r in (res.get('result') or res.get('results') or [])[:5]:
                u0 = (r.get('url') or '')
                if not u0 or re.search(r'(facebook|instagram|twitter|tiktok|youtube|'
                                       r'eventbrite|wikipedia|imdb|linkedin)\\.', u0, re.I):
                    continue
                h = _fetch(u0)
                emails += _emails_html(h)
        except Exception:
            pass
    seen = []
    for e in emails:
        if _email_valido(e) and e not in seen:
            seen.append(e)
    return _mejor(seen)


def norm(s):
    s = (s or '').lower()
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', '', s)


def _colas():
    orgs = {}
    try:
        gb = json.loads((PROOT / 'goabase_org_emails.json').read_text(encoding='utf-8'))
        for k, v in gb.items():
            if not (v or {}).get('email'):
                orgs[norm(k)] = k
    except Exception:
        pass
    try:
        eb = json.loads((PROOT / 'eventbrite_orgs.json').read_text(encoding='utf-8'))
        for o in eb.get('organizadores', []):
            orgs.setdefault(norm(o.get('nombre')), o.get('nombre'))
    except Exception:
        pass
    return orgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tope', type=int, default=0)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    if args.apply:
        return apply()

    prev = {}
    if OUT.exists():
        try:
            prev = json.loads(OUT.read_text(encoding='utf-8'))
        except Exception:
            prev = {}

    cola = _colas()
    quitar = {k for k, v in prev.items() if v.get('email')}
    pend = [v for k, v in cola.items() if k not in prev or k in quitar]
    if args.tope:
        pend = pend[:args.tope]
    print(f'cola total {len(cola)} | pendientes {len(pend)}')
    lock = threading.Lock()
    ok = err = 0
    t0 = time.time()

    def tarea(org):
        nonlocal ok, err
        try:
            e = minar_org(org)
        except Exception:
            e = ''
        with lock:
            prev[norm(org)] = {'org': org, 'email': e, 't': time.strftime('%H:%M:%S')}
            if e:
                ok += 1
            else:
                err += 1
            if ok + err % 10 == 0 or (ok + err) % 25 == 0:
                OUT.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding='utf-8')
                print(f'  … {ok+err}/{len(pend)}  (email {ok}, vacíos {err}) {time.time()-t0:.0f}s')

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(tarea, pend))
    OUT.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'FIN: con email {ok} | vacíos {err} | {time.time()-t0:.0f}s')


def apply():
    from core.csv_lock import csv_locked_rows
    prev = {}
    try:
        prev = json.loads(OUT.read_text(encoding='utf-8'))
    except Exception:
        pass
    con = [(k, v['email']) for k, v in prev.items() if v.get('email') and _email_valido(v['email'])]
    tabla = {k: e for k, e in con}
    print(f'emails minados aplicables: {len(tabla)}')
    n = 0
    by = {}
    with csv_locked_rows(str(PROOT / 'eventos_encontrados.csv')) as (todas, fn):
        for r in todas:
            if (r.get('email') or '').strip():
                continue
            e = tabla.get(norm(r.get('organizador') or ''))
            if e:
                r['email'] = e
                n += 1
                by[e] = by.get(e, 0) + 1
    print(f'APLICADO: {n} celdas (por organizador)')
    for e, c in sorted(by.items(), key=lambda x: -x[1])[:8]:
        print(f'  {e:44} x{c}')


if __name__ == '__main__':
    main()