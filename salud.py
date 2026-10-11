#!/usr/bin/env python3
"""Healthcheck runtime del pipeline (comprobación constante).

Salida = evidencia, no opinión: CSV/loop/SERP/watchdog. Exit 1 si hay algo roto.
Uso: make salud   (o)   python3 salud.py
"""
import csv
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FALLO = False


def na(v):
    return (v or '').strip().lower() in ('', 'n/a', 'na', 'none', 'null', '-', '?')


def chequear_csv():
    global FALLO
    p = ROOT / 'eventos_encontrados.csv'
    if not p.exists():
        print('CSV: NO EXISTE  <-- acción'); FALLO = True; return
    rows = list(csv.DictReader(p.open(encoding='utf-8')))
    tot = len(rows)
    comp = sum(1 for r in rows if not na(r.get('organizador')) and not na(r.get('email')))
    edad = int((time.time() - p.stat().st_mtime) // 60)
    print(f'CSV: {tot} filas | completados {comp} ({comp/tot*100:.2f}%) | '
          f'última escritura hace {edad} min')
    if edad > 120:
        print('  AVISO: CSV sin cambios >2h (¿loop caído?)'); FALLO = True


def chequear_loop():
    global FALLO
    r = subprocess.run(['pgrep', '-fl', 'loop_completar.py'],
                       capture_output=True, text=True)
    if r.stdout.strip():
        print('loop: VIVO', r.stdout.strip().splitlines()[0][:60])
    else:
        print('loop: MUERTO  <-- acción'); FALLO = True


def chequear_serp():
    global FALLO
    try:
        sys.path.insert(0, str(ROOT))
        from serp_worker import search
        r = search('test', timeout=20)
        print(f"SERP search: status {r['status']} n {len(r['results'])}")
        if r['status'] != 200:
            print('  AVISO: SERP sin 200 (¿Tor/SearXNG caídos?)'); FALLO = True
    except Exception as e:
        print(f'SERP search: EXCEPCIÓN {e}'); FALLO = True


def chequear_searxng():
    global FALLO
    try:
        r = subprocess.run(
            ['docker', 'inspect', 'searxng', '--format',
             'searxng={{.State.Status}} exit={{.State.ExitCode}} '
             'restarts={{.RestartCount}} oom={{.State.OOMKilled}}'],
            capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr.strip())
        if 'running' not in r.stdout:
            print('  AVISO: searxng no running (watchdog debería resucitarlo)')
    except Exception as e:
        print(f'searxng: excepción {e}'); FALLO = True


def main():
    print('== EVIDENCIA DE SALUD DEL PIPELINE ==')
    chequear_csv()
    chequear_loop()
    chequear_serp()
    chequear_searxng()
    inc = ROOT / 'incidents'
    incs = sorted(inc.glob('*.txt')) if inc.exists() else []
    print(f"watchdog: {len(incs)} incidente(s) capturado(s)"
          + (f" (último {incs[-1].name})" if incs else ''))
    print('\n== RESULTADO:', 'CON FALLOS <-- revisar' if FALLO else 'TODO SANO ==')
    return 1 if FALLO else 0


if __name__ == '__main__':
    sys.exit(main())
