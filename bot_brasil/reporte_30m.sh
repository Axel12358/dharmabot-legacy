#!/bin/bash
# Reporte Brasil cada 30 min -> bot_brasil/reporte_30m.log
BASE="/Users/angelgarcia/dharmabot/bot_brasil"
PY="/Users/angelgarcia/dharmabot/.venv/bin/python"
while true; do
  sleep 1800
  echo "=== REPORTE BRASIL $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$BASE/reporte_30m.log"
  $PY -c "
import csv
rows=list(csv.DictReader(open('$BASE/eventos_brasil.csv',encoding='utf-8')))
tot=len(rows)
org=sum(1 for r in rows if (r.get('organizador') or '').strip() not in ('','N/A',''))
email=sum(1 for r in rows if (r.get('email') or '').strip() not in ('','N/A',''))
under=sum(1 for r in rows if 'tba' in (r.get('tipo_lugar') or '').lower() or 'underground' in (r.get('descripcion') or '').lower())
print(f'BRASIL: total {tot} org {org} {org*100//max(tot,1)}% email {email} {email*100//max(tot,1)}% underground {under}')
" >> "$BASE/reporte_30m.log" 2>&1
  tail -2 "$BASE/loop_brasil.log" 2>/dev/null | cut -c1-110 >> "$BASE/reporte_30m.log"
  echo "---" >> "$BASE/reporte_30m.log"
done
