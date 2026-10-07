#!/usr/bin/env python3
"""Recupera fechas reales de los placeholders YYYY-01-01 vía og:description de FB.

- snapshot bajo csv_lock (sin escritura)
- descargas en paralelo (cache en cache_fb_desc_fechas.json, resume si corta)
- parsea fecha (multi-lang) y aplica cambiando SOLO 'fecha'
- año 2025-2028 -> actualiza fecha
- año 2021-2024 -> eventos_deadstock_2021_2024.csv
- año <=2020    -> eventos_historicos_pre2021.csv
- N/A -> permanece con placeholder (se re-trata en otra pasada)
Nunca borra datos: lo que sale del CSV principal va a un archivo de respaldo.
"""
import csv, re, sys, json, time, random, argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, '/tmp')
from core.csv_lock import csv_locked_rows
from core.fb_ids import extraer_id
from minar_fb_og import get_og
from core.fecha_parse import parse_fecha

CSV = ROOT / 'eventos_encontrados.csv'
CACHE = ROOT / 'cache_fb_desc_fechas.json'
DEAD = ROOT / 'eventos_deadstock_2021_2024.csv'
HIST = ROOT / 'eventos_historicos_pre2021.csv'

def load_cache():
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding='utf-8'))
        except Exception:
            return {}
    return {}

def save_cache(cache):
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')

def fetch_one(item):
    fb_id, fallback_year = item
    desc = get_og(f'https://www.facebook.com/events/{fb_id}/')
    time.sleep(random.uniform(0.05, 0.25))
    return fb_id, desc

def _argmax():
    p = argparse.ArgumentParser()
    p.add_argument('--max', type=int, default=0)
    return p.parse_args()

def main():
    with csv_locked_rows(CSV, timeout=300) as (rows, fn):
        ph = [r for r in rows
              if re.match(r'^\d{4}-01-01$', (r.get('fecha') or '').strip())]
    print(f'placeholder rows: {len(ph)}')

    jobs = {}
    for r in ph:
        _id = extraer_id(r.get('link', ''))
        if not _id:
            continue
        jobs.setdefault(_id, (r.get('fecha') or '')[:4])

    cache = load_cache()
    pend = [kv for kv in jobs.items() if kv[0] not in cache]
    print(f'ids únicos: {len(jobs)} | ya en cache: {len(jobs)-len(pend)} | por bajar: {len(pend)}')

    args = _argmax()
    if args.max:
        pend = pend[:args.max]
        print('testing con max:', args.max)

    sol = {}
    try:
        sol = json.loads(open('/tmp/fechas_backup.json').read())
    except Exception:
        sol = {}
    print('backup crossref ids:', len(sol))
    for _id in jobs:
        if _id in sol:
            cache.setdefault(_id, 'BACKUP:' + sol[_id])

    done = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(fetch_one, kv): kv for kv in pend}
        for fut in as_completed(futs):
            fb_id, desc = fut.result()
            cache.setdefault(fb_id, desc)
            done += 1
            if done % 500 == 0:
                el = time.time() - t0
                eta = el / max(done, 1) * len(pend)
                print(f'[{done}/{len(pend)}] {el:.0f}s ETA {eta:.0f}s', flush=True)
                save_cache(cache)
    save_cache(cache)
    print(f'descargas completas: {done} en {time.time()-t0:.0f}s')

    fechas = {}
    for _id, yr in jobs.items():
        raw = cache.get(_id)
        if isinstance(raw, str) and raw.startswith('BACKUP:'):
            d = raw[7:]
            if re.match(r'^\d{4}-\d{2}-\d{2}$', d):
                fechas[_id] = d
            continue
        if not raw:
            continue
        d = parse_fecha(raw, fallback_year=yr)
        if d:
            fechas[_id] = d
    grp = {'2025-2028': 0, '2021-2024': 0, '<=2020': 0}
    for d in fechas.values():
        y = int(d[:4])
        if y >= 2025:
            grp['2025-2028'] += 1
        elif y >= 2021:
            grp['2021-2024'] += 1
        else:
            grp['<=2020'] += 1
    print('ids con fecha resuelta:', len(fechas), '| distribuido:', grp)

    updates, removals = {}, {}
    for r in ph:
        _id = extraer_id(r.get('link', ''))
        if not _id or _id not in fechas:
            continue
        lk = (r.get('link') or '').strip().lower()
        if not lk:
            lk = '_N_' + (r.get('nombre') or '').strip().lower() + '|' + (r.get('fecha') or '').strip()
        if int(fechas[_id][:4]) >= 2025:
            updates[lk] = fechas[_id]
        else:
            removals[lk] = (r, int(fechas[_id][:4]), fechas[_id])

    if len(removals) > 4000:
        print(f'ABORTO de seguridad: se moverían {len(removals)} filas; umbral 4000')
        sys.exit(2)
    tgt, hist_ids, dead_ids = [], [], []
    with csv_locked_rows(CSV, timeout=300) as (rows2, fn2):
        for fr in rows2:
            lk = (fr.get('link') or '').strip().lower()
            if not lk:
                lk = '_N_' + (fr.get('nombre') or '').strip().lower() + '|' + (fr.get('fecha') or '').strip()
            if lk in removals:
                fr['fecha'] = removals[lk][2]
                (hist_ids if removals[lk][1] < 2021 else dead_ids).append(fr)
                continue
            if lk in updates:
                fr['fecha'] = updates[lk]
            tgt.append(fr)

        def dump(path, filas):
            if not filas:
                return 0
            prev = []
            if Path(path).exists():
                with open(path, encoding='utf-8') as fh:
                    prev = list(csv.DictReader(fh, fieldnames=None))
            seen = {(x.get('link') or '').strip().lower() for x in prev}
            nuevos = [x for x in filas if (x.get('link') or '').strip().lower() not in seen]
            with open(path, 'w', newline='', encoding='utf-8') as fh:
                w = csv.DictWriter(fh, fieldnames=fn2, extrasaction='ignore')
                w.writeheader()
                w.writerows(prev)
                w.writerows(nuevos)
            return len(nuevos)

        n_dead = dump(DEAD, dead_ids)
        n_hist = dump(HIST, hist_ids)
    print(f'MAIN: {len(tgt)} filas (antes {len(rows)})')
    print(f'deadstock 2021-2024 añadidas: {n_dead} | hist <=2020 añadidas: {n_hist}')
    print('OK')

if __name__ == '__main__':
    main()