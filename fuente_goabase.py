#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fuente goabase→email: organizador (web del org) → email de contacto.

1. Descarga partylist de goabase.net (JSON público): parties + nameOrganizer + urlOrganizer.
2. Por cada organizador con web: fetch homepage + página de contacto → emails.
3. Guarda goabase_org_emails.json {org (lower): {url, email, pagina}}.
4. Modo --apply: rellena filas del CSV cuyo organizador coincida (solo vacíos).

Uso:  python fuente_goabase.py [--dry] [--max N] [--apply]
"""
import argparse
import csv
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

PROOT = Path('/Users/angelgarcia/dharmabot')
sys.path.insert(0, str(PROOT))
from core.emails_guard import es_email_basura  # noqa: E402

OUT = PROOT / 'goabase_org_emails.json'

EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
MALOS_DOM = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.css',
             '.js', '.pdf', '.mp3', '.mp4')


def fetch_goabase():
    url = 'https://www.goabase.net/api/party/json/?limit=500'
    with urllib.request.urlopen(url, timeout=30) as r:
        d = json.load(r)
    return d.get('partylist', [])


_UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                     'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'}


def fetch_html(url, timeout=12):
    """Directo primero (páginas públicas de contacto); si falla, Tor (get_html)."""
    try:
        req = urllib.request.Request(url, headers=_UA)
        return urllib.request.urlopen(req, timeout=timeout).read().decode('utf-8', 'ignore')
    except Exception:
        code = (
            f"import sys; sys.path.insert(0,{str(PROOT)!r}); "
            "from core.http_client import get_html; "
            f"html=get_html({url!r}, timeout={timeout}); "
            "print(html if html else '')"
        )
        try:
            r = subprocess.run(
                [str(PROOT / '.venv/bin/python'), '-c', code],
                capture_output=True, text=True, timeout=timeout + 3)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout
        except Exception:
            pass
        return ''


def emails_de_html(html):
    out = []
    for m in EMAIL_RE.findall(html or ''):
        e = m.strip('. -')
        e = e.lower()
        if any(e.endswith(x) or x in e for x in MALOS_DOM):
            continue
        if e.startswith('e.g.') or e.startswith('your') or e.startswith('example'):
            continue
        if es_email_basura(e):
            continue
        out.append(e)
    return out


def pagina_contacto(html, base):
    cand = []
    for m in re.finditer(r'href=["\']([^"\']+)["\']', html or ''):
        u = m.group(1)
        if any(k in u.lower() for k in ('contact', 'kontakt', '-impressum',
                                        '/impressum', 'booking', 'about',
                                        'info-emails-invitees', 'presse')):
            cand.append(urllib.parse.urljoin(base, u))
    return cand[:2]


def normalizar(s):
    return (s or '').strip().lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--max', type=int, default=500)
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    parties = fetch_goabase()
    print(f'goabase parties: {len(parties)}')
    orgs = {}
    for p in parties:
        org = normalizar((p.get('nameOrganizer') or '').strip())
        url = (p.get('urlOrganizer') or '').strip()
        if org and url and org not in orgs:
            orgs[org] = {'url': url, 'parties': 0}
        if org in orgs:
            orgs[org]['parties'] = orgs[org].get('parties', 0) + 1
    print(f'organizadores con web: {len(orgs)}')

    if OUT.exists():
        prev = json.loads(OUT.read_text(encoding='utf-8'))
    else:
        prev = {}
    nuevas = 0
    prog = 0
    for org, info in sorted(orgs.items(), key=lambda kv: -kv[1].get('parties', 0)):
        if org in prev and prev[org].get('email'):
            continue
        if prog >= args.max:
            break
        prog += 1
        url = info['url']
        html = fetch_html(url)
        if not html:
            continue
        dominio = urllib.parse.urlparse(url).netloc.lower()
        emails = emails_de_html(html)
        contactos = pagina_contacto(html, url) if not emails else []
        pagina = url
        for cu in contactos:
            ch = fetch_html(cu)
            if ch:
                extra = emails_de_html(ch)
                if extra:
                    emails += extra
                    pagina = cu
                    break
            time.sleep(0.4)
        if emails:
            lista = list(dict.fromkeys(emails))
            gmail = [e for e in lista if 'gmail' in e or '.com' not in e.split('@')[0].split('.')[0]]
            mejor = next((e for e in lista if dominio.split(':')[0] in e), None)
            if not mejor:
                mejor = lista[0]
            prev[org] = {'url': url, 'email': mejor, 'pagina': pagina,
                         'n_emails': len(lista), 'parties': info['parties']}
            nuevas += 1
            print(f'  + {org[:34]:36} → {mejor}')
        else:
            prev.setdefault(org, {'url': url, 'email': None})
        time.sleep(0.5)
        if args.dry and prog >= 3:
            break

    OUT.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding='utf-8')
    con = sum(1 for v in prev.values() if v.get('email'))
    print(f'\ncon email (acumulado): {con} | nuevos ahora: {nuevas}')

    if args.apply:
        pares = {k: v['email'] for k, v in prev.items() if v.get('email')}
        n = 0
        with open(PROOT / 'eventos_encontrados.csv', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
            fn = csv.DictReader(f).fieldnames if False else None
        with __import__('core.csv_lock', fromlist=['csv_locked_rows']).csv_locked_rows(
                str(PROOT / 'eventos_encontrados.csv')) as (todas, fieldnames):
            for r in todas:
                if (r.get('email') or '').strip():
                    continue
                o = normalizar(r.get('organizador'))
                if o in pares:
                    r['email'] = pares[o]
                    n += 1
        print(f'// apply: {n} filas rellenadas')


if __name__ == '__main__':
    main()