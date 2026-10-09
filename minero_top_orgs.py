#!/usr/bin/env python3
"""Minero BATCH de emails por organizador (fuentes verificadas + top orgs del CSV).

Modos:
  --fuente goabase   cola = organizadores de goabase + eventbrite (verificados)
  --fuente csv-top   cola = TOP N organizadores del CSV sin email (ordenados por nº
                     de filas), menos basura de slug y menos los ya intentados
                     por el loop (sin duplicar DDG).

Minado de alta precisión:
  1. DDG -> sitio oficial del organizador (validamos título/url contra tokens del org)
  2. crawl homepage + /contact + /booking + /about
  3. emails relevantes: dominio del sitio == dominio del email  (on-site, fuerte)
                        o token del org presente en el email     (relación)
  4. free-mail solo si el local-part refiere al org

Aplicación (--apply): rellena SOLO filas sin email cuyo organizador coincide,
re-validando relevancia. Nunca pisa ni borra. Múltiplo por filas del org.
"""
import argparse
import csv
import json
import re
import sys
import threading
import time
import unicodedata
import urllib.request
import urllib.parse
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
_SKIPURL = re.compile(r'(facebook|instagram|twitter|tiktok|youtube|soundcloud|spotify|'
                      r'wikipedia|imdb|linkedin|eventbrite|lu\.ma|ra\.co|residentadvisor|'
                      r'goabase|partyflock|bandsintown|songkick|linktr|beacons|tripadvisor|'
                      r'yelp|discogs|mixcloud|beatport|resident)\.', re.I)
_PADRES = re.compile(r'\b(image|static|webmaster|noreply|no-reply|example|support@example|'
                     r'orders@|charity@|ebhelp@|abuse@|security@|unsubscribe|optout|list@|'
                     r'press@eventbrite|noresponse|automated|do-not-reply|donotreply)\b', re.I)
free_mail = re.compile(r'@(gmail|hotmail|outlook|yahoo|live|gmx|mail|aol)\.')

# slugs genéricos que NO son promoters (basura de dork/venue)
GARB = {'explore', 'comida', 'compras', 'airports', 'location', 'today', 'events',
        'online', 'tickets', 'entradas', 'bilhetes', 'fiesta', 'concierto', 'gratis',
        'free', 'festival', 'techno', 'trance', 'rave', 'party', 'parties', 'musica',
        'hangout', 'meetup', 'other', 'misc', 'miscelaneos', 'eventstoday', 'khalti',
        'promotion', 'promo', 'event', 'agenda', 'colecionar', 'arquivo', 'prueba',
        'test', 'psytrance', 'outlook', 'konferencia', 'congreso', 'kongress', 'kongresse', 'congress', 'heute',
        'entradasgratuitas', 'gratuito', 'bono', 'voucher', 'descuentos', 'ofertas'}


def norm(s):
    s = (s or '').lower()
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', '', s)


def _tokens_org(org):
    s = (org or '').lower()
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    return [t for t in re.findall(r'[a-z0-9]{3,}', s)
            if t not in ('the', 'and', 'official', 'officiall', 'club', 'events',
                         'presenta', 'presents', 'live', 'night', 'presents')]


def _relevante(org, email, url=''):
    """¿Este email puede pertenecer a este organizador?"""
    e = (email or '').lower()
    if not e or e.count('@') != 1 or len(e) > 60:
        return False
    if es_email_basura(e) or _PADRES.search(e):
        return False
    # on-site fuerte: dominio del sitio == dominio del email (o subdominio)
    if url:
        try:
            host = urllib.parse.urlparse(url).netloc.lower().lstrip('www.')
        except Exception:
            host = ''
        edom = e.split('@')[1]
        if host and edom and (edom == host or host.endswith('.' + edom) or edom.endswith('.' + host)):
            return True
    # token del org en el email
    toks = _tokens_org(org)
    if not toks:
        return False
    for t in toks:
        if len(t) >= 4 and t in e:
            return True
        if t in [e.split('@')[1].split('.')[0]] + e.split('@')[1].split('.')[:-1]:
            return True
    # free-mail: exigir local-part refiera al org
    if free_mail.search(e):
        lp = e.split('@')[0]
        on = norm(org)
        return bool(lp and (lp in on or (len(on) >= 8 and on in lp)))
    return False


def _email_valido(e):
    e = urllib.parse.unquote(e or '')
    return bool(e) and e.count('@') == 1 and not es_email_basura(e) and not _PADRES.search(e)


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
    return list(dict.fromkeys(out))


def _sitio_del_org(org, toks, url, html):
    """Valida que el sitio SÍ pertenece al org (tokens en título/url/host)."""
    blob = (url or '').lower()
    try:
        blob += ' ' + urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        pass
    m = re.search(r'<title[^>]*>(.*?)</title>', html or '', re.S | re.I)
    if m:
        blob += ' ' + re.sub(r'<[^>]+>', '', m.group(1)).lower()[:300]
    m2 = re.search(r'og:site_name"\s+content="([^"]+)"', html or '', re.I)
    if m2:
        blob += ' ' + m2.group(1).lower()
    return any(t in blob for t in toks if len(t) >= 4)


def minar_org(org, extra_queries=''):
    toks = _tokens_org(org)
    if not toks:
        return ''
    queries = [f'"{org}" official website contact email',
               f'"{org}" booking contact email {extra_queries}'.strip()]
    for q in queries:
        try:
            res = ddg_search(q, timeout=22)
        except Exception:
            continue
        for r in (res.get('results') or [])[:5]:
            u0 = (r.get('url') or '')
            if not u0 or _SKIPURL.search(u0):
                continue
            h = _fetch(u0)
            if not h or not _sitio_del_org(org, toks, u0, h):
                continue
            candidatos = [e for e in set(_emails_html(h)) if _relevante(org, e, u0)]
            if not candidatos:
                pu = urllib.parse.urlparse(u0)
                base = f'{pu.scheme}://{pu.netloc}'
                for path in ('/contact', '/booking', '/about'):
                    h2 = _fetch(base + path, timeout=10)
                    if h2:
                        candidatos += [e for e in set(_emails_html(h2))
                                       if _relevante(org, e, u0)]
            if candidatos:
                libres = [e for e in candidatos if not free_mail.search(e)]
                return (libres or candidatos)[0]
    return ''


def _garbage(org):
    n = norm(org)
    if len(n) < 6 or n in GARB:
        return True
    if org.startswith('http') or ' - facebook' in (org or '').lower():
        return True
    if re.fullmatch(r'[\d\s\W]+', org or ''):
        return True
    # org terminado en país = descriptor de lugar, no promoter
    PAISES = {'united', 'kingdom', 'netherlands', 'germany', 'spain', 'france',
              'italy', 'portugal', 'england', 'scotland', 'ireland', 'europe',
              'states', 'america', 'canada', 'austria', 'belgium', 'poland',
              'czech', 'republic', 'switzerland', 'denmark', 'sweden', 'norway',
              'hungary', 'greece', 'croatia', 'romania', 'bulgaria', 'mexico',
              'brazil', 'argentina', 'chile', 'colombia', 'facebook'}
    ult = re.findall(r'[a-z]+', (org or '').lower())
    if ult and ult[-1] in PAISES:
        return True
    return False


def cola_csv_top(tope, excluir_loop=True):
    """TOP organizadores del CSV sin email, por nº de filas (multi-fila)."""
    from collections import Counter
    rows = list(csv.DictReader(open(PROOT / 'eventos_encontrados.csv', encoding='utf-8')))
    vacio = lambda x: (x or '').strip() in ('', 'N/A', '-')
    intentados = set()
    if excluir_loop:
        try:
            cp = json.loads((PROOT / 'loop_completar_checkpoint.json').read_text(encoding='utf-8'))
            intentados = set(norm(k) for k in (cp.get('org_email_pendientes') or {}))
        except Exception:
            pass
    try:
        prev = json.loads(OUT.read_text(encoding='utf-8'))
        ya = set(prev)  # excluye intentados (con y sin email) para no repetir
    except Exception:
        ya = set()
    c = Counter()
    hist = {}
    for r in rows:
        if not vacio(r.get('email')) or vacio(r.get('organizador')):
            continue
        o = r['organizador'].strip()
        k = norm(o)
        if _garbage(o) or k in intentados or k in ya:
            continue
        c[k] += 1
        hist.setdefault(k, o)
    orden = c.most_common(tope)
    return [(hist[k], n) for k, n in orden]


def cola_goabase():
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
    return [(v, 1) for v in orgs.values()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fuente', default='csv-top', choices=['csv-top', 'goabase'])
    ap.add_argument('--tope', type=int, default=250)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--incluir-fallidos', action='store_true',
                    help='incluye orgs ya intentados por el loop (los falló con searx caído)')
    args = ap.parse_args()

    if args.apply:
        return apply()

    prev = {}
    if OUT.exists():
        try:
            prev = json.loads(OUT.read_text(encoding='utf-8'))
        except Exception:
            prev = {}

    cola = (cola_csv_top(args.tope, excluir_loop=not args.incluir_fallidos)
            if args.fuente == 'csv-top' else cola_goabase())
    print(f'cola "{args.fuente}": {len(cola)} orgs (filas cubiertas {sum(n for _, n in cola)})')
    lock = threading.Lock()
    n_ok = n_vac = 0
    t0 = time.time()

    def tarea(org, nfilas):
        nonlocal n_ok, n_vac
        try:
            e = minar_org(org)
        except Exception:
            e = ''
        with lock:
            prev[norm(org)] = {'org': org, 'n': nfilas, 'email': e,
                               't': time.strftime('%H:%M:%S')}
            if e:
                n_ok += 1
            else:
                n_vac += 1
            if (n_ok + n_vac) % 10 == 0:
                OUT.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding='utf-8')
                print(f'  … {n_ok+n_vac}/{len(cola)} | con email {n_ok} | '
                      f'{time.time()-t0:.0f}s', flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(tarea, org, n) for org, n in cola]
        for f in futs:
            f.result()
    OUT.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'FIN: con email {n_ok} | vacíos {n_vac} | {time.time()-t0:.0f}s')


def apply():
    from core.csv_lock import csv_locked_rows
    prev = {}
    try:
        prev = json.loads(OUT.read_text(encoding='utf-8'))
    except Exception:
        pass
    tabla = {k: v['email'] for k, v in prev.items()
             if v.get('email') and _email_valido(v['email'])}
    print(f'emails minados aplicables: {len(tabla)}')
    n = 0
    por = {}
    with csv_locked_rows(str(PROOT / 'eventos_encontrados.csv')) as (todas, fn):
        for r in todas:
            if (r.get('email') or '').strip():
                continue
            k = norm(r.get('organizador') or '')
            e = tabla.get(k)
            if e and _relevante(r.get('organizador'), e):
                r['email'] = e
                n += 1
                por[k] = por.get(k, 0) + 1
    print(f'APLICADO: {n} celdas (multi-fila por org)')
    for k, c in sorted(por.items(), key=lambda x: -x[1])[:10]:
        print(f'  {tabla.get(k, "?"):40} x{c}  ({prev.get(k, {}).get("org", k)[:24]})')


if __name__ == '__main__':
    main()