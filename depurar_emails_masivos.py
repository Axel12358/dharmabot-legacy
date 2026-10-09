#!/usr/bin/env python3
"""Depura emails por defecto/repetidos que NO son del organizador.

Reversible y no destructivo:
  - Backup timestamped del CSV antes de escribir.
  - Cada email quitado se guarda en email_cuarentena.json (clave estable -> original).
  - Solo se VACÍA la celda; ninguna fila se borra.
  - Conserva emails tipo serie/artista (repetidos pero plausibles).

Criterio de cuarentena (solo basura inequívoca):
  - alteredstatepsy@gmail.com salvo filas cuyo org/nombre mencione "altered state".
  - plantillas (votre@email.fr), antiphishing (apwg), pasarelas (khalti),
    periodistas (newcastleherald), departamentos legales (partyx legal).

Uso:  python depurar_emails_masivos.py [--apply]
"""
import argparse
import json
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, '/Users/angelgarcia/dharmabot')
from core.csv_lock import csv_locked_rows          # noqa: E402
from core.emails_guard import es_email_basura      # noqa: E402

CSV = Path('/Users/angelgarcia/dharmabot/eventos_encontrados.csv')
CUARENTENA = Path('/Users/angelgarcia/dharmabot/email_cuarentena.json')


def _clave(r):
    link = (r.get('link') or '').strip()
    if link:
        return 'link:' + link
    return 'nm:' + '|'.join((r.get(c) or '').strip().lower()
                            for c in ('nombre', 'fecha', 'lugar'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--sin-backup', action='store_true',
                    help='no crear backup (para auto-sanado periódico en el loop)')
    args = ap.parse_args()

    with csv_locked_rows(str(CSV)) as (todas, fieldnames):
        cuarentena = {}
        motivos = Counter()
        for r in todas:
            e = (r.get('email') or '').strip().lower()
            if not e or e == 'n/a':
                continue
            if es_email_basura(e, r):
                motivo = ('default_masivo' if 'alteredstatepsy' in e
                          else 'basura') + ':' + e
                cuarentena[_clave(r)] = {'email': (r.get('email') or '').strip(),
                                         'motivo': motivo,
                                         'nombre': (r.get('nombre') or '')[:80],
                                         'organizador': (r.get('organizador') or '')[:80]}
                motivos[motivo] += 1

        print(f'a cuarentena: {len(cuarentena)} emails')
        for m, c in motivos.most_common():
            print(f'   {c:6d}  {m}')

        if not args.apply:
            print('(dry-run — usa --apply para escribir; se hará backup previo)')
            return

        if not args.sin_backup:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup = CSV.with_name(f'backup_{ts}_pre_depuracion_emails.csv')
            shutil.copy2(CSV, backup)
            print('backup:', backup.name)

        if cuarentena:
            if CUARENTENA.exists():
                prev = json.loads(CUARENTENA.read_text(encoding='utf-8'))
                prev.update(cuarentena)
                cuarentena = prev
            CUARENTENA.write_text(json.dumps(cuarentena, ensure_ascii=False, indent=1),
                                  encoding='utf-8')

        gan = 0
        for r in todas:
            e = (r.get('email') or '').strip().lower()
            if e and es_email_basura(e, r):
                r['email'] = ''
                gan += 1
        print(f'APLICADO: {gan} celdas de email vaciadas (originales en {CUARENTENA.name})')


if __name__ == '__main__':
    main()
