#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Loop de bajada y completado de eventos.

Procesa eventos sin email / sin organizador:
  1. Lee CSV y extrae los eventos faltantes
  2. Para RA: busca promoters via DDG dorks + websites
  3. Para FB/IG: busca organizador via snippets/dorks
  4. Escribe resultados al CSV
"""
import csv
import json
import re
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from serp_worker import search as ddg_search
from core.emails_guard import es_email_basura

def fetch_hard(url, timeout=12):
    """Fetch con timeout HARD via subprocess + SIGKILL (curl_cffi+Tor)."""
    try:
        import subprocess
        code = (
            f"import sys; sys.path.insert(0,{_PROJECT_ROOT!r}); "
            "from core.http_client import get_html; "
            f"html=get_html({url!r}, timeout={timeout}); "
            "print(html if html else '')"
        )
        r = subprocess.run(
            [str(Path(_PROJECT_ROOT) / '.venv/bin/python'), '-c', code],
            capture_output=True, text=True, timeout=timeout + 3
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
        return None
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None

CSV_FILE = Path(_PROJECT_ROOT) / "eventos_encontrados.csv"
LOG_FILE = Path(_PROJECT_ROOT) / "loop_completar.log"
CHECKPOINT_FILE = Path(_PROJECT_ROOT) / "loop_completar_checkpoint.json"

EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

SPAM_NAME_PAT = re.compile(
    r'(how to|ways to|[\w\s]*tips|kitchen|recipe|delta air|united airline|'
    r'make money|click here|free download|download now|amazon|'
    r'secrets|hacks|best [\w ]+ for|office|airlines|\+1 ?[0-9 ]{9,}|'
    r'customer service|support number)',
    re.I
)

def es_nombre_spam(nombre):
    """True si el nombre del evento parece spam (no psytrance real)."""
    if not nombre:
        return True
    return bool(SPAM_NAME_PAT.search(nombre))


def _dorks_activos():
    """True si algún dork FB/IG está activo en config_modulos.json.

    El frente de org FB (2a/2b) se alimenta de los batches de dorks
    (site:facebook.com/events ...). Con los dorks apagados su yield medido
    es ~0: se pausa y el presupuesto va al frente email (que sí rinde).
    """
    try:
        import json as _json, os as _os
        _p = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                           "config_modulos.json")
        _act = _json.load(open(_p, encoding="utf-8")).get("activos", {})
        return any(_act.get(m, False) for m in
                   ("facebook_dorks", "instagram_dorks", "dorks_resultados"))
    except Exception:
        return True  # sin config no se frena (comportamiento previo)


# Nombres genéricos que NO revelan organizador (no enriquecibles)
GENERIC_ORG_WORDS = {
    'dark', 'psy', 'forest', 'hi-tech', 'suomi', 'goa', 'goatrance',
    'psychill', 'prog', 'progressive', 'darkpsy', 'zenon', 'bashcore',
    'night', 'party', 'rave', 'gathering', 'festival', 'fest', 'feja',
    'openair', 'open', 'air', 'celebration', 'ritual', 'frisson',
    'fullon', 'full', 'psybient', 'ambient', 'trance', 'psychedelic',
    'outdoor', 'indoor', 'day', 'summer', 'winter', 'spring', 'autumn',
    'edition', 'weekend', 'weekender', 'events', 'event',
    'techno', 'acid', 'bass', 'hardcore', 'hard', 'deep', 'proghouse',
    'ceremony', 'celebration', 'gathering', 'meetup', 'reunion',
    'lounge', 'vibe', 'journey', 'experience', 'immersion', 'tribe',
    'meltdown', 'explosion', 'eruption', 'moon', 'sun', 'stars',
    'cosmos', 'galaxy', 'universe', 'infinite', 'infinity', 'eternal',
    'psychedelia', 'psy', ' Goa', 'twilight', 'dusk', 'dawn',
    'core', 'psycore', 'hi', 'happening', 'now',
    'psytrance', 'psydub', 'psybass', 'forestpsy', 'darkforest',
}

def es_nombre_gen_org(nombre):
    """True si el nombre es genérico y no revela un organizador real.

    Método por sustracción: elimina todos los tokens genéricos (substrings,
    para cazar compuestos con guion tipo 'hi-tech'); si no queda nada
    con sustancia → genérico, irresoluble vía dorks.
    """
    if not nombre:
        return True
    n = nombre.strip().lower()
    if len(n) < 5:
        return True
    n = n.replace('\u202f', ' ').replace('\u00a0', ' ')
    n = re.sub(r'[.,:;!?()\"\'’‘“”–—-]+', ' ', n)
    genericos = {w.strip().lower() for w in GENERIC_ORG_WORDS if w.strip()}
    genericos |= {'tech', 'hitech', 'chill', 'on', 'the', 'de', 'la', 'el',
                  'los', 'las', 'in', 'at', 'of', 'a', 'y', 'e', 'und', 'et'}
    tmp = n
    # Coincidencia por palabra completa (\b): los compuestos con guion ya
    # están separados (hi-tech → hi tech) y las formas fusionadas
    # (hitech, fullon, darkpsy) están en el set. Substring devoraba
    # 'at' dentro de 'sat'/'beat' y rompía la detección de fechas.
    for w in sorted(genericos, key=len, reverse=True):
        if len(w) >= 2:
            tmp = re.sub(r'\b' + re.escape(w) + r'\b', ' ', tmp)
    tmp = re.sub(r'[\s\-/&+]+', ' ', tmp).strip()
    # marcadores de volumen/edición sueltos (vol 4, edition 2, #3...)
    tmp = re.sub(r'\b(vol|volume|edition|ed|part|pt|n|no|nr)\.?\s*#?\d*\b', ' ', tmp).strip()
    tmp = re.sub(r'#\d+|\b\d+\b', ' ', tmp).strip()
    tmp = re.sub(r'\s+', ' ', tmp).strip()
    if tmp == '':
        return True
    # fragmentos de fecha/hora como "nombre" (26 2:00 aest sat sep):
    # si solo quedan meses/días/horas/tz → no es un nombre resoluble
    fecha_hora = {
        'jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct',
        'nov', 'dec', 'ene', 'abr', 'ago', 'dic', 'janv', 'fevr', 'mars',
        'avr', 'mai', 'juin', 'juil', 'aout', 'sept', 'octo', 'nove', 'dece',
        'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday',
        'sunday', 'mon', 'tue', 'tues', 'wed', 'thu', 'thur', 'fri', 'sat',
        'sun', 'lunes', 'martes', 'miercoles', 'jueves', 'viernes',
        'sabado', 'domingo', 'lun', 'mar', 'mie', 'jue', 'vie', 'sab', 'dom',
        'lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi',
        'dimanche', 'cet', 'cest', 'aest', 'pst', 'est', 'gmt', 'utc',
        'pm', 'am', 'pst', 'pdt', 'edt', 'bst', 'ist',
    }
    toks = [t.strip(':.,') for t in tmp.split(' ') if t.strip(':.,')]
    if toks and all(t in fecha_hora or re.fullmatch(r'\d{1,2}(:\d{2})?', t) for t in toks):
        return True
    return False

GENERIC_EMAILS = {
    'support@', 'info@', 'noreply@', 'no-reply@', 'admin@',
    'webmaster@', 'hostmaster@', 'postmaster@', 'abuse@',
    'spam@', 'hello@', 'contact@', 'marketing@', 'press@',
    'office@', 'team@', 'help@', 'feedback@', 'billing@',
    'your@', 'email@', 'test@', 'example@', 'user@',
    'privacy@', 'tickets@', 'volunteer@', 'subscribe@',
    'promotersupport@',
}

NO_DOMAINS = {
    'w3.org', 'cloudflare.com', 'googleapis.com', 'gstatic.com',
    'sentry.io', 'example.com', 'test.com', 'github.io',
    'wix.com', 'squarespace.com', 'wordpress.com',
}

PLACEHOLDER_LOCAL = {
    'deine', 'dein', 'tu', 'tumail', 'namail', 'name', 'nombre',
    'nom', 'vorname', 'emailadresse', 'mailadresse', 'youremail',
    'ilsregistrieren', 'anmeldung', 'registrierung', 'somebody',
    'isthis', 'who', 'whom', 'or', 'ande', 'insert', 'enters',
    'notreal', 'fakemail', 'fake', 'prueba', 'testmail',
    'john', 'john.doe', 'jane', 'jane.doe', 'jdoe', 'johndoe',
    'janedoe', 'fred', 'flintstone', 'testing', 'unknown',
}

# Dominios de spam / booking no relevantes al organizador de psytrance
NO_RELEVANT_DOMAINS = {
    'delta.com', 'united.com', 'aa.com', 'booking.com', 'expedia.com',
    'airbnb.com', 'amazon.com', 'ebay.com', 'walmart.com', 'uber.com',
    'lyft.com', 'nike.com', 'adidas.com', 'thatericalper.com',
    'verbraucherzentrale.nrw', 'verbraucherzentrale.de',
}
PLACEHOLDER_DOMAINS = {
    'email.de', 'email.com', 'mail.de', 'mail.com', 'gmail.de',
    'hotmail.de', 'web.de', 'example.de', 'test.de', 'domain.de',
    'domain.com', 'yourdomain.com', 'example.org', 'noreply.de',
    'noemail.com', 'fakemail.de', 'fakeemail.com',
    'email.test', 'nacimiento.test', 'provedor.com',
}

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass

# Fuente única de verdad para validez de email: venue_enricher (filtros
# endurecidos: placeholders multi-idioma, técnicos, enmascarados, unicode).
# Se importa con fallback a la implementación local si falla.
try:
    from venue_enricher import es_email_valido as _ve_valido
    def es_email_valido(email):
        if not email:
            return False
        from core.emails_guard import es_email_basura
        if es_email_basura(email):
            return False
        if not _ve_valido(email):
            return False
        e = email.lower()
        domain = e.split('@')[1] if '@' in e else ''
        if domain in NO_RELEVANT_DOMAINS:
            return False
        return True
except Exception:
    def es_email_valido(email):
        """Filtra emails falsos o genéricos (fallback local)."""
        if not email:
            return False
        from core.emails_guard import es_email_basura
        if es_email_basura(email):
            return False
        e = email.lower()
        if any(e.startswith(p) for p in GENERIC_EMAILS):
            return False
        if re.search(r'\.(jpg|jpeg|png|gif|webp|avif|svg|pdf|html|css|js)$', e):
            return False
        if re.search(r'\.(gz|zip|tar|rar|7z|mp3|mp4|wav|ogg)$', e):
            return False
        if re.search(r'^\w{20,}@', e):
            return False
        domain = e.split('@')[1] if '@' in e else ''
        if domain in NO_DOMAINS:
            return False
        if domain in PLACEHOLDER_DOMAINS:
            return False
        if domain in NO_RELEVANT_DOMAINS:
            return False
        local = e.split('@')[0] if '@' in e else ''
        if local in PLACEHOLDER_LOCAL:
            return False
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', e):
            return False
        return True

def cargar_eventos_sin_email():
    """Carga eventos sin email del CSV."""
    with open(CSV_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    sin_email = []
    for r in rows:
        if not r.get('email', '').strip() or not es_email_valido(r.get('email', '')):
            sin_email.append(r)
    return sin_email

def cargar_eventos_sin_org():
    """Carga eventos sin organizador del CSV."""
    with open(CSV_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    sin_org = []
    for r in rows:
        org = r.get('organizador', '').strip()
        if not org or org == 'N/A':
            sin_org.append(r)
    return sin_org


_FB_SNIPPET_PAT = re.compile(
    r'\bby\s+(?P<org>[A-ZÀ-ÿ0-9][^\s][^.]*?)\s+'
    r'ond?\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|'
    r'Mon|Tue|Tues|Wed|Thu|Thur|Fri|Sat|Sun)',
    re.I)
_FB_SNIPPET_PAT2 = re.compile(
    r'\bby\s+(?P<org>[A-ZÀ-ÿ0-9][^\s][^.]*?)\s+'
    r'(?:at|with)\s', re.I)
_FB_ORGANIZADOR_COADJUNTOS = re.compile(r'\s+(?:and|&|,)\s+.*$')


def _limpiar_org_fb(org):
    """Limpia un organizador extraído de snippet FB ('by X on' / 'X and Y')."""
    import html as _html
    org = _html.unescape(org or '')
    org = _FB_ORGANIZADOR_COADJUNTOS.sub('', org)          # 'X and Y' → 'X'
    org = re.split(r'\s+&\s+', org)[0].strip()             # 'X & Y' → 'X'
    org = re.sub(r'\s*@\S+', '', org)                      # quita @menciones
    org = re.sub(r'[\\/|]', ' ', org)                      # barras no
    org = re.sub(r'\s+(?:on|at|in|with|de|el|la|los|las)\s+.*$', '', org, flags=re.I)
    org = re.sub(r'\s*[-–]\s*.*$', '', org)                # 'X - Ciudad' → 'X'
    org = re.sub(r'\b(?:2|others?|people?|interested|going|posted?|post(s)?)\b', ' ', org, flags=re.I)
    org = re.sub(r'\s+', ' ', org).strip(' ,.:;-')
    if not org or len(org) < 3 or len(org) > 50 or len(org.split()) > 5:
        return ''
    low = org.lower()
    if any(w in low for w in ('store', 'shop', 'market', 'marketplace',
                              'food', 'facebook', '(dorks)', 'slug')):
        return ''
    if low in ('explore', 'music', 'party', 'parties', 'rave', 'event', 'events',
               'facebook', 'instagram', 'n/a', 'na', 'promoter', 'organizer'):
        return ''
    return org


def _normalizar_link_fb(url):
    """Normaliza un link FB a clave estable (sin query/fragmento, lowercase)."""
    url = (url or '').lower().split('?')[0].split('#')[0].rstrip('/')
    return url


_FB_EVENT_URL = re.compile(
    r'https?://(?:www|m|mbasic)\.facebook\.com/events/[A-Za-z0-9._%+\-]+(?:/[A-Za-z0-9._%+\-]+)*',
    re.I)


def _org_desde_texto(texto):
    """Extrae organizador de un snippet/mensaje ('by X on', 'presented by X')."""
    t = (texto or '')[:400]
    for m in _FB_SNIPPET_PAT.finditer(t):
        o = _limpiar_org_fb(m.group('org'))
        if o:
            return o
    for pat in (r'(?:presented by|organized by|organizado por|hosted by)[:,\s]+'
                r'([A-ZÀ-ÿ][\w\s&.-]{2,40}?)(?=\s*[,.\n]|$)',
                r'([A-ZÀ-ÿ][\w\s&.-]{2,30}?)\s+presents'):
        m = re.search(pat, t, re.I)
        if m:
            o = _limpiar_org_fb(m.group(1))
            if o:
                return o
    return ''


def minar_organizadores_telegram(ciudades, max_por_ciclo=1):
    """Vector Telegram (canales públicos): descubre canales por ciudad via DDG,
    crawlea t.me/s/<canal> (+1 página 'before=') y extrae organizador por mensaje:
      1) patrón 'by X on'/'presented by X' en el texto (canales)
      2) autor del mensaje si NO es el propio canal (grupos → el que postea suele
         ser el promoter).
    Devuelve {link_normalizado: organizador}.
    """
    from core.http_client import crear_sesion_tor
    sesion = None
    mapa = {}
    for ciudad in ciudades[:max_por_ciclo]:
        canales = []
        try:
            for dork in (f'site:t.me {ciudad} psy trance events OR parties',
                         f'site:t.me {ciudad} psytrance rave'):
                res = ddg_search(dork, timeout=20)
                for r in res.get('results', []):
                    url = r.get('url', '') or ''
                    m = re.search(r't\.me/(?:s/)?([A-Za-z0-9_]{4,40})', url)
                    if m and m.group(1).lower() not in ('joinchat', 'youtube', 'telegram'):
                        canales.append(m.group(1))
        except Exception:
            pass
        for ch in list(dict.fromkeys(canales))[:4]:
            paginas = []
            try:
                if sesion is None:
                    sesion = crear_sesion_tor()
                html = sesion.get(f'https://t.me/s/{ch}', timeout=30).text
                paginas.append(html)
                m = re.search(r'data-post="[^"]+/(\d+)"', html)
                if m:
                    paginas.append(sesion.get(f'https://t.me/s/{ch}?before={m.group(1)}',
                                              timeout=30).text)
            except Exception:
                continue
            for html in paginas:
                for b in re.split(r'data-post="', html)[1:]:
                    texto = ''
                    mtx = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', b, re.S)
                    if mtx:
                        texto = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', mtx.group(1)))
                    for link in _FB_EVENT_URL.findall(texto):
                        org = _org_desde_texto(texto)
                        if not org:
                            ma = re.search(
                                r'tgme_widget_message_author[^>]*>\s*<a[^>]+href="(https://t\.me/[^"]+)"[^>]*>\s*<span[^>]*>([^<]+)</span>',
                                b)
                            if ma and ma.group(2) and ma.group(1) != f'https://t.me/{ch}':
                                org = _limpiar_org_fb(ma.group(2))
                        if org:
                            mapa.setdefault(_normalizar_link_fb(link), org)
    return mapa


def _aplicar_mapa_org(mapa, solo_vacios=True):
    """Aplica {link_normalizado: org} al CSV bajo lock. Devuelve ganado."""
    if not mapa:
        return 0
    from core.csv_lock import csv_locked_rows
    ganado = 0
    with csv_locked_rows(CSV_FILE) as (todas, fieldnames):
        for r in todas:
            if 'Facebook' not in r.get('fuente', ''):
                continue
            org_act = (r.get('organizador', '') or '').strip()
            if org_act and org_act.lower() != 'n/a':
                if solo_vacios or not es_org_slugderivado(org_act):
                    continue
            org = mapa.get(_normalizar_link_fb(r.get('link', '') or ''))
            if org and org.lower() != org_act.lower():
                r['organizador'] = org
                r['tipo_organizador'] = tipo_organizador(org)
                ganado += 1
    return ganado


_GOABASE_EMAILS = None


def _goabase_email_para_org(org):
    """Email de organizador ya minado vía goabase (JSON, sin red)."""
    global _GOABASE_EMAILS
    if _GOABASE_EMAILS is None:
        try:
            with open(_PROJECT_ROOT + '/goabase_org_emails.json', encoding='utf-8') as _f:
                _GOABASE_EMAILS = json.load(_f)
        except Exception:
            _GOABASE_EMAILS = {}
    v = _GOABASE_EMAILS.get((org or '').strip().lower())
    return (v or {}).get('email') if isinstance(v, dict) else ''


_MAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')


def _emails_en_html(html):
    out = []
    for m in _MAIL_RE.findall(html or ''):
        e = m.strip('.-').lower()
        if len(e) > 60:
            continue
        if e.startswith(('your', 'example', 'e.g.', 'someone', 'user@', 'name@')):
            continue
        if re.search(r'\.(png|jpg|jpeg|gif|webp|svg|css|js|pdf)$', e):
            continue
        if es_email_basura(e):
            continue
        out.append(e)
    return out


def _fetch_pagina(url, timeout=12):
    """Directo primero; si falla, Tor (fetch_hard)."""
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        return urllib.request.urlopen(req, timeout=timeout).read().decode('utf-8', 'ignore')
    except Exception:
        try:
            return fetch_hard(url, timeout=timeout) or ''
        except Exception:
            return ''


def minar_email_organizador(org, lugar):
    """Rama A: DDG→web→email para un organizador/promoter. Reutiliza el
    buscador de email por query (snippets + fetch de páginas)."""
    org = (org or '').strip()
    if not org or _es_org_placeholder(org):
        return ''
    lugar = (lugar or '').strip()
    # Fuente (1): organizador ya minado vía goabase (web del org)
    geo = _goabase_email_para_org(org)
    if geo and es_email_valido(geo):
        return geo
    queries = [
        f'"{org}" {lugar} email contact',
        f'"{org}" psytrance promoter email booking',
        f'"{org}" {lugar} contact',
    ]
    emails = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futuros = [pool.submit(_buscar_email_una_query, org, lugar, q) for q in queries]
        for f in futuros:
            try:
                emails.extend(f.result(timeout=35))
            except Exception:
                pass
    if emails:
        return _dedup_emails(emails)[:1][0]
    # Fuente (2): web del organizador → homepage/contacto (emails directos)
    try:
        res = ddg_search(f'"{org}" official site OR homepage OR "official website"', timeout=20)
        skipd = re.compile(r'(facebook|instagram|twitter|tiktok|youtube|soundcloud|spotify|'
                           r'wikipedia|imdb|linkedin|yelp|pinterest|goabase|partyflock|'
                           r'residentadvisor)\.', re.I)
        for r in (res.get('results') or [])[:6]:
            u0 = (r.get('url') or '')
            if not u0 or skipd.search(u0):
                continue
            html = _fetch_pagina(u0)
            if html:
                got = _dedup_emails(_emails_en_html(html))
                if got:
                    return got[0]
                break
    except Exception:
        pass
    return ''


_PLACEHOLDER_ORGS = {
    'john doe', 'jane doe', 'anon', 'anonymous', 'n/a', 'tba', 'tbd',
    'unknown', 'organizer', 'promoter', 'ticket', 'event',
    # sustantivos genéricos que NO son promotores concretos
    'events', 'festivals', 'festival', 'concerts', 'parties', 'raves',
    'music', 'underground', 'psytrance', 'trance', 'booking', 'dj',
    'party', 'fest', 'nights', 'night',
}


def _es_org_placeholder(org):
    o = (org or '').strip().lower()
    if o in _PLACEHOLDER_ORGS:
        return True
    if '/' in o or '\\' in o:   # subreddits/grupos/URLs, no promotores
        return True
    return False


def tipo_organizador(org):
    """Clasifica: 'promoter' (SERP/metrics/RA/Telegram), 'venue' (slug), '' (vacío)."""
    o = (org or '').strip()
    if not o or o.lower() == 'n/a':
        return ''
    if es_org_slugderivado(o):
        return 'venue'
    return 'promoter'


def _aplicar_email_organizador(org, email):
    """Aplica un email encontrado a TODOS los eventos del mismo organizador
    que aún no tengan email (bajo lock)."""
    from core.csv_lock import csv_locked_rows
    org = (org or '').strip().lower()
    if not org or _es_org_placeholder(org) or not es_email_valido(email):
        return 0
    ganado = 0
    with csv_locked_rows(CSV_FILE) as (todas, fieldnames):
        for r in todas:
            if (r.get('email', '') or '').strip():
                continue
            if (r.get('organizador', '') or '').strip().lower() != org:
                continue
            if es_email_valido(email):
                r['email'] = email
                ganado += 1
    return ganado


def es_org_slugderivado(org):
    """¿Org parece derivado de un slug de URL (email 'Ph Hs', 'Cuu Te')?
    Corto, TitleCase, cada token ≤ 6 letras. Se puede sobrescribir con el
    organizador real extraído del snippet de la propia página del evento."""
    o = (org or '').strip()
    if not o:
        return False
    toks = o.split()
    if not (1 <= len(toks) <= 3):
        return False
    if not (len(o) <= 16):
        return False
    for t in toks:
        if not re.fullmatch(r'[A-ZÀ-ÿ][a-zA-Z0-9À-ÿ]{0,5}', t):
            return False
    return True


def _serp_eventos(motor, dork, timeout=22):
    """Consulta el motor indicado y devuelve dict {results:[{url,titulo,snippet}]}.
    - 'ddg': proceso hijo serp_worker (DuckDuckGo html).
    - 'bing'/'yandex': searxng local (docker) vía Tor — indexan FB
      que DDG no toca (URLs events/<slug>/<subslug> e IDs numéricos).
    """
    if motor == 'ddg':
        return ddg_search(dork, timeout=timeout)
    try:
        import urllib.request as _ur
        q = urllib.parse.quote(dork)
        u = (f'http://localhost:8888/search?q={q}&format=json'
             f'&engines={motor}')
        req = _ur.Request(u, headers={'User-Agent': 'Mozilla/5.0'})
        d = json.loads(_ur.urlopen(req, timeout=timeout).read())
        out = []
        for x in d.get('results', []):
            out.append({
                'url': x.get('url', '') or '',
                'titulo': x.get('title', '') or '',
                'snippet': x.get('content', '') or '',
            })
        return {'status': 1, 'results': out}
    except Exception:
        return {'status': 0, 'results': []}


def minar_organizadores_fb_serp(ciudades, anios=None, subgeneros=None, max_por_ciclo=2):
    """Barrido SERP por ciudad: dork 'site:facebook.com/events <ciudad> <subg> <año>'
    y extrae organizador del snippet 'Event in X by ORGANIZER on <día>'.

    subgeneros = sinónimos originales del dork matriz ('dark psy', 'goa trance'...).
    Devuelve {link_normalizado: organizador} con match por URL exacta.
    """
    import html as _html
    anios = anios or []
    subgeneros = subgeneros or []
    resultados = {}
    for ciudad in ciudades[:max_por_ciclo]:
        dorks = []
        if anios:
            for a in anios[:2]:
                if subgeneros:
                    for sg in subgeneros[:3]:
                        dorks.append(f'site:facebook.com/events {ciudad} {sg} {a}')
                        dorks.append(f'site:facebook.com/events {ciudad} {sg} party {a}')
                dorks.append(f'site:facebook.com/events {ciudad} psy trance {a}')
                dorks.append(f'site:facebook.com/events {ciudad} psy trance party {a}')
        dorks.append(f'site:facebook.com/events {ciudad} psy trance')
        dorks.append(f'site:facebook.com/events {ciudad} trance')
        for dork in list(dict.fromkeys(dorks)):
            consultas = [('ddg', dork)]
            if not (dork.endswith(' psy trance') or dork.endswith(' trance')):
                consultas.append(('yandex', dork))
            for _motor, _d in consultas:
                try:
                    res = _serp_eventos(_motor, _d, timeout=22)
                except Exception:
                    continue
                for r in res.get('results', []):
                    url = _normalizar_link_fb(r.get('url', '') or '')
                    if '/events' not in url:
                        continue
                    sn = _html.unescape(r.get('snippet', '') or '')
                    org = ''
                    m = _FB_SNIPPET_PAT.search(sn) or _FB_SNIPPET_PAT2.search(sn)
                    if m:
                        org = _limpiar_org_fb(m.group('org'))
                    if not org:
                        # fallback: título 'X - La Casa de' con '- Facebook' fuera
                        tit = _html.unescape(r.get('titulo', '') or '')
                        tit = re.sub(r'\s*-\s*Facebook\s*$', '', tit, flags=re.I).strip()
                        org = _limpiar_org_fb(tit)
                        if not org or org.lower() in ('facebook',):
                            # bing/yandex indexan events/<org_slug>/<subslug>: el primer
                            # segmento es la página del organizador (p.ej. void-berlin).
                            _pm = re.match(r'facebook\.com/events/([^/?#]{3,})/', url.lower())
                            if _pm and not _pm.group(1).split('-')[-1].isdigit():
                                _slug_org_name = _pm.group(1).replace('-', ' ').strip()
                                org = _limpiar_org_fb(_slug_org_name.title())
                        if org:
                            resultados[url] = org
                time.sleep(0.6)
                if len(resultados) >= 40:
                    break
            if len(resultados) >= 40:
                break
    return resultados

def _buscar_email_una_query(nombre, lugar, q):
    """Ejecuta una query DDG y extrae emails de resultados + páginas."""
    emails = []
    try:
        if len(q) > 80:
            q = q[:80]
        result = ddg_search(q, timeout=20)
        for r in result.get('results', []):
            texto = f"{r.get('titulo','')} {r.get('snippet','')}"
            for e in EMAIL_REGEX.findall(texto):
                if es_email_valido(e):
                    emails.append(e)
            # Intentar fetch de página
            url = r.get('url', '')
            if url and not any(s in url for s in ['facebook', 'instagram', 'twitter', 'reddit', 'youtube', 'tiktok']):
                html = fetch_hard(url, timeout=10)
                if html:
                    for e in EMAIL_REGEX.findall(html):
                        if es_email_valido(e):
                            emails.append(e)
    except Exception:
        pass
    return emails

def _dedup_emails(emails):
    seen = set()
    unique = []
    for e in emails:
        if e.lower() not in seen:
            seen.add(e.lower())
            unique.append(e)
    return unique

def buscar_email_para_evento(evento):
    """Busca email del organizador para un evento vía DDG (queries en paralelo)."""
    nombre = evento.get('nombre', '')
    lugar = evento.get('lugar', '')
    
    queries = [
        f'"{nombre}" email contact',
        f'"{nombre}" {lugar} email booking',
        f'{nombre} psytrance promoter email',
    ]
    
    # Correr las 3 queries en paralelo
    emails_concurrentes = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futuros = [pool.submit(_buscar_email_una_query, nombre, lugar, q) for q in queries]
        for f in futuros:
            try:
                emails_concurrentes.extend(f.result(timeout=30))
            except Exception:
                pass
    
    for e in _dedup_emails(emails_concurrentes):
        if es_email_valido(e):
            return e
    return ''

def buscar_org_para_evento(evento):
    """Busca organizador para un evento via DDG."""
    nombre = evento.get('nombre', '')
    lugar = evento.get('lugar', '')

    queries = [
        f'"{nombre}" organizer OR promoter OR "presented by"',
        f'"{nombre}" "organizado por" OR "presented by"',
        f'"{nombre}" {lugar} party',
    ]

    _FB_NO = ('events', 'pages', 'groups', 'watch', 'reel', 'reels', 'photo',
              'photos', 'video', 'videos', 'profile', 'public', 'people',
              'hashtag', 'marketplace', 'gaming', 'live', 'story')
    for q in queries:
        if len(q) > 90:
            q = q[:90]
        try:
            result = ddg_search(q, timeout=20)
            for r in result.get('results', []):
                url = r.get('url', '') or ''
                texto = f"{r.get('titulo','')} {r.get('snippet','')}"
                # 1. URL de página FB host (no /events/) → la página es el organizador
                m = re.search(r'facebook\.com/([A-Za-z0-9._-]+)(?:[/?#]|$)', url)
                if m:
                    slug = m.group(1).lower()
                    if slug not in _FB_NO and len(slug) >= 4 and not slug[0].isdigit():
                        org = re.sub(r'[._-]+', ' ', slug).strip().title()
                        if 3 <= len(org) <= 45:
                            return org
                # 2. Partyflock organisation → nombre en la URL
                m = re.search(r'partyflock\.nl/organisation/\d+:([^/?#]+)', url, re.I)
                if m:
                    org = re.sub(r'[-_]+', ' ', m.group(1)).strip().title()
                    if 3 <= len(org) <= 45:
                        return org
                # 3. Patrones de organizador en título/snippet
                patterns = [
                    r'(?:presented by|organized by|organizado por|hosted by)[:,\s]+([A-Z][\w\s&.-]{2,40}?)(?=\s*[,.\n]|$)',
                    r'([A-Z][\w\s&.-]{2,30}?)\s+(?:presents|presenta)',
                    r'(?:by|por)\s+@?([A-Z][\w\s&.-]{2,30}?)(?=\s*[,.\n]|$)',
                ]
                for pat in patterns:
                    m = re.search(pat, texto, re.I)
                    if m:
                        org = m.group(1).strip()
                        org = re.sub(r'\s+', ' ', org)
                        # Recortar coletillas: "X on Thursday" / "X at Venue" → "X"
                        org = re.sub(r'\s+(on|at|in|for|with|from|de|el|la|los|las)\s+.*$', '', org, flags=re.I).strip()
                        if 3 <= len(org) <= 45 and len(org.split()) <= 4 and org.lower() not in ('event', 'events', 'loading', 'facebook', 'instagram', 'skip', 'see', 'more'):
                            return org
        except Exception:
            pass
    return ''

def _procesar_un_evento(ev, tipo):
    """Procesa un solo evento (email u org). Devuelve (key, cambio) o (key, None)."""
    key = ev.get('link', '') or f"{ev.get('nombre','')}|{ev.get('fecha','')}"
    
    if es_nombre_spam(ev.get('nombre', '')):
        log(f"  ⏭️ Spam, saltando: {ev.get('nombre','')[:40]}")
        return key, None
    
    if tipo == 'email':
        email = buscar_email_para_evento(ev)
        if email:
            log(f"  ✅ Email: {ev.get('nombre','')[:40]} → {email}")
            return key, {'email': email}
        else:
            log(f"  ⚠️ Sin email: {ev.get('nombre','')[:40]}")
            return key, None
    
    elif tipo == 'org':
        org = buscar_org_para_evento(ev)
        if org:
            log(f"  ✅ Org: {ev.get('nombre','')[:40]} → {org}")
            return key, {'organizador': org}
        else:
            log(f"  ⚠️ Sin org: {ev.get('nombre','')[:40]}")
            return key, None
    
    return key, None

def procesar_batch(eventos, tipo, max_procesar=5, offset=0):
    """Procesa un batch de eventos en paralelo (3 workers).
    
    offset rota la ventana para no procesar siempre los mismos primeros
    (inanición del resto cuando nadie convierte y la lista no se achica).
    """
    resultados = {}
    
    n = len(eventos)
    if n == 0:
        return resultados
    off = offset % n
    ventana = (eventos[off:] + eventos[:off])[:max_procesar]
    
    with ThreadPoolExecutor(max_workers=12) as pool:
        futuros = {
            pool.submit(_procesar_un_evento, ev, tipo): ev
            for ev in ventana
        }
        for f in futuros:
            try:
                key, cambio = f.result(timeout=180)
                if cambio:
                    resultados[key] = cambio
            except Exception:
                pass
    
    return resultados

def aplicar_cambios(cambios, tipo):
    """Aplica cambios al CSV (bajo lock exclusivo: ver core/csv_lock)."""
    from core.csv_lock import csv_locked_rows
    updated = 0
    with csv_locked_rows(CSV_FILE) as (rows, fieldnames):
        for r in rows:
            key = r.get('link', '') or f"{r.get('nombre','')}|{r.get('fecha','')}"
            if key in cambios:
                for campo, valor in cambios[key].items():
                    r[campo] = valor
                updated += 1

    return updated

def main():
    log("=== Loop de completado iniciado ===")
    
    # Cargar checkpoint
    checkpoint = {}
    if CHECKPOINT_FILE.exists():
        try:
            with open(CHECKPOINT_FILE, 'r') as f:
                checkpoint = json.load(f)
        except Exception:
            pass
    
    iteration = checkpoint.get('iteration', 0)
    BATCH = checkpoint.get('batch', 150)
    PAUSA = checkpoint.get('pausa', 5)
    
    while True:
        iteration += 1
        log(f"=== Iteración {iteration} ===")
        
        # 1. Procesar por bloques de fuente (no cargar) — RA / FB matriz / resto
        sin_email = cargar_eventos_sin_email()
        sin_email_ra = [e for e in sin_email if 'Resident Advisor' in e.get('fuente','')]
        # bloque rotativo: 0=RA, 1=FB matriz, 2=resto (Goabase etc.)
        bloque = iteration % 3
        if bloque == 1:
            sin_email_bloque = [e for e in sin_email if 'Facebook (matriz)' in e.get('fuente','')]
            log(f"Sin email: {len(sin_email)} total, {len(sin_email_ra)} RA — BLOQUE FB matriz ({len(sin_email_bloque)} sin email)")
        elif bloque == 2:
            sin_email_bloque = [e for e in sin_email if e not in sin_email_ra and 'Facebook (matriz)' not in e.get('fuente','')]
            log(f"Sin email: {len(sin_email)} total, {len(sin_email_ra)} RA — BLOQUE resto ({len(sin_email_bloque)} sin email)")
        else:
            sin_email_bloque = sin_email_ra
            log(f"Sin email: {len(sin_email)} total, {len(sin_email_ra)} RA — BLOQUE RA")
        
        # 1b. Cada 5 iteraciones: pase venue-first (buscar email del venue UNA vez
        #     y aplicarlo a todos sus eventos RA sin email).
        if sin_email_ra and iteration % 5 == 0:
            try:
                import venue_enricher as ve
                cache = ve.VenueContactCache()
                from collections import Counter as _C
                venues = _C(r.get('organizador','').strip() for r in sin_email_ra)
                venues_util = {v:c for v,c in venues.items() if ve.es_venue_util(v)}
                ordenados = sorted(venues_util.items(), key=lambda x:-x[1])
                log(f"  🏟️ Venue-first: {len(venues_util)} venues enriquecibles")
                ganado = 0
                por_actualizar = {}  # venue -> email
                for v, _c in ordenados[:20]:
                    info = cache.get(v)
                    if info and info.get('email') and es_email_valido(info['email']):
                        por_actualizar[v] = info['email']
                if por_actualizar:
                    from core.csv_lock import csv_locked_rows
                    with csv_locked_rows(CSV_FILE) as (todas, fieldnames):
                        for r in todas:
                            rv = r.get('organizador','').strip()
                            if rv in por_actualizar and not r.get('email','').strip():
                                # Re-validar: el cache puede contener emails viejos ya filtrados
                                if es_email_valido(por_actualizar[rv]):
                                    r['email'] = por_actualizar[rv]
                                    ganado += 1
                log(f"  🏟️ Venue-first: {ganado} eventos actualizados desde cache")
            except Exception as e:
                log(f"  ⚠️ Venue-first error: {str(e)[:80]}")
        
        # bloque por fuente para no cargar
        objetivo = sin_email_bloque if bloque != 0 else sin_email_ra
        if not objetivo and sin_email_ra:
            objetivo = sin_email_ra  # fallback si bloque vacío
        if objetivo:
            nombre_bloque = {0:"RA",1:"FB matriz",2:"resto"}[bloque]
            log(f"Procesando {min(BATCH, len(objetivo))} eventos {nombre_bloque} sin email...")
            cambios = procesar_batch(objetivo, 'email', BATCH, offset=iteration*BATCH)
            updated = aplicar_cambios(cambios, 'email')
            log(f"  ✅ {updated} eventos actualizados con email")
        elif sin_email:
            log(f"  (sin RA) Procesando {min(BATCH, len(sin_email))} eventos de otras fuentes sin email...")
            cambios = procesar_batch(sin_email, 'email', BATCH, offset=iteration*BATCH)
            updated = aplicar_cambios(cambios, 'email')
            log(f"  ✅ {updated} eventos actualizados con email")
        
        # 2. Procesar eventos sin organizador. Incluye la cola FB (matriz) con
        #    nombres genéricos ('dark psy ritual'): aunque el rendimiento por
        #    evento es bajo (~4%), la rotación barre todo el pool y el minero
        #    resuelve los que sí tienen página host indexada.
        sin_org = cargar_eventos_sin_org()
        sin_org_fb = [
            e for e in sin_org
            if e.get('fuente','') in ('Facebook','Facebook (matriz)','Instagram (prueba)','Psytrance.pl','Facebook (dorks)')
        ]
        sin_org_gen = [e for e in sin_org if es_nombre_gen_org(e.get('nombre','')) and
                       e.get('fuente','') not in ('Facebook','Facebook (matriz)','Instagram (prueba)','Psytrance.pl','Facebook (dorks)')]
        log(f"Sin organizador: {len(sin_org)} total, {len(sin_org_fb)} minables (incl. cola FB genérica), {len(sin_org_gen)} genéricos no-FB (omitidos)")
        
        _dorks = _dorks_activos()
        if sin_org_fb and _dorks:
            # Rama 2a: org por nombre vía DDG → yield medido ~0 (los nombres
            # genéricos de FB no tienen presencia en buscadores). Solo corre si
            # los dorks FB/IG están activos (su feed alimenta este frente).
            presupuesto_2a = min(40, BATCH, len(sin_org_fb))
            log(f"Procesando {presupuesto_2a} eventos FB/IG enriquecibles (org/2a)...")
            cambios = procesar_batch(sin_org_fb, 'org', presupuesto_2a, offset=iteration*BATCH)
            updated = aplicar_cambios(cambios, 'org')
            log(f"  ✅ {updated} eventos actualizados con organizador")

        # 2b. Barrido SERP por ciudad: los eventos FB (matriz) vienen de dorks
        #     'site:facebook.com/events <ciudad> psy trance <año>' → el snippet
        #     trae 'Event in X by ORGANIZER on <día>' y la URL exacta del evento.
        #     Match por URL literal, rota las ciudades pendientes. Sobrescribe
        #     organizadores basura derivados de slug ('Ph Hs') con el real.
        pend = checkpoint.setdefault('fb_ciudades_pendientes', [])
        if not pend:
            pend = sorted({(r.get('lugar', '') or '').strip()
                          for r in sin_org
                          if 'Facebook' in r.get('fuente', '') and (r.get('lugar', '') or '').strip()})
            checkpoint['fb_ciudades_pendientes'] = pend
        if pend:
            from collections import Counter as _C
            _years = {}
            for r in sin_org:
                if 'Facebook' in r.get('fuente', ''):
                    c = (r.get('lugar', '') or '').strip()
                    y = (r.get('fecha', '') or '')[:4]
                    if y.isdigit() and y >= '2024':
                        _years.setdefault(c, _C()).update([y])
            ciudades_ahora = [pend.pop() for _ in range(min(8, len(pend)))]
            pend[:0] = ciudades_ahora                              # rotar al frente
            log(f"  🌆 Barrido SERP por ciudad: {ciudades_ahora}")
            mapa = {}
            if _dorks:
                try:
                    anios_ciud = {c: [y for y, _ in _years[c].most_common(2)] for c in ciudades_ahora if c in _years}
                    sub_ciud = {}
                    for r in sin_org:
                        if (r.get('lugar', '') or '').strip() in ciudades_ahora and 'Facebook' in r.get('fuente', ''):
                            sg = (r.get('subgenero', '') or '').strip()
                            if sg and sg.lower() != 'n/a':
                                sub_ciud.setdefault((r.get('lugar', '') or '').strip(), _C()).update([sg])
                    for c in ciudades_ahora:
                        subs = [sg for sg, _ in sub_ciud[c].most_common(4)] if c in sub_ciud else []
                        mapa.update(minar_organizadores_fb_serp([c], anios=anios_ciud.get(c, []),
                                                                subgeneros=subs, max_por_ciclo=1))
                except Exception as e:
                    mapa = {}
                    log(f"  ⚠️ Barrido SERP error: {str(e)[:80]}")
            else:
                log("  🌆 Frente FB-org SERP en pausa: dorks FB/IG apagados (yield ~0 medido) → presupuesto al frente email")
            ganado = 0
            mejorado = 0
            if mapa:
                # Índice por slug del primer segmento de events/<slug> para
                # propagar el organizador a TODAS las filas FB con esa página
                # host, aunque la URL completa del SERP no matchee textualmente.
                _slug_org = {}
                for _u, _o in mapa.items():
                    _sm = re.search(r'facebook\.com/events/([^/?#]+)', _u.lower())
                    if _sm:
                        _slug_org.setdefault(_sm.group(1), _o)
                from core.csv_lock import csv_locked_rows
                with csv_locked_rows(CSV_FILE) as (todas, fieldnames):
                    for r in todas:
                        if 'Facebook' not in r.get('fuente', ''):
                            continue
                        org_act = (r.get('organizador', '') or '').strip()
                        if org_act and org_act.lower() != 'n/a' and not es_org_slugderivado(org_act):
                            continue
                        rl = _normalizar_link_fb(r.get('link', '') or '')
                        org = mapa.get(rl)
                        if not org:
                            _sm2 = re.search(r'facebook\.com/events/([^/?#]+)', rl.lower())
                            if _sm2:
                                org = _slug_org.get(_sm2.group(1))
                        if org and org.lower() != org_act.lower():
                            if org_act and org_act.lower() != 'n/a':
                                mejorado += 1
                            else:
                                ganado += 1
                            r['organizador'] = org
                            r['tipo_organizador'] = tipo_organizador(org)
                log(f"  🌆 Barrido SERP: {ganado} nuevos + {mejorado} mejorados (de {len(mapa)} soles, {len(_slug_org)} slugs)")

        # 2c. Telegram: canales públicos por ciudad (vector del asesor). Un canal
        #     activo cubre docenas de eventos del mismo organizador; los mensajes
        #     traen URL FB + organizador ('by X on'/'presented by X').
        #     Rendimiento real bajo con dorks DDG → racionado (1 ciudad cada 8₮).
        if pend and ciudades_ahora and iteration % 8 == 0:
            try:
                tmapa = minar_organizadores_telegram(ciudades_ahora, max_por_ciclo=1)
                if tmapa:
                    tganado = _aplicar_mapa_org(tmapa, solo_vacios=True)
                    log(f"  📡 Telegram: {tganado} nuevos (de {len(tmapa)} soles)")
            except Exception as e:
                log(f"  ⚠️ Telegram error: {str(e)[:80]}")

        # 2d. Re-propagación periódica del caché limpio (cada 5 ciclos):
        #     reusa emails ya existentes en fuentes fiables para organizadores
        #     resueltos por el propio loop (no busca nuevos, solo propaga).
        if iteration % 2 == 0:
            try:
                from propagacion_caché_limpio import repropagar_cache
                _gan = repropagar_cache()
                log(f"  ♻️ Re-propagación caché: {_gan} emails aplicados")
            except Exception as e:
                log(f"  ⚠️ Re-propagación caché error: {str(e)[:80]}")

        # 3. Rama A (asesor): email por organizador → DDG → web → email.
        #    Un promoter cubre muchos eventos: se busca UNA vez y se aplica a
        #    todos sus eventos sin email. Cola rotativa persistente (3/iteración,
        #    máx 3 intentos antes de abandonar).
        pend_em = checkpoint.setdefault('org_email_pendientes', {})
        if iteration % 50 == 1 or not pend_em:
            pend_em.clear()
            for r in sin_org + cargar_eventos_sin_email():
                org = (r.get('organizador', '') or '').strip()
                if not org or org.lower() == 'n/a':
                    continue
                if _es_org_placeholder(org):
                    continue
                if (r.get('email', '') or '').strip():
                    continue
                key = org.lower()
                e = pend_em.setdefault(key, {'key': org, 'lugar': '', 'n': 0, 'intentos': 0, 'ult': 0})
                e['n'] += 1
                lug = (r.get('lugar', '') or '').strip()
                if lug and not e['lugar']:
                    e['lugar'] = lug
            pend_em = dict(sorted(pend_em.items(), key=lambda kv: -kv[1]['n']))
            checkpoint['org_email_pendientes'] = pend_em
        try:
            from concurrent.futures import ThreadPoolExecutor as _Th
            now_ts = time.time()
            candidatos = [v for v in pend_em.values()
                          if (v['ult'] if isinstance(v.get('ult'), (int, float)) else 0) < now_ts - 4*3600
                          and v['intentos'] < 3]
            candidatos.sort(key=lambda v: v['n'], reverse=True)

            def _rama_a(obj):
                obj['intentos'] += 1
                obj['ult'] = now_ts
                try:
                    email = minar_email_organizador(obj['key'], obj.get('lugar', ''))
                except Exception:
                    email = ''
                if not email:
                    return obj, 0, ''
                g = _aplicar_email_organizador(obj['key'], email)
                return obj, g, email

            with _Th(max_workers=8) as pool:
                futuros = [pool.submit(_rama_a, o) for o in candidatos[:40]]
                for f in futuros:
                    try:
                        obj, g, email = f.result(timeout=300)
                    except Exception as exc:
                        log(f"  ⚠️ Rama A thread error: {str(exc)[:60]}")
                        continue
                    if not email:
                        log(f"  ⚠️ Rama A sin email: {obj['key']} (intento {obj['intentos']}/3)")
                        continue
                    log(f"  ✉️ Rama A: {g} eventos de '{obj['key']}' ← {email}")
                    if g > 0:
                        del pend_em[obj['key'].lower()]
        except Exception as e:
            log(f"  ⚠️ Rama A error: {str(e)[:80]}")

        # 2e. Catálogo-origen local (sin red): re-aplica org por venue-host y
        # email por organizador curado. Datos verificados, alta precisión.
        if iteration % 4 == 0:
            try:
                _cf = Path(__file__).resolve().parent
                if (_cf / 'catalogo_org_email.json').exists() and (_cf / 'mapa_venue_host.json').exists():
                    from aplicar_catalogo_org_email import aplicar as _aplicar_cat
                    _g = _aplicar_cat(escribir=True)
                    if _g.get('error'):
                        log(f"  ⚠️ Catálogo-origen: {_g['error']}")
                    elif _g['org'] or _g['email']:
                        log(f"  🗂️ Catálogo-origen: +{_g['org']} org (venue) "
                            f"+{_g['email']} email")
            except Exception as ex:
                log(f"  ⚠️ Catálogo-origen: {str(ex)[:80]}")

        # 2f. Contactos de agencia/booking (local, sin red): refresca
        # agencias_bookings*.csv barriendo todo lo compilado. Alimenta el
        # workstream comercial (agencias de booking de la escena).
        if iteration % 8 == 0:
            try:
                import subprocess as _sp
                _r = _sp.run([sys.executable,
                              str(Path(__file__).resolve().parent / 'buscar_agencias.py')],
                             capture_output=True, text=True, timeout=240)
                _out = (_r.stdout or '').strip().splitlines()
                if _r.returncode == 0 and _out:
                    log(f"  🏢 Agencias/bookings: {_out[-1]}")
                else:
                    log(f"  ⚠️ Agencias: rc={_r.returncode} {(_r.stderr or '')[:60]}")
            except Exception as ex:
                log(f"  ⚠️ Agencias: {str(ex)[:80]}")

        # 2g. Auto-sanado de emails basura (local): cualquier default/plantilla
        # re-inyectado por otros writers se vuelve a vaciar. Idempotente.
        if iteration % 4 == 0:
            try:
                import subprocess as _sp2
                _r2 = _sp2.run([sys.executable,
                                str(Path(__file__).resolve().parent / 'depurar_emails_masivos.py'),
                                '--apply', '--sin-backup'],
                               capture_output=True, text=True, timeout=240)
                _out2 = (_r2.stdout or '').strip().splitlines()
                _apl = [l for l in _out2 if l.startswith('APLICADO')]
                _tot = [l for l in _out2 if l.startswith('a cuarentena')]
                if _apl and not _apl[0].startswith('APLICADO: 0'):
                    log(f"  🧹 Auto-sanado emails — {_tot[-1] if _tot else ''} {_apl[-1]}")
            except Exception as ex:
                log(f"  ⚠️ Auto-sanado emails: {str(ex)[:80]}")

        # Detector de meseta (criterio de 'tope real').
        # Meseta: <0.3 puntos de ganancia acumulada en ORG y EMAIL en 30
        # iteraciones (DOS rotaciones completas del pool de ciudades:
        # 118 ciudades / 8 por ciclo ≈ 15 iter por rotación). Así el barrido
        # SERP ya barrió cada ciudad 2 veces y confirmamos que no queda nada.
        try:
            with csv_locked_rows(CSV_FILE) as (todas, _):
                _lleno = lambda r, c: (r.get(c, '') or '').strip() not in ('', 'N/A')
                n = max(1, len(todas))
                pct_org = sum(1 for r in todas if _lleno(r, 'organizador')) / n
                pct_email = sum(1 for r in todas if _lleno(r, 'email')) / n
                # Catálogo refinado (meta honesta): excluye el residuo NO
                # minable (nombres genéricos FB sin página host indexable).
                resid = [r for r in todas
                         if (r.get('fuente') or '').lower().startswith('facebook')
                         and es_nombre_gen_org(r.get('nombre') or '')]
                _rids = {id(r) for r in resid}
                ref = [r for r in todas if id(r) not in _rids]
                n_ref = max(1, len(ref))
                pct_org_ref = sum(1 for r in ref if _lleno(r, 'organizador')) / n_ref
                pct_email_ref = sum(1 for r in ref if _lleno(r, 'email')) / n_ref
            hist = checkpoint.setdefault('meseta_historial', [])
            hist.append({'it': iteration, 'org': pct_org_ref, 'email': pct_email_ref})
            hist[:] = hist[-30:]
            meta_org = checkpoint.get('meta_org', 0.95)
            meta_email = checkpoint.get('meta_email', 0.95)
            llegado = pct_org_ref >= meta_org and pct_email_ref >= meta_email
            # Meseta = "tope real" solo si ya estamos cerca del techo. Si la
            # cobertura está baja (p.ej. tras una limpieza de datos), NO es
            # meseta: queda trabajo minable y el loop debe seguir.
            _piso = checkpoint.get('meseta_piso', 0.80)
            meseta = len(hist) == 30 and pct_org_ref >= _piso and pct_email_ref >= _piso and (
                hist[-1]['org'] - hist[0]['org'] < 0.003 and
                hist[-1]['email'] - hist[0]['email'] < 0.003
            )
            log(f"  📊 Org {pct_org*100:.1f}% (ref {pct_org_ref*100:.1f}%) | "
                f"Email {pct_email*100:.1f}% (ref {pct_email_ref*100:.1f}%) | "
                f"residuo {len(resid)} | meta {meta_org*100:.0f}/{meta_email*100:.0f} | "
                f"llego={llegado} meseta={meseta}")
            if llegado or meseta:
                parar = checkpoint.get('parar_al_llegar', False)
                if parar:
                    estado = "por umbral" if llegado else "por meseta"
                    log(f"  🏁 COMPLETADO ({estado}) — deteniendo loop en iteración {iteration}")
                    checkpoint['iteration'] = iteration
                    checkpoint['batch'] = BATCH
                    checkpoint['pausa'] = PAUSA
                    checkpoint['estado'] = f'completado:{estado}'
                    with open(CHECKPOINT_FILE, 'w') as f:
                        json.dump(checkpoint, f, indent=2)
                    return
                log("  ℹ️ Meta/meseta alcanzada pero parar_al_llegar=False — continúo completando")
        except Exception as e:
            log(f"  ⚠️ Meseta check error: {str(e)[:80]}")

        # Checkpoint
        checkpoint['iteration'] = iteration
        checkpoint['batch'] = BATCH
        checkpoint['pausa'] = PAUSA
        try:
            with open(CHECKPOINT_FILE, 'w') as f:
                json.dump(checkpoint, f, indent=2)
        except Exception:
            pass

        # Cada 25 iteraciones: relleno local de N/A (país/continente/subgénero
        # desde el propio dataset + geo_cache; cero coste de red).
        if iteration % 25 == 0:
            try:
                import subprocess
                subprocess.run([sys.executable, str(Path(_PROJECT_ROOT) / 'core' / 'rellenar_na.py')],
                               timeout=120, capture_output=True)
            except Exception as e:
                log(f"  ⚠️ Relleno local error: {str(e)[:80]}")
        
        # Esperar antes de siguiente iteración
        log(f"Esperando {PAUSA}s antes de siguiente iteración...")
        time.sleep(PAUSA)

if __name__ == "__main__":
    main()
