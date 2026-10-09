#!/usr/bin/env python3
"""Base de contactos de agencias/bookings/management/promo/talent/press.

Barre en SOLO LECTURA los CSV/JSON/JSONL de la raíz del proyecto (dataset
principal, no_psy, históricos, deadstock, backups, propuestas, cuarentena...),
extrae cualquier email cuyo local-part o dominio apunte a agencia/booking/
management/promo/talent/press, lo clasifica como ESCENA o NO-ESCENA y escribe
dos salidas:

  - agencias_bookings.csv         -> TODOS los contactos (con escena + motivo)
  - agencias_bookings_escena.csv  -> SOLO escena (música/eventos)

Nunca modifica el dataset ni catalogo_org_email.json (workstream paralelo).

Uso:
    .venv/bin/python buscar_agencias.py                 # escribe ambos CSV
    .venv/bin/python buscar_agencias.py --solo-escena   # solo escena
    .venv/bin/python buscar_agencias.py --min-menciones 5
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

PROJ = Path(__file__).resolve().parent
OUT_TODOS = PROJ / 'agencias_bookings.csv'
OUT_ESCENA = PROJ / 'agencias_bookings_escena.csv'

# Nunca leer los propios outputs (bucle de retroalimentación) ni el catálogo
# (lo está limpiando otro workstream en paralelo).
EXCLUIR_ARCHIVOS = {OUT_TODOS.name, OUT_ESCENA.name, 'catalogo_org_email.json'}

RE_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# local-part o dominio de agencia/booking (incluye 'artists' y 'reserv*').
AG = re.compile(
    r'book|agenc|reserv|talent|mgmt|manage|promot|promo|press|roster|bureau|artists?',
    re.I)

# --------------------------------------------------------------------------- #
# Clasificación escena / no-escena
# --------------------------------------------------------------------------- #

# Dominios concretos verificados como NO escena (hospitality/tours/gob/medios/
# corporativo). Ampliable: se revisa la lista de escena tras cada ejecución.
NONSCENE_DOMAINS = {
    # ejemplos que dio el usuario
    'lapalomarestaurante.es', 'oelgarten.com', 'yourholidaybooking.com',
    'panchotours.com', 'marriott.com', 'tate.org.uk', 'wayofdk.de',
    'readymag.com', 'fortifiedestate.com',
    # hospitality / venues de comida
    'muamuarestaurant.com', 'waldorfastoria.com', 'sixsenses.com',
    'nobuhotels.com', 'renhotels.com', 'princess-hotels.com', 'melia.com',
    'fairmont.com', 'boisdale-cw.co.uk', 'cratebrewery.com',
    'winemechanics.se', 'luxyoga.com', 'starlanepizzabar.com',
    'saunasocialclub.co.uk', 'cavorooftop.pt', 'esporao.com', 'labmadrid.es',
    'skatecafe.nl', 'spotlag.com', 'rowans.co.uk', 'thestationbar.co.nz',
    'destinationhostels.com',
    # travel / tours
    'ghosttour.dk', 'bcs-bus.com', 'thamesrockets.com', 'impresstravel.com',
    'travelpromoters.co.uk', 'tropical-nomads.com', 'tropicalnomads.com',
    # hospitality / comida (pubs, lounges)
    'threestagspub.com', 'celavi.com',
    # plataformas / spam / corporativo
    'rapidshare.com', 'everybooking.com',
    # medios / corporativo / gobierno
    'christianbook.com', 'mohistory.org', 'medium.com', 'freepress.com',
    'freiepresse.de', 'jpress.co.uk', 'lemonade-pr.com', 'mslgroup.com',
    # placeholders / basura
    'yourname.com', 'booking.com', 'booking.comfor',
}

# Subcadenas seguras dentro del dominio (distintivas de no-escena).
NONSCENE_SUB_DOM = (
    'restaurant', 'restaurante', 'hotel', 'hostel', 'resort', 'retreat',
    'holiday', 'tourism', 'travel', 'ticketing', 'rooftop', 'sauna',
    'camping', 'cruise', 'pizz', 'brewery', 'brewhouse', 'winery', 'winebar',
    'museum', 'university', 'realty', 'insurance', 'freiepresse', 'freepress',
    'tageszeitung', 'newspaper', 'travelpromoters', 'panchotours',
    'ghosttour', 'sixsenses', 'nobuhotels', 'renhotels', 'waldorfastoria',
    'fairmont', 'marriott', 'princess-hotels', 'lemonade-pr',
    'lagencedulobby', 'christianbook', 'mohistory', 'thamesrockets',
    'bcs-bus', 'destinationhostel', 'boisdale', 'cratebrewery',
    'winemechanics', 'luxyoga', 'starlanepizza', 'saunasocial', 'skatecafe',
    'streetfeast', 'spuds', 'rowans',
)

# Tokens exactos (local o dominio) que delatan no-escena.
NONSCENE_TOKENS = {
    'resto', 'cafe', 'coffee', 'cafeteria', 'pub', 'bistro', 'brasserie',
    'tavern', 'diner', 'grill', 'steakhouse', 'sushi', 'taco', 'burger',
    'bakery', 'spa', 'inn', 'lodge', 'suites', 'marina', 'palace', 'chateau',
    'castle', 'mansion', 'yoga', 'edu', 'gov', 'government', 'council',
    'university', 'school', 'museum', 'insurance', 'realty',
}

# Subcadenas no-escena dentro del local-part.
NONSCENE_SUB_LOCAL = (
    'coaching', 'privacyrequest', 'customerservice', 'customerservices',
    'mediarelations', 'bookcentre', 'ticketing',
)

# Placeholders / plantillas (se descartan por completo de ambos CSV).
PLACEHOLDER_LOCAL = {
    'votre', 'votreemail', 'votre-email', 'youremail', 'your-email',
    'yourname', 'nombre', 'tunombre', 'tudominio', 'midominio',
    'nombredominio', 'email', 'example', 'test', 'user', 'usuario',
}
PLACEHOLDER_DOMAIN = {
    'example.com', 'example.org', 'example.net', 'example.es',
    'domain.com', 'domain.tld', 'domain.es', 'email.com', 'mail.test',
    'test.com', 'test.org', 'yourname.com', 'yourdomain.com',
    'tudominio.com', 'midominio.com', 'nombredominio.com',
    'company.com', 'empresa.com', 'sitename.com',
}

RE_RESERVA = re.compile(r'\breserv|reserve|reservierung|reserveren|reserva', re.I)


def _tld_malformada(dom: str) -> bool:
    last = dom.rsplit('.', 1)[-1]
    for t in ('com', 'org', 'net', 'edu', 'gov', 'info', 'biz', 'int', 'mil'):
        if last.startswith(t) and last != t:
            return True
    return False


def es_basura(local: str, dom: str) -> bool:
    if not local or not dom:
        return True
    if local in PLACEHOLDER_LOCAL or dom in PLACEHOLDER_DOMAIN:
        return True
    if 'votre' in local or 'tudominio' in dom:
        return True
    if _tld_malformada(dom):
        return True
    return False


def clasificar_tipo(local: str, dom: str) -> str:
    hay = f'{local} {dom}'.lower()
    if re.search(r'mgmt|management|manage\b|manager', hay):
        return 'management'
    if 'talent' in hay:
        return 'talent'
    if re.search(r'promot|promo', hay):
        return 'promo'
    if re.search(r'booking|bookings|\bbook\b', hay):
        return 'booking'
    if re.search(r'agenc|agency|bureau|roster|artists?', hay):
        return 'agency'
    if re.search(r'press|presse|\bpr\b', hay):
        return 'press'
    return 'artist'


def clasificar_escena(local: str, dom: str, org: str, ejemplo: str):
    """Devuelve (escena: bool, motivo_exclusion: str)."""
    if RE_RESERVA.search(local) or local in {'tour', 'tours', 'travel'}:
        return False, 'reserva_hospitality'
    if dom in NONSCENE_DOMAINS:
        return False, 'dominio_no_escena'
    if any(s in dom for s in NONSCENE_SUB_DOM):
        return False, 'dominio_hospitality_corp'
    toks = set(re.split(r'[^a-z0-9]+', f'{local} {dom}'))
    if toks & NONSCENE_TOKENS:
        return False, 'token_no_escena'
    if any(s in local for s in NONSCENE_SUB_LOCAL):
        return False, 'local_no_escena'
    return True, ''


# --------------------------------------------------------------------------- #
# Barrido de fuentes
# --------------------------------------------------------------------------- #

def _fila_csv(p: Path):
    try:
        with open(p, encoding='utf-8', errors='ignore', newline='') as f:
            yield from csv.DictReader(f)
    except Exception:
        return


def _walk_json(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from _walk_json(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk_json(v)
    elif isinstance(o, str):
        yield o


def recoge():
    agg = defaultdict(lambda: {'n': 0, 'archivos': Counter(),
                               'orgs': Counter(), 'paises': Counter(),
                               'ejemplo': '', 'link': ''})
    archivos = [p for p in PROJ.glob('*')
                if p.suffix.lower() in ('.csv', '.json', '.jsonl')
                and p.name not in EXCLUIR_ARCHIVOS]

    def _acepta(e: str):
        if '@' not in e:
            return None
        local, _, dom = e.partition('@')
        if not AG.search(local) and not AG.search(dom):
            return None
        if es_basura(local, dom):
            return None
        return local, dom

    for p in sorted(archivos):
        if p.suffix.lower() == '.csv':
            for r in _fila_csv(p):
                for val in r.values():
                    if not val:
                        continue
                    for e in RE_EMAIL.findall(val):
                        e = e.strip().lower()
                        par = _acepta(e)
                        if not par:
                            continue
                        a = agg[e]
                        a['n'] += 1
                        a['archivos'][p.name] += 1
                        org = (r.get('organizador') or '').strip()
                        if org and org.upper() not in ('N/A', 'NA'):
                            a['orgs'][org] += 1
                        pais = (r.get('pais') or r.get('lugar') or '').strip()
                        if pais and pais.upper() not in ('N/A', 'NA'):
                            a['paises'][pais] += 1
                        if not a['ejemplo']:
                            a['ejemplo'] = (r.get('nombre') or '')[:90]
                            a['link'] = (r.get('link') or '')[:120]
        else:
            try:
                data = json.loads(p.read_text(encoding='utf-8'))
            except Exception:
                try:
                    data = [json.loads(l) for l in p.read_text(
                        encoding='utf-8').splitlines() if l.strip().startswith('{')]
                except Exception:
                    continue
            for s in _walk_json(data):
                for e in RE_EMAIL.findall(s):
                    e = e.strip().lower()
                    if _acepta(e):
                        agg[e]['n'] += 1
                        agg[e]['archivos'][p.name] += 1
    return agg, [p.name for p in archivos]


def construir_filas(agg):
    filas = []
    for e, a in agg.items():
        local, _, dom = e.partition('@')
        org = (a['orgs'].most_common(1)[0][0] if a['orgs'] else '')
        ejemplo = a['ejemplo']
        escena, motivo = clasificar_escena(local, dom, org, ejemplo)
        filas.append({
            'email': e, 'dominio': dom, 'tipo': clasificar_tipo(local, dom),
            'escena': 'true' if escena else 'false',
            'motivo_exclusion': motivo,
            'n_menciones': a['n'], 'n_archivos': len(a['archivos']),
            'organizador': org,
            'pais': (a['paises'].most_common(1)[0][0] if a['paises'] else ''),
            'archivos': ','.join(x for x, _ in a['archivos'].most_common()),
            'ejemplo': ejemplo, 'link': a['link'],
        })
    # Relevancia: escena primero, luego n_menciones desc, luego email.
    filas.sort(key=lambda r: (r['escena'] != 'true', -r['n_menciones'], r['email']))
    return filas


CAMPOS = ['email', 'dominio', 'tipo', 'escena', 'motivo_exclusion',
          'n_menciones', 'n_archivos', 'organizador', 'pais', 'archivos',
          'ejemplo', 'link']


def _escribe(path: Path, filas):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        w.writeheader()
        w.writerows(filas)


def validar(path: Path):
    """Comprueba recuento, unicidad y ausencia de emails basura/plantilla."""
    with open(path, encoding='utf-8') as f:
        filas = list(csv.DictReader(f))
    emails = [r['email'] for r in filas]
    dup = len(emails) - len(set(emails))
    basura = [e for e in emails
              if es_basura(*e.partition('@')[::2]) or 'votre' in e.lower()]
    return len(filas), dup, basura


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--solo-escena', action='store_true',
                    help='escribir únicamente agencias_bookings_escena.csv')
    ap.add_argument('--min-menciones', type=int, default=1,
                    help='descartar contactos con menos de N menciones (def. 1)')
    args = ap.parse_args()

    agg, archivos = recoge()
    filas = construir_filas(agg)
    filas = [r for r in filas if r['n_menciones'] >= args.min_menciones]
    escena = [r for r in filas if r['escena'] == 'true']

    if not args.solo_escena:
        _escribe(OUT_TODOS, filas)
    _escribe(OUT_ESCENA, escena)

    t, d, b = validar(OUT_ESCENA)
    print(f'archivos escaneados: {len(archivos)}')
    print(f'contactos totales (no-escena incluidos): {len(filas)}')
    print(f'contactos ESCENA: {len(escena)} -> {OUT_ESCENA.name}')
    if not args.solo_escena:
        print(f'contactos totales         -> {OUT_TODOS.name}')
    print(f'validación escena: filas={t} duplicados={d} basura={len(b)}')


if __name__ == '__main__':
    main()
