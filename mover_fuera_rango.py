#!/usr/bin/env python3
"""Pase de limpieza: mueve del CSV principal a los archivos de respaldo
toda fila con fecha resuelta fuera del rango 2025-2028.

- deadstock 2021-2024 -> eventos_deadstock_2021_2024.csv
- <=2020              -> eventos_historicos_pre2021.csv
Nunca borra: muta rows in-place para que csv_locked_rows escriba la
versión correcta. Re-trata TODAS las fechas ya resueltas (sin descargas).
"""
import csv, re, sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from core.csv_lock import csv_locked_rows

CSV = ROOT / 'eventos_encontrados.csv'
DEAD = ROOT / 'eventos_deadstock_2021_2024.csv'
HIST = ROOT / 'eventos_historicos_pre2021.csv'

def _link(r):
    lk = (r.get('link') or '').strip().lower()
    if lk:
        return lk
    return '_N_' + (r.get('nombre') or '').strip().lower() + '|' + (r.get('fecha') or '').strip()

def _year(r):
    d = (r.get('fecha') or '').strip()
    m = re.match(r'^(\d{4})-\d{2}-\d{2}$', d)
    if m and not re.match(r'^\d{4}-01-01$', d):
        return int(m.group(1))
    return None

def _dump(path, filas, fieldnames):
    prev = []
    if Path(path).exists():
        with open(path, encoding='utf-8') as fh:
            prev = list(csv.DictReader(fh, fieldnames=None))
    seen = {_link(x) for x in prev}
    nuevos = [x for x in filas if _link(x) not in seen]
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction='ignore')
        w.writeheader()
        w.writerows(prev)
        w.writerows(nuevos)
    return len(nuevos)

with csv_locked_rows(CSV, timeout=300) as (rows, fn):
    dead_ids, hist_ids = [], []
    keep = []
    for fr in rows:
        y = _year(fr)
        if y is None:
            keep.append(fr)
        elif y >= 2025:
            keep.append(fr)
        elif y >= 2021:
            dead_ids.append(fr)
        else:
            hist_ids.append(fr)
    n_dead = _dump(DEAD, dead_ids, fn)
    n_hist = _dump(HIST, hist_ids, fn)
    rows[:] = keep
print(f'MAIN: {len(rows)} filas (de {len(rows)+len(dead_ids)+len(hist_ids)})')
print(f'deadstock añadidas (nuevas): {n_dead} | historicas nuevas: {n_hist}')