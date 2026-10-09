#!/usr/bin/env python3
"""Descubre promoters/eventos en Eventbrite (búsqueda pública) para nuestro nicho.

Por keyword + país recoge: nombre de evento, fecha, ciudad, organizador (nombre e id).
Es la fuente DISCOVERY: no da emails directamente, pero expone promoters reales
y recurrentes (ej. "Laietana" -> Jueves Hard Techno Barcelona) que luego se
cruzan con nuestras filas y reciben minería por organizador.

Gratis/local, sin login. HTTP directo con UA (Eventbrite bloquea TOR).
"""
import argparse
import json
import re
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

PROOT = Path('/Users/angelgarcia/dharmabot')

UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
      'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8'}

MAPA_PAIS = {
    'es': 'spain', 'pt': 'portugal', 'de': 'germany', 'nl': 'netherlands',
    'fr': 'france', 'it': 'italy', 'ch': 'switzerland', 'at': 'austria',
    'cz': 'czech-republic', 'be': 'belgium', 'hu': 'hungary', 'pl': 'poland',
    'uk': 'united-kingdom', 'nordic': 'sweden',
}
KEYWORDS = [
    'psytrance', 'techno', 'hard techno', 'schranz', 'goa trance', 'progressive trance',
    'psychedelic', 'trance party', 'rave', 'full moon', 'darkpsy', 'acid techno',
]


def get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read().decode('utf-8', 'ignore')


def eventos_de_pagina(html):
    # evento -> nombre, fecha, ciudad, organizador
    datos = {}
    m = re.findall(r'https:[^"\\]+eventbrite\.com/e/[^"\\#? ]+', html)
    for u in list(dict.fromkeys(m)):
        datos.setdefault(u, {})
    # fechas ISO embebidas (pagina enlaza eventos con start/end)
    for u in list(datos):
        datos[u]['url'] = u
    return datos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tope', type=int, default=20, help='eventos por página/keyword')
    ap.add_argument('--paises', default='es,pt,de',
                    help='códigos de país (es,pt,de,fr,it,ch,at,nl,cz,be,hu,pl,uk,nordic)')
    ap.add_argument('--marcable', action='store_true')
    args = ap.parse_args()

    OUT = PROOT / 'eventbrite_orgs.json'
    prev = {}
    if OUT.exists():
        try:
            prev = json.loads(OUT.read_text(encoding='utf-8'))
        except Exception:
            prev = {}

    orgs = {o['nombre']: o for o in prev.get('organizadores', [])}
    eventos = {e['url']: e for e in prev.get('eventos', [])}
    paises = [p for p in (args.paises or '').split(',') if p in MAPA_PAIS]

    def org_de_evento(u):
        try:
            h = get(u)
        except Exception:
            return None
        for oid in re.findall(r'[/"]o/(\d+)[/"]?', h):
            pass
        nombre = ''
        for m in re.findall(r'"organizer"\s*:\s*\{[^}]*?"name"\s*:\s*"([^"]+)"', h):
            nombre = m
            break
        if not nombre:
            nombre = (u.split('/o/')[-1].split('-')[:-1] or [''])
            nombre = ' '.join(x for x in (''.join(nombre)).split('-') if x)[:60] if isinstance(nombre, list) else nombre
        if nombre and len(nombre) >= 3:
            orgs.setdefault(nombre.strip(), {'nombre': nombre.strip()})
            return nombre.strip()
        return None

    for cod in paises:
        slug_pais = MAPA_PAIS[cod]
        for kw in KEYWORDS:
            q = urllib.parse.quote(kw)
            url = (f'https://www.eventbrite.com/d/{slug_pais}/{q}/'
                   f'?page_size={args.tope}')
            try:
                html = get(url)
            except Exception as ex:
                print(f'[{cod}] {kw}: ERR {str(ex)[:50]}')
                time.sleep(2)
                continue
            eps = list(dict.fromkeys(re.findall(r'https:[^"\\]+eventbrite\.com/e/[^"\\#? ]+', html)))
            nuevas = [u for u in eps if u not in eventos]
            for u in nuevas[:12]:
                eventos[u] = {'url': u}
                org_de_evento(u)
            print(f'[{cod}] {kw}: {len(eps)} visto, {len(nuevas)} nuevos (orgs total {len(orgs)})')
            time.sleep(1.0)

    prev['eventos'] = list(eventos.values())
    prev['organizadores'] = list(orgs.values())
    prev['paises'] = paises
    OUT.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'organizadores: {len(orgs)} | eventos: {len(eventos)} | salvado en {OUT.name}')
    for o in sorted(orgs)[:15]:
        print('   +', o)


if __name__ == '__main__':
    main()