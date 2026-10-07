#!/usr/bin/env python3
"""Minero de organizadores vía Graph API de Facebook (owner del evento).

Con App ID + App Secret (gratis, developers.facebook.com) genera el app token
y lee el campo 'owner.name' de cada evento FB (el organizador real — la página
que creó el evento). Cero falsos: owner es dato oficial de FB.

Uso:
  python minar_fb_graph.py                 # dry-run: muestra cuántos recupera
  python minar_fb_graph.py --apply         # escribe organizador bajo csv_lock

Config: pon tu APP_ID y APP_SECRET en fb_config.env (ver fb_config.env.example)
o como variables de entorno FB_APP_ID / FB_APP_SECRET.
"""
import argparse
import csv
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core.csv_lock import csv_locked_rows
from loop_completar import tipo_organizador

_BASE = Path(__file__).parent
CSV = _BASE / 'eventos_encontrados.csv'
CONF = _BASE / 'fb_config.env'
GRAPH = 'https://graph.facebook.com'
VERSION = 'v19.0'


def cargar_conf():
    conf = {}
    if CONF.exists():
        for line in CONF.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            conf[k.strip()] = v.strip()
    conf.setdefault('FB_APP_ID', os.environ.get('FB_APP_ID', ''))
    conf.setdefault('FB_APP_SECRET', os.environ.get('FB_APP_SECRET', ''))
    return conf


def get_app_token(app_id, secret):
    import urllib.parse, urllib.request
    q = urllib.parse.urlencode({
        'client_id': app_id, 'client_secret': secret,
        'grant_type': 'client_credentials'})
    url = f'{GRAPH}/oauth/access_token?{q}'
    with urllib.request.urlopen(url, timeout=15) as r:
        return r.read().decode().strip()


def graph_get(path, fields, token):
    import json, urllib.parse, urllib.request
    q = urllib.parse.urlencode({'fields': fields, 'access_token': token})
    url = f'{GRAPH}/{VERSION}/{path}?{q}'
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        return {'error': {'message': body}}


def eventos_pendientes():
    """Devuelve los IDs de evento FB sin organizador, con sus filas."""
    ids = {}
    with csv_locked_rows(CSV) as (todas, _):
        for r in todas:
            if 'Facebook' not in r.get('fuente', ''):
                continue
            if (r.get('organizador') or '').strip() in ('', 'N/A'):
                continue
            m = re.match(r'https://(?:www\.)?facebook\.com/events/(\d{10,})/?', (r.get('link') or '').strip())
            if m:
                ids.setdefault(m.group(1), []).append(r)
    return ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--max', type=int, default=100000, help='máx IDs a consultar')
    ap.add_argument('--sleep', type=float, default=0.35, help='seg entre requests')
    args = ap.parse_args()

    conf = cargar_conf()
    if not conf.get('FB_APP_ID') or not conf.get('FB_APP_SECRET'):
        print('No hay FB_APP_ID / FB_APP_SECRET.')
        print('1) Ve a https://developers.facebook.com -> Mis aplicaciones -> Crear app')
        print('   Tipo "Otro" -> "Ninguna de las anteriores" (gratis, 2 min).')
        print(f'2) Copia App ID y App Secret a {CONF} así:')
        print('   FB_APP_ID=1234567890')
        print('   FB_APP_SECRET=abcdef0123456789abcdef')
        sys.exit(2)

    print('Generando app token...')
    token = get_app_token(conf['FB_APP_ID'], conf['FB_APP_SECRET'])
    print(f'token OK: {token[:12]}...')

    ids = eventos_pendientes()
    ids = list(ids.items())[:args.max]
    print(f'IDs de evento FB sin org a consultar: {len(ids)}')

    # sanity: probar el primero solo
    res = graph_get(ids[0][0], 'id,name,timestamp', token)
    if isinstance(res.get('error'), dict) and 'error' in res.get('error', {}):
        msg = res['error'].get('message', '')
        print('FALLA de permisos en el primer ID:', msg[:200])
        if 'review' in msg.lower() or 'permission' in msg.lower():
            print('FB pide App Review para leer eventos de páginas ajenas.')
            print('Prueba a añadir al token el permiso pages_read_engagement, o')
            print('marca la app modo "Desarrollo" e intenta con user token (Settings).')
        sys.exit(1)
    print('Primer ID responde OK (sin review). Procediendo...')

    resultados = {}
    n_ok = n_err = 0
    for i, (sid, filas) in enumerate(ids, 1):
        data = graph_get(sid, 'name,owner,organizer', token)
        if 'error' in data:
            n_err += 1
        else:
            owner = (data.get('owner') or {}).get('name') or ''
            if owner:
                resultados[sid] = owner
                n_ok += 1
        if i % 50 == 0 or i == len(ids):
            print(f'  ...{i}/{len(ids)} | ok={n_ok} err={n_err}')
        time.sleep(args.sleep)

    print(f'\nIDs resueltos: {n_ok} | sin resolución: {n_err}')

    if args.apply and resultados:
        with csv_locked_rows(CSV) as (todas, _):
            gan = 0
            for r in todas:
                m = re.match(r'https://(?:www\.)?facebook\.com/events/(\d{10,})/?', (r.get('link') or '').strip())
                if not m or m.group(1) not in resultados:
                    continue
                if (r.get('organizador') or '').strip() not in ('', 'N/A'):
                    continue
                r['organizador'] = resultados[m.group(1)]
                r['tipo_organizador'] = tipo_organizador(resultados[m.group(1)])
                gan += 1
            print(f'✅ APLICADOS: {gan} filas con organizador (owner de FB)')
    else:
        print('DRY-RUN — usa --apply para escribir')
        for sid, org in list(resultados.items())[:10]:
            print(f'  {sid} -> {org}')


if __name__ == '__main__':
    main()