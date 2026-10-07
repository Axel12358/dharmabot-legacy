#!/bin/bash
# Loop Brasil — no satura: batch 5 + 30s pausa + 10s entre requests
cd "$(dirname "$0")"
while true; do
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] === ciclo Brasil ===" >> loop_brasil.log
  /Users/angelgarcia/dharmabot/.venv/bin/python loop_brasil.py >> loop_brasil.log 2>&1
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] pausa 300s" >> loop_brasil.log
  sleep 300
done
