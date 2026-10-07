"""Fase 1: Ampliar grupos de Facebook por subgénero × ciudad vía SERP (Tor).

Busca en DuckDuckGo `site:facebook.com/groups {subgenre} {ciudad}` para cada
combinación, extrae grupos reales y los agrega a grupos_encontrados.json
(dedup por id). Checkpoint de combos procesados. Con subprocess+SIGKILL.
"""
import json
import os
import random
import re
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
CHECKPOINT = _ROOT / "grupos_fase1_checkpoint.json"
LOG_FILE = _ROOT / "grupos_fase1.log"
CONFIG = _ROOT / "config_fase1.json"

TOR_SEMAPHORE = None
HARD_TIMEOUT = 20
ROTATE_EVERY = 10
MAX_SECONDS = 95

logger = None


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
        return {}
    try:
        data = json.loads(GRUPOS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "groups" in data:
            return {g["id"]: g for g in data["groups"]}
        if isinstance(data, list):
            return {g["id"]: g for g in data}
        return {v["id"]: v for v in data.values() if isinstance(v, dict) and "id" in v}
    except Exception:
        return {}


def guardar_grupos(grupos):
    tmp = GRUPOS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"groups": list(grupos.values())}, ensure_ascii=False, indent=2))
    tmp.replace(GRUPOS_FILE)


def slug(text):
    import unicodedata
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    return text.lower().replace(" ", "").replace("-", "")


def _id_de_url(url):
    m = re.search(r"facebook\.com/groups/([^/?]+)", url)
    return m.group(1).split("/")[0] if m else None


def clasificar_psy(nombre, url):
    t = f"{nombre} {url}".lower()
    subgenero = None
    for key in ("darkpsy", "dark psy", "forest", "goa", "hitech", "suomi",
                "psychill", "psytrance", "psy trance", "psychedelic", "progressive"):
        if key in t:
            subgenero = key.replace(" psy", "").replace("psychedelic", "psytrance")
            break
    return subgenero or "psytrance"


def main():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    subgeneros = config.get("subgeneros", ["psytrance"])
    ciudades = config.get("ciudades", [])[:5]

    grupos = cargar_grupos()
    checkpoint = {}
    if CHECKPOINT.exists():
        try:
            checkpoint = json.loads(CHECKPOINT.read_text())
        except Exception:
            checkpoint = {}

    combinaciones = []
    for sub in subgeneros:
        for ciudad in ciudades:
            key = f"{sub}::{ciudad}"
            if key not in checkpoint.get("hechas", []):
                combinaciones.append((key, sub, ciudad))

    if not combinaciones:
        log("TODAS las combinaciones hechas. Saliendo.")
        return

    log(f"Cargadas: {len(grupos)} grupos. {len(combinaciones)} combos pendientes.")
    hechas = checkpoint.get("hechas", [])
    nuevos = 0
    inicio = time.time()
    for i, (key, sub, ciudad) in enumerate(combinaciones):
        if time.time() - inicio > MAX_SECONDS:
            log(f"Tope {MAX_SECONDS}s. Guardando {nuevos} nuevos...")
            break
        query = f"site:facebook.com/groups {sub} {ciudad}"
        if i % ROTATE_EVERY == 0 and i > 0:
            rotar_tor()
        resp = fetch_serp(query)
        cnt = 0
        if resp.get("status") == 200:
            for r in resp.get("results", []):
                url = r.get("url", "")
                if not url:
                    continue
                gid = _id_de_url(url)
                if not gid or gid in grupos:
                    continue
                nombre = r.get("titulo", "") or gid
                if "auxiliary" in nombre[:15]:
                    continue
                if not re.search(r"psy|trance|goa|dark|forest|hi|ritual", f"{nombre} {sub} {ciudad}", re.I):
                    continue
                grupos[gid] = {
                    "id": gid,
                    "nombre": nombre[:80].replace(" - Facebook", "").strip(),
                    "url": f"https://facebook.com/groups/{gid}",
                    "tipo_grupo": [clasificar_psy(nombre, url)],
                    "fuente": "Fase1_SERP",
                    "query": query,
                }
                nuevos += 1
                cnt += 1
            log(f"[{key}] {respoaci_ok(len(resp['results']))}: {cnt} nuevos")
        else:
            log(f"[{key}] status={resp.get('status')} err={resp.get('error')}")
        hechas.append(key)
        if (i + 1) % 5 == 0:
            guardar_grupos(grupos)
            CHECKPOINT.write_text(json.dumps({"hechas": hechas}))
            log(f"CHECKPOINT: {len(grupos)} grupos, {nuevos} nuevos")
        time.sleep(random.uniform(6, 10))

    guardar_grupos(grupos)
    CHECKPOINT.write_text(json.dumps({"hechas": hechas}))
    log(f"FIN Fase1: grupos={len(grupos)} nuevos={nuevos} combos={len(hechas)}")


def respoaci_ok(n):
    return n


if __name__ == "__main__":
    main()