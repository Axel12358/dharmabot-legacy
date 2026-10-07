#!/usr/bin/env python3
"""Genera el reporte profesional del dataset global (reporte_datos.md y
estado_datos.csv) a partir de eventos_encontrados.csv y archivos históricos."""
import collections
import csv
import re
from pathlib import Path

ROOT = Path(__file__).parent
EM = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def leer(csv_path):
    if not csv_path.exists():
        return []
    return list(csv.DictReader(open(csv_path, encoding='utf-8')))


def pct(n, m):
    return 100.0 * n / m if m else 0.0


def pluck(rows, campo):
    val = collections.Counter()
    for r in rows:
        v = (r.get(campo) or '').strip()
        if not v or v.lower() == 'n/a' or v.lower() == 'nan':
            continue
        val[v] += 1
    return val


def main():
    main_rows = leer(ROOT / 'eventos_encontrados.csv')
    dead = leer(ROOT / 'eventos_deadstock_2021_2024.csv')
    hist = leer(ROOT / 'eventos_historicos_pre2021.csv')
    nop = leer(ROOT / 'non_psy.csv')
    n = len(main_rows)
    e = sum(1 for r in main_rows if EM.match((r.get('email') or '').strip()))
    o = sum(1 for r in main_rows if not (r.get('organizador') or '').strip().lower() in ('', 'n/a'))
    ph = sum(1 for r in main_rows if re.match(r'^\d{4}-01-01$', (r.get('fecha') or '').strip()))

    by_year = pluck(main_rows, 'fecha')
    year_final = {}
    for k, c in by_year.items():
        year_final[k[:4]] = year_final.get(k[:4], 0) + c
    by_cont = pluck(main_rows, 'continente')
    by_sub = pluck(main_rows, 'subgenero')
    by_fuente = pluck(main_rows, 'fuente')
    by_ciudad = pluck(main_rows, 'lugar')
    by_tipo = pluck(main_rows, 'tipo_lugar')

    org_cnt = pluck(main_rows, 'organizador')
    gmail = sum(1 for r in main_rows if EM.match((r.get('email') or '').strip())
                and (r.get('email') or '').split('@')[1].startswith(('gmail', 'hotmail', 'outlook', 'yahoo')))

    fechas_validas = sum(1 for r in main_rows
                         if re.match(r'^\d{4}-\d{2}-\d{2}$', (r.get('fecha') or '').strip())
                         and not re.match(r'^\d{4}-01-01$', (r.get('fecha') or '').strip()))
    con_email_org = sum(1 for r in main_rows
                        if EM.match((r.get('email') or '').strip())
                        and not (r.get('organizador') or '').strip().lower() in ('', 'n/a'))

    lines = []
    w = lambda s='': lines.append(s)
    w('# Reporte del dataset — dharmabot')
    w()
    w('_Generado automáticamente (script `generar_reporte.py`). Sin modificar datos._')
    w()
    w('## Resumen global')
    w()
    w('| Campo | Valor |')
    w('|---|---|')
    w(f'| Eventos 2025-2028 (producción) | **{n}** |')
    w(f'| Eventos 2021-2024 (archivo) | {len(dead)} |')
    w(f'| Eventos ≤2020 (histórico) | {len(hist)} |')
    w(f'| No-psy / ruido clasificado | {len(nop)} |')
    w(f'| **Total del pipeline** | **{n + len(dead) + len(hist) + len(nop)}** |')
    w()
    w('## Cobertura de campos (dataset global)')
    w()
    w('| Campo | Cobertura | Pendiente |')
    w('|---|---|---|')
    w(f'| Organizador | {o} ({pct(o, n):.2f}%) | {n - o} |')
    w(f'| Email válido | {e} ({pct(e, n):.2f}%) | {n - e} |')
    w(f'| Fecha específica (día) | {fechas_validas} ({pct(fechas_validas, n):.2f}%) | {ph} |')
    w(f'| Fila completa (org + email) | {con_email_org} ({pct(con_email_org, n):.2f}%) | {n - con_email_org} |')
    w(f'| Email dominio propio (no gmail/…) | {e - gmail} | — |')
    w()
    w('## Por año')
    w()
    w('| Año | Eventos |')
    w('|---|---|')
    for a in sorted(year_final, reverse=True):
        w(f'| {a} | {year_final[a]} |')
    w()
    w('## Por continente')
    w()
    w('| Continente | Eventos | % |')
    w('|---|---|---|')
    for c_, cv in by_cont.most_common(8):
        w(f'| {c_} | {cv} | {pct(cv, n):.1f}% |')
    w()
    w('## Por subgénero (top 15)')
    w()
    w('| Subgénero | Eventos |')
    w('|---|---|')
    for s, sv in by_sub.most_common(15):
        w(f'| {s} | {sv} |')
    w()
    w('## Por ciudad (top 20)')
    w()
    w('| Ciudad | Eventos |')
    w('|---|---|')
    for ci, civ in by_ciudad.most_common(20):
        w(f'| {ci} | {civ} |')
    w()
    w('## Top 20 organizadores')
    w()
    w('| Organizador | Eventos |')
    w('|---|---|')
    for org, oc in org_cnt.most_common(20):
        w(f'| {org} | {oc} |')
    w()
    w('## Por fuente')
    w()
    w('| Fuente | Eventos |')
    w('|---|---|')
    for f_, fv in by_fuente.most_common(8):
        w(f'| {f_} | {fv} |')
    w()
    w('## Tipo de lugar')
    w()
    for t, tv in by_tipo.most_common(10):
        w(f'- **{t or "sin dato"}**: {tv}')
    w()
    w('---')
    w()
    w('Resumen:\n')
    w(f'- **{n}** eventos en producción (2025-2028).')
    w(f'- Organizador al **{pct(o, n):.1f}%**, email al **{pct(e, n):.1f}%**, fecha al **{pct(fechas_validas, n):.1f}%**.')
    w(f'- {ph} fechas pendientes por muro de login de Facebook (se mantienen sin inventar).')
    (ROOT / 'reporte_datos.md').write_text('\n'.join(lines), encoding='utf-8')

    import json
    estado = {
        'total': n, 'con_organizador': o, 'con_email': e,
        'fecha_especifica': fechas_validas, 'fecha_pendiente': ph,
        'fila_completa': con_email_org,
        'archivo_2021_2024': len(dead), 'historico_pre2021': len(hist),
        'no_psy': len(nop),
    }
    (ROOT / 'estado_datos.json').write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Reporte: {ROOT / "reporte_datos.md"}  estado: {ROOT / "estado_datos.json"}')


if __name__ == '__main__':
    main()