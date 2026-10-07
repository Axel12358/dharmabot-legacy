#!/usr/bin/env python3
"""Pase B fechas: m.facebook.com para los placeholders sin fecha en og:description.
Cache en cache_fecha_alt.json (resume). Aplica bajo lock; <2025 a archivos.
"""
import csv, re, sys, json, time, random, urllib.request, argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, '/tmp')
from core.csv_lock import csv_locked_rows
from core.fb_ids import extraer_id
from core.fecha_parse import parse_fecha

CSV = ROOT / 'eventos_encontrados.csv'
CACHE = ROOT / 'cache_fecha_alt.json'
DEAD = ROOT / 'eventos_deadstock_2021_2024.csv'
HIST = ROOT / 'eventos_historicos_pre2021.csv'
UA = 'facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)'

def fetch_m(i):
    for host in ('https://m.facebook.com/events/%s/' % i, 'https://www.facebook.com/events/%s/' % i):
        try:
            req = urllib.request.Request(host, headers={'User-Agent': UA})
            html = urllib.request.urlopen(req, timeout=14).read().decode('utf-8', 'ignore')
        except Exception:
            continue
        if not html or 'Inicia sesi' in html or 'Ve publicaciones' in html:
            return html if '</html>' in html else None
        return html
    return None

def extraer_meta(html):
    out = {}
    m = re.search(r'"startDate"\s*:\s*"([^"]+)"', html)
    if m: out['startDate'] = m.group(1)
    m = re.search(r'og:description"\s+content="([^"]+)"', html)
    if m: out['ogdesc'] = (m.group(1).replace('&#xe1;','á').replace('&#xfa;','ú')
                           .replace('&#xed;','í').replace('&#xf3;','ó')
                           .replace('&#xe9;','é').replace('&#xf1;','ñ'))
    return out

def load_cache():
    if CACHE.exists():
        try: return json.loads(CACHE.read_text(encoding='utf-8'))
        except Exception: return {}
    return {}

def main():
    args = _args()
    with csv_locked_rows(CSV, timeout=300) as (rows, _fn):
        ph = [r for r in rows if re.match(r'^\d{4}-01-01$', (r.get('fecha') or '').strip())]
    print('placeholders restantes:', len(ph))
    jobs = {}
    for r in ph:
        i = extraer_id(r.get('link', ''))
        if i: jobs.setdefault(i, (r.get('fecha') or '')[:4])
    cache = load_cache()
    pend = [kv for kv in jobs.items() if kv[0] not in cache]
    if args.max: pend = pend[:args.max]
    print(f'ids a probar FB móvil: {len(pend)} / {len(jobs)}')

    done = 0; t0 = time.time()
    def worker(item):
        fb_id, yr = item
        html = fetch_m(fb_id)
        meta = extraer_meta(html) if html else {}
        time.sleep(random.uniform(0.1, 0.4))
        return fb_id, meta
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(worker, kv): kv for kv in pend}
        for fut in as_completed(futs):
            fb_id, meta = fut.result()
            cache.setdefault(fb_id, meta)
            done += 1
            if done % 200 == 0:
                el = time.time()-t0
                print(f'[{done}/{len(pend)}] {el:.0f}s ETA {el/max(done,1)*len(pend):.0f}s', flush=True)
                CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')
    print('fetch móvil completo:', done)

    fechas = {}
    for i, yr in jobs.items():
        meta = cache.get(i) or {}
        d = None
        if meta.get('startDate'):
            m = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})', meta['startDate'])
            if m: d = f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'
        if not d and meta.get('ogdesc'):
            d = parse_fecha(meta['ogdesc'], fallback_year=yr)
        if d: fechas[i] = d
    # recuento
    grp = {'2025-2028':0,'2021-2024':0,'<=2020':0}
    for d in fechas.values():
        y = int(d[:4])
        grp['2025-2028' if y>=2025 else ('2021-2024' if y>=2021 else '<=2020')] += 1
    print('resueltas:', len(fechas), grp)

    updates, removals = {}, {}
    for r in ph:
        i = extraer_id(r.get('link', ''))
        if not i or i not in fechas: continue
        lk = (r.get('link') or '').strip().lower() or ('_N_'+(r.get('nombre') or '').lower())
        if int(fechas[i][:4]) >= 2025: updates[lk] = fechas[i]
        else: removals[lk] = (int(fechas[i][:4]), fechas[i])
    if len(removals) > 4000:
        print('ABORTO umbral'); sys.exit(2)

    dead_ids, hist_ids = [], []
    with csv_locked_rows(CSV, timeout=300) as (rows2, fn2):
        keep = []
        for fr in rows2:
            lk = (fr.get('link') or '').strip().lower() or ('_N_'+(fr.get('nombre') or '').lower())
            if lk in removals:
                fr['fecha'] = removals[lk][1]
                (hist_ids if removals[lk][0] < 2021 else dead_ids).append(fr)
                continue
            if lk in updates: fr['fecha'] = updates[lk]
            keep.append(fr)
        def dump(p, filas):
            if not filas: return 0
            prev = []
            if Path(p).exists():
                with open(p, encoding='utf-8') as fh: prev = list(csv.DictReader(fh, fieldnames=None))
            seen = {(x.get('link') or '').lower() for x in prev}
            nuevos = [x for x in filas if (x.get('link') or '').lower() not in seen]
            with open(p, 'w', newline='', encoding='utf-8') as fh:
                w = csv.DictWriter(fh, fieldnames=fn2, extrasaction='ignore'); w.writeheader(); w.writerows(prev); w.writerows(nuevos)
            return len(nuevos)
        nd = dump(DEAD, dead_ids); nh = dump(HIST, hist_ids)
        rows2[:] = keep
    print(f'MAIN: {len(rows)} | deadstock nuevas:{nd} | historicas nuevas:{nh}')

def _args():
    p = argparse.ArgumentParser(); p.add_argument('--max', type=int, default=0); return p.parse_args()

if __name__ == '__main__':
    main()