#!/bin/bash
# Watchdog Dharmadhatu — mantiene matriz + searxng vivos y en cola.
# 1) Si searxng no devuelve resultados google (engines suspendidos) → reinicio.
# 2) Si la matriz no está corriendo y quedan seeds → lanza la siguiente tanda.
# 3) Log en estado_runtime/watchdog.log (persistente, sobrevive reinicios).
#
# Estado persistente (estado_runtime/, NO en /tmp):
#   - current=N            : round en curso (1..ROUNDS_TOTAL) o 0 si ninguno.
#   - rounds_completados.txt : rounds cuya log llegó a [2000/2000] (1 línea c/u).
# Con esto, tras un apagado/reboot el watchdog reanuda el round que quedó
# pendiente en vez de saltarlo o empezar de cero.
cd "/Users/angelgarcia/dharmabot" || exit 1

SEEDS=(13 17 23 29)
ROUNDS_TOTAL=4
CORE="/Users/angelgarcia/dharmabot/estado_runtime"
STATE="$CORE/watchdog_state.txt"
DONE="$CORE/rounds_completados.txt"
LOG="$CORE/watchdog.log"
RESTART_TS="$CORE/searxng_ultimo_restart.txt"
LAUNCHER="$CORE/lanzar_matriz.py"
MATRIZ_PID="$CORE/matriz.pid"
COOLDOWN_S=1500  # espera mínima entre reinicios de Docker (25 min)
mkdir -p "$CORE"

log() { echo "[$(date '+%H:%M:%S')] $*" >> "$LOG"; }

# init estado
if [ ! -f "$STATE" ]; then
  echo "current=0" > "$STATE"
fi
current=$(grep current "$STATE" 2>/dev/null | cut -d= -f2)
current=${current:-0}
touch "$DONE"

probe_searxng() {
  # Solo google (engine crítico). Devuelve:
  #   OK        → google respondió sin error (aunque traiga 0 resultados fb;
  #               eso es una query legítima sin matches, NO un bloqueo)
  #   BAD:<msg> → google en unresponsive_engines (403/429/suspendido/rechazo)
  #   ERR       → searxng/Docker no respondieron (contener caído)
  local out
  out=$(curl -s -m 25 "http://localhost:8888/search?q=site%3Afacebook.com%2Fevents+psytrance+Berlin&format=json&engines=google" 2>/dev/null)
  echo "$out" | python3 -c "import sys,json
try:
  d=json.load(sys.stdin)
  if not isinstance(d, dict) or 'results' not in d:
    print('ERR'); sys.exit()
  bad=[u for u in d.get('unresponsive_engines',[])
       if (u.get('engine') if isinstance(u, dict) else u[0])=='google']
  if bad:
    raw=bad[0]
    msg=raw.get('message') if isinstance(raw, dict) else (str(raw[1]) if len(raw)>1 else str(raw))
    print('BAD:'+str(msg)[:90])
  else:
    print('OK')
except Exception:
  print('ERR')"
}

probe_startpage() {
  # Fallback: si google está caído pero startpage responde, docker NO se reinicia
  # (el contenedor está sano; solo el engine google está suspendido).
  local out n
  out=$(curl -s -m 25 "http://localhost:8888/search?q=site%3Afacebook.com%2Fevents+psytrance+Berlin&format=json&engines=startpage" 2>/dev/null)
  n=$(echo "$out" | python3 -c "import sys,json
try:
  d=json.load(sys.stdin); print(sum(1 for x in d.get('results',[]) if 'facebook.com' in x.get('url','')))
except: print(0)")
  [ "$n" -ge 1 ]
}

intentar_reiniciar() {
  # Cooldown anti-loop de reinicios: google marca a IPs que reconectan
  # cada 3-5 min como sospechosas. Esperamos ≥25 min entre reinicios.
  now=$(date +%s)
  last_restart=$(cat "$RESTART_TS" 2>/dev/null || echo 0)
  elapsed=$((now - last_restart))
  if [ "$elapsed" -lt "$COOLDOWN_S" ]; then
    log "cooldown reinicio Docker: ${elapsed}s de ${COOLDOWN_S}s → sin reinicio"
    fail_count=0
  else
    log "REINICIANDO searxng (último hace ${elapsed}s)..."
    docker restart searxng >/dev/null 2>&1
    date +%s > "$RESTART_TS"
    fail_count=0
    sleep 20
  fi
}

round_completado() {
  # 0 si la round $1 tiene log con [2000/2000] (terminó), 1 si aún no
  local rl="$CORE/matriz_round${1}.log"
  [ -f "$rl" ] && rg -q '\[2000/2000\]' "$rl"
}

next_round_pendiente() {
  # devuelve el número de round (1..ROUNDS_TOTAL) sin completar, o 0 si todos hechos
  local i
  for i in $(seq 1 $ROUNDS_TOTAL); do
    if ! grep -qx "$i" "$DONE" 2>/dev/null; then
      echo "$i"
      return
    fi
  done
  echo 0
}

matriz_viva() {
  # 0 si la matriz corre (por PID file, no pgrep — distingue procesos)
  [ -f "$MATRIZ_PID" ] && kill -0 "$(cat "$MATRIZ_PID" 2>/dev/null)" 2>/dev/null
}

while true; do
  # --- searxng health ---
  probe_out=$(probe_searxng)
  case "$probe_out" in
    OK)
      # google responde (aunque traiga 0 fb: query legítima, no bloqueo)
      fail_count=0
      ;;
    BAD:*)
      # google rechazado/suspendido: reiniciamos SOLO si startpage también
      # falla (contenedor realmente enfermo). Detalle del motivo en el log.
      motivo=${probe_out#BAD:}
      if probe_startpage; then
        log "google rechazado: ${motivo} → startpage responde, sin reinicio (fallo $fail_count)"
        fail_count=$((fail_count+1))
        [ "$fail_count" -ge 4 ] && fail_count=3
      else
        fail_count=$((fail_count+1))
        log "google rechazado (${motivo}) y startpage caído → fallo $fail_count/3"
        if [ "$fail_count" -ge 3 ]; then
          intentar_reiniciar
        fi
      fi
      ;;
    *)
      # ERR: searxng no responde (contenedor caído), fallo real
      fail_count=$((fail_count+1))
      log "searxng sin respuesta HTTP (fallo $fail_count/3)"
      if [ "$fail_count" -ge 3 ]; then
        intentar_reiniciar
      fi
      ;;
  esac

  # --- matriz ---
  if ! matriz_viva; then
    # Si el round actual ya terminó su log → marcarlo como completado
    if [ "$current" -ge 1 ] && [ "$current" -le "$ROUNDS_TOTAL" ] && round_completado "$current"; then
      echo "$current" >> "$DONE"
      log "Round $current completado y marcado"
      echo "current=0" > "$STATE"
      current=0
    fi

    nxt=$(next_round_pendiente)
    if [ "$nxt" -ge 1 ]; then
      idx=$((nxt-1))
      seed=${SEEDS[$idx]}
      echo "current=$nxt" > "$STATE"
      log "Lanzando matriz round $nxt (semilla $seed, 2000 dorks, sesión own)"
      # setsid portable (macOS no trae setsid(1)): la matriz se daemoniza y
      # escribe su PID; la muerte del watchdog ya no la arrastra.
      .venv/bin/python "$LAUNCHER" --presupuesto 2000 --semilla "$seed" --ejecutar >> "$CORE/matriz_round${nxt}.log" 2>&1 &
    else
      : # rounds agotados → enriquecimiento lo cubre loop_completar (daemon
        # independiente vía DDG). La fase 2 de dorks vía searxng/google daba
        # 0 emails y quemaba la sesión de google → DESACTIVADA.
    fi
  fi

  sleep 45
done