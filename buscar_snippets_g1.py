"""Fase G1: Descubrir hosts/posts de grupos FB vía SERP (DDG, Tor).

Para cada grupo en grupos_encontrados.json lanza queries tipo
  site:facebook.com/groups/{id} "hosted by" / "organized by" / events / permalink
y guarda snippets en grupos_snippets.json (checkpoint por grupo + query).

Posteriormente la Fase G2 extraerá el host de los snippets con regex + LLM.
Patrón: subprocess+SIGKILL (curl_cffi Tor), rotación Tor cada N, bloques de 95s.
"""
import json
import os
import random
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

_ROOT = Path("/Users/angelgarcia/dharmabot")
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

VENV_PY = str(_ROOT / ".venv/bin/python")
WORKER = str(_ROOT / "serp_worker.py")
GRUPOS_FILE = _ROOT / "grupos_encontrados.json"
SNIPPETS_FILE = _ROOT / "grupos_snippets.json"
CHECKPOINT = _ROOT / "grupos_g1_checkpoint.json"
LOG_FILE = _ROOT / "grupos_g1.log"

HARD_TIMEOUT = 20
ROTATE_EVERY = 8
MAX_SECONDS = 95
QUERIES_POR_GRUPO = 3
SLEEP_MIN, SLEEP_MAX = 6, 10


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def rotar_tor():
    try:
        from core.tor_manager import renovar_identidad_tor
        renovar_identidad_tor()
        log("Tor rotado")
    except Exception as e:
        log(f"Tor rotation fail: {e}")


def fetch_serp(query: str) -> dict:
    try:
        proc = subprocess.Popen(
            [VENV_PY, WORKER, query, str(HARD_TIMEOUT)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(_ROOT),
        )
        try:
            stdout, _ = proc.communicate(timeout=HARD_TIMEOUT)
            if proc.returncode != 0:
                return {"status": 0, "results": [], "error": "exit"}
            return json.loads(stdout.decode())
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                proc.kill()
            return {"status": 0, "results": [], "error": "HARD_TIMEOUT"}
    except Exception as e:
        return {"status": 0, "results": [], "error": str(e)[:100]}


def cargar_grupos():
    if not GRUPOS_FILE.exists():
        return []
    try:
        data = json.loads(GRUPOS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "groups" in data:
            return data["groups"]
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def cargar_snippets():
    if not SNIPPETS_FILE.exists():
        return {}
    try:
        return json.loads(SNIPPETS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def guardar_snippets(data):
    tmp = SNIPPETS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(SNIPPETS_FILE)


def _id_de_url(url):
    m = re_search_groups(url)
    return m.split("/")[0] if m else None


def re_search_groups(url):
    import re
    m = re.search(r"facebook\.com/groups/([^/?#]+)", url)
    return m.group(1) if m else None


def es_snippet_util(snip):
    """Snippet con señal de evento/host."""
    s = snip.lower()
    señales = ["organiz", "host", "present", "event", "festival", "party",
               "rave", "gathering", "open air", "by ", "line up", "lineup"]
    return any(x in s for x in señales)


def main():
    grupos = cargar_grupos()
    if not grupos:
        log("Sin grupos. Fin.")
        return

    snippets = cargar_snippets()
    ckpt = {}
    if CHECKPOINT.exists():
        try:
            ckpt = json.loads(CHECKPOINT.read_text())
        except Exception:
            ckpt = {}
    hechas = set(ckpt.get("hechas", []))

    # Cola pendiente: por cada grupo un subíndice de query (0..QUERIES_POR_GRUPO-1)
    queries_plan = []
    for g in grupos:
        gid = g.get("id") or _id_de_url(g.get("url", ""))
        if not gid:
            continue
        for q in range(QUERIES_POR_GRUPO):
            key = f"{gid}::q{q}"
            if key not in hechas:
                queries_plan.append((key, gid, q, g.get("nombre", ""), g.get("url", "")))

    random.shuffle(queries_plan)
    log(f"Grupos: {len(grupos)} | Pendientes: {len(queries_plan)}")
    if not queries_plan:
        log("TODO procesado. Fin.")
        return

    plantillas = [
        'site:facebook.com/groups/{gid} "organized by" OR "hosted by" OR "presents" psytrance',
        'site:facebook.com/groups/{gid}/events psytrance',
        'site:facebook.com/groups/{gid} festival gathering party',
    ]

    nuevos_snippets = 0
    reqs_ok = 0
    reqs_block = 0
    inicio = time.time()

    for i, (key, gid, q, nombre, url) in enumerate(queries_plan):
        if time.time() - inicio > MAX_SECONDS:
            log(f"Tope {MAX_SECONDS}s. Guardando {nuevos_snippets} snippets nuevos...")
            break

        query = plantillas[q].format(gid=gid)

        if i % ROTATE_EVERY == 0 and i > 0:
            rotar_tor()

        resp = fetch_serp(query)
        cnt = 0
        if resp.get("status") == 200:
            reqs_ok += 1
            gkey = gid
            if gkey not in snippets:
                snippets[gkey] = {"id": gid, "nombre": (nombre or "")[:100],
                                  "url": url, "snippets": []}
            for r in resp.get("results", []):
                snip = r.get("snippet", "")
                if not snip or not es_snippet_util(snip):
                    continue
                # Evitar duplicar el mismo snippet exacto
                if snip in [s["snippet"] for s in snippets[gkey]["snippets"]]:
                    continue
                snippets[gkey]["snippets"].append({
                    "url": r.get("url", ""),
                    "titulo": (r.get("titulo", "") or "")[:120],
                    "snippet": snip[:600],
                    "query": f"q{q}",
                })
                nuevos_snippets += 1
                cnt += 1
        elif resp.get("status") == 403 or resp.get("error") == "blocked":
            reqs_block += 1
        hechas.add(key)

        if i % 4 == 0:
            guardar_snippets(snippets)
            CHECKPOINT.write_text(json.dumps({"hechas": sorted(hechas)}))

        if nuevos_snippets and (i % 8 == 0 or nuevos_snippets % 20 == 0):
            log(f"[{i}] snippets={len(snippets)} nuevos={nuevos_snippets} ok={reqs_ok} block={reqs_block}")
        time.sleep(random.uniform(SLEEP_MIN, SLEEP_MAX))

    guardar_snippets(snippets)
    CHECKPOINT.write_text(json.dumps({"hechas": sorted(hechas)}))
    log(f"FIN G1: grupos=con_snippets={sum(1 for v in snippets.values() if v['snippets'])} "
        f"snippets={nuevos_snippets} ok={reqs_ok} block={reqs_block} pendientes={len(queries_plan)}")


if __name__ == "__main__":
    main()