#!/bin/bash
# Watchdog de SearXNG: si el contenedor no responde, CAPTURA EVIDENCIA
# (estado + logs del último aliento) y lo resucita. Nada de resucitar a ciegas.
# Log de cada incidente: incidents/searxng_YYYYmmdd_HHMMSS.txt
cd "$(dirname "$0")" || exit 1
STAMP=$(date +%Y%m%d_%H%M%S)
LOG_DIR=incidents
mkdir -p "$LOG_DIR"

if /usr/local/bin/docker inspect -f '{{.State.Status}}' searxng 2>/dev/null |
    grep -q running; then
    # arriba: ¿responde HTTP de verdad?
    if curl -s -o /dev/null -w '%{http_code}' -m 8 \
        'http://127.0.0.1:8888/search?q=test&format=json' | grep -q '200'; then
        exit 0
    fi
    # container "running" pero web caída: evidenciarlo igual
    INC="${LOG_DIR}/searxng_${STAMP}.txt"
    {
        echo "== web muerta con contenedor 'running' $STAMP =="
        /usr/local/bin/docker inspect searxng --format \
            'estado={{.State.Status}} iniciado={{.State.StartedAt}} finalizado={{.State.FinishedAt}} restarts={{.RestartCount}} policy={{.HostConfig.RestartPolicy.Name}}'
        echo '== logs últimos 80 =='
        /usr/local/bin/docker logs searxng --tail 80 2>&1
    } >>"$INC" 2>&1
    exit 0
fi

# contenedor caído: capturar TODO antes de resucitar → causa raíz
INC="${LOG_DIR}/searxng_${STAMP}.txt"
{
    echo "== searxng CAÍDO $STAMP =="
    /usr/local/bin/docker inspect searxng --format \
        'estado={{.State.Status}} exit={{.State.ExitCode}} iniciado={{.State.StartedAt}} finalizado={{.State.FinishedAt}} restarts={{.RestartCount}} oom={{.State.OOMKilled}}'
    echo '-- docker logs (tail 80) --'
    /usr/local/bin/docker logs searxng --tail 80 2>&1
    echo '-- motores Tor vivos? --'
    timeout 5 bash -c 'echo > /dev/tcp/127.0.0.1/9052 && echo tor-9052 OK || echo tor-9052 MUERTO' 2>/dev/null || echo 'tor-9052 MUERTO'
} >>"$INC" 2>&1

/usr/local/bin/docker start searxng >>"$INC" 2>&1
echo "SearXNG resucitado — incidente: $INC"