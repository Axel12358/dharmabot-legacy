#!/usr/bin/env python3
"""Minero de organizador vía og:description del event page de Facebook.

El og:description público (servido con UA facebookexternalhit) incluye
"Evento ... de ORGANIZADOR el día ..." — el organizador es dato oficial de FB.
Sin API, sin cuenta, sin login. Cero falsos: solo toma el rol "de X" del texto.

Patrones soportados:
  'Evento en <ciudad>, <país> de <ORG> el <día>'  (1 org)
  'Evento en <ciudad>, <país> de <ORG> y N personas más el <día>'  (co-host = ORG)
  'Evento de <ORG> el <día>'
  'Evento de <Categoría> de <ORG> el ...'   (e.g. 'Evento de Deportes de Football Dug Out')
  + variantes EN/ES/DE/FR/PT según locale del HTML.

Uso:
  python minar_fb_og.py                 # dry-run
  python minar_fb_og.py --apply         # escribe bajo csv_lock
  python minar_fb_og.py --max 1000 --threads 8
"""
import argparse
import csv
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core.csv_lock import csv_locked_rows
from core.fb_ids import extraer_id  # versión única (core/fb_ids.py)

PROJECT = Path(__file__).parent
CSV = PROJECT / 'eventos_encontrados.csv'
_CACHE_FILE = PROJECT / 'cache_fb_og_desc.json'
UA = 'facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)'
CACHE = PROJECT / 'cache_fb_og_desc.json'

# 'Evento en <ciudad>, <país> de <ORG> el <día>' | 'Evento de <cat> de <ORG> el'
_PATTERNS = [
    re.compile(r'de\s+([A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9 .,\'&\-]{2,45}?)(?:\s+el\s+|\s+y\s+\d|\s+y\s+otr|\s+,\s+\w+\s+\d|\s*$)', re.I),
]
# quitar 'y N personas más', 'y 4 personas más el', '.. miles' colas
_CLEAN = [
    (re.compile(r'\s+y\s+\d[\d.]*\s*(?:mil|k|K)?(?:\s*personas?)?\s*m[aá]s?\s*$'), ''),
    (re.compile(r'\s+y\s+(\d+\s*(?:mil|k)?)\s*personas?\s*$'), ''),
    (re.compile(r'\.$'), ''),
]


def get_og(link: str):
    """Devuelve og:description del event page (con UA de crawler de FB)."""
    import subprocess
    try:
        p = subprocess.run(
            ['curl', '-s', '--max-time', '14', '-A', UA,
             'https://www.facebook.com/events/%s/' % extraer_id(link)],
            capture_output=True, text=True)
        html = p.stdout or ''
    except Exception:
        return None
    if not html or 'Inicia sesi' in html or 'Ve publicaciones' in html:
        return None
    m = re.search(r'og:description"\s+content="([^"]+)', html)
    if not m:
        return None
    return m.group(1).replace('&#xe1;', 'á').replace('&#xfa;', 'ú').replace('&#xed;', 'í').replace('&#xf3;', 'ó').replace('&#xe9;', 'é')


_CATS = {'música', 'musica', 'danza', 'baile', 'fiesta', 'deportes', 'arte', 'otro', 'otros',
         'cine', 'teatro', 'gastronomía', 'gastronomia', 'clases', 'educación', 'educacion',
         'comunidad', 'familia', 'negocios', 'red', 'ciencia', 'feria', 'causa', 'religión',
         'religion', 'viajes', 'bienestar', 'environment', 'sungai', 'party', 'music', 'dance',
         'sports', 'other', 'networking', 'science', 'community', 'travel', 'shopping'}

# tokens que cierran ciudades/países compuestos ('Ciudad de MÉXICO',
# 'Estados Unidos de AMÉRICA'): un ' de <GEO>' no es el separador del org.
_GEO = {'américa', 'america', 'méxico', 'mexico', 'mexicanos', 'islas', 'bajos',
        'vaticano', 'emiratos', 'gran', 'britania', 'oriente', 'mediodía', 'mediodia'}

# Subgéneros de la escena a los que el og:description aplica organizador.
_ESCENA = {'goa', 'psytrance', 'goa trance', 'psychedelic', 'forest', 'dark psy',
           'progressive', 'prog', 'forest psy', 'darkpsy', 'psy trance', 'hitech',
           'progressive trance', 'full-on', 'twilight', 'forest-psy', 'hi-tech',
           'full on', 'hi tech', 'psycore', 'dark-psytrance', 'suomisaundi',
           'psybient', 'forestpsy', 'dark-psy', 'twilight psy', 'goatrance', 'dark',
           'suomi psy', 'psy', 'night', 'electronic', 'techno', 'trance', 'chill',
           'ambient', 'acid', 'hard', 'party', 'rave'}


def org_desde_desc(desc: str):
    """Extrae el ORGANIZADOR del og:description de FB (ES/en).

    Formatos reales:
      A) 'en <ciudad>, <país> de <ORG> ...'      -> org tras el 1er ' de ' post-ciudad
      B) 'de <ORG> en <ciudad> ...'              -> org = <ORG> (precedente a 'en')
      C) 'de <Cat> en <ciudad>, <país> de <ORG>' -> org tras el ' de ' post-ciudad
      D) 'de <ORG> ...' (sin ciudad)             -> org = <ORG>
    Ciudad detectada por ' en <Capital>'. Categoría = _CATS.
    """
    import html as _html
    if not desc:
        return ''
    s = _html.unescape(desc.strip())
    s = re.split(
        r'\s+(?:el|on|le|den|am)\s+[a-zà-ÿ]{3,10}\b'
        r'|\s+y\s+\d+[\d.,]*\s*(?:personas?\s*)?m[aá]s?'
        r'|\s+con\s+\d+[\d.,]*(?:\s*(?:mil|k))?\s*personas?'
        r'|\.\s*\d+\s*(?:publicacione|comentario|interesado)',
        s, 1)[0].strip()
    s = re.sub(r'^\s*evento\b', '', s, flags=re.I).strip()
    if not s or s.lower() in ('facebook',):
        return ''

    def _fin(seg):
        seg = seg.strip(' .,;').strip()
        seg = re.split(r'\s+y\s+[A-ZÀ-ÿ]|\s+and\s+[A-ZÀ-ÿ]', seg)[0].strip()
        if len(seg) < 2 or len(seg) > 45:
            return ''
        if seg.lower() in ('facebook', 'evento', 'event', 'de', 'by'):
            return ''
        return seg

    # separar por la cláusula de ciudad 'en <Capital>'
    m_en = re.search(r'(?<![a-z])en\s+(?=[A-ZÀ-ÿ])', s)
    if m_en:
        previo = s[:m_en.start()].strip()
        despues = s[m_en.end():]
        # si antes del ' en ' viene ' de <X>', X puede ser ORG (B) o categoría (C)
        m_de1 = re.match(r'^(?:de|by)\s+([A-ZÀ-ÿ])', previo) if previo else None
        if m_de1 and previo[m_de1.start() + 3:].strip().lower() not in _CATS:
            org = _fin(previo[3:])            # caso B: ORG precede a ciudad
            return org
        # post-ciudad: org tras el 1er ' de ' o ' by ' post-ciudad,
        # saltando ' de <GEO>' (ciudades/países compuestos con 'de' interno).
        for m in re.finditer(r'\s(?:de|by)\s+(?=[A-ZÀ-ÿ])', despues):
            nxt = despues[m.end():].strip().split(' ')[0].strip('.,').lower()
            if nxt in _GEO:
                continue
            org = _fin(despues[m.end():])
            if org:
                return org
        return _fin(despues)
    # sin ciudad (caso D): org tras ' de ' inicial
    m_de = re.match(r'^(?:de|by)\s+(?=[A-ZÀ-ÿ])', s)
    if m_de:
        org = _fin(s[m_de.end():])
        if org:
            return org
    # 'Evento Deportes de <ORG>' sin ' de ' inicial
    for m in re.finditer(r'\s(?:de|by)\s+(?=[A-ZÀ-ÿ])', s):
        org = _fin(s[m.end():])
        if org:
            return org
    return ''


def _normalizar_org(org):
    o = org.strip()
    return re.sub(r'\s+', ' ', o)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--max', type=int, default=200000)
    ap.add_argument('--threads', type=int, default=6)
    args = ap.parse_args()

    # cargar cache previa
    cache = {}
    if CACHE.exists():
        try:
            cache = json.loads(CACHE.read_text())
        except Exception:
            cache = {}

    # IDs pendientes
    ids = {}
    with csv_locked_rows(CSV) as (todas, _):
        for r in todas:
            if 'Facebook' not in r.get('fuente', ''):
                continue
            if (r.get('organizador') or '').strip() in ('', 'N/A'):
                continue
            m = extraer_id(r.get('link'))
            if m:
                ids.setdefault(m, []).append(r)
    pend = [sid for sid in ids if sid not in cache][:args.max]
    print(f'IDs únicos sin org, a explorar: {len(pend)} (de {len(ids)})')

    def work(sid):
        if sid in cache:
            return sid, cache.get(sid)
        d = get_og('https://www.facebook.com/events/%s/' % sid)
        org = org_desde_desc(d) if d else ''
        time.sleep(0.05)
        return sid, org

    resultados = {}
    with ThreadPoolExecutor(max_workers=args.threads) as ex:
        for i, (sid, org) in enumerate(ex.map(work, pend), 1):
            if org:
                resultados[sid] = _normalizar_org(org)
            cache[sid] = org
            if i % 100 == 0:
                print(f'  ...{i}/{len(pend)} | orgs {len(resultados)}')

    # persistir cache
    with CACHE.open('w') as f:
        json.dump(cache, f, ensure_ascii=False)

    print(f'\nIDs con organizador vía og: {len(resultados)} ({100*len(resultados)/max(len(pend),1):.0f}%)')

    if args.apply:
        with csv_locked_rows(CSV) as (todas, _):
            gan = 0; omit = 0
            aplicables = {s: o for s, o in cache.items() if o}
            for r in todas:
                m = extraer_id(r.get('link'))
                if not m or m not in aplicables:
                    continue
                if (r.get('organizador') or '').strip() not in ('', 'N/A'):
                    continue
                sub = (r.get('subgenero') or '').strip().lower()
                if not (sub in _ESCENA or sub.endswith(('party', 'rave', 'festival'))):
                    omit += 1
                    continue
                r['organizador'] = aplicables[m]
                gan += 1
            print(f'✅ APLICADOS: {gan} filas con organizador (omitidas fuera de escena: {omit})')
    else:
        print('DRY-RUN — usa --apply para escribir')
        for sid, org in list(resultados.items())[:12]:
            print(f'  {sid} -> {org}')


if __name__ == '__main__':
    main()