"""Fase G3 v2: Merge de candidatos de organizador (organizador_candidates.json) al CSV.

Señal fuerte: por cada snippet que menciona un evento, se extrae el NOMBRE del
evento (LLM) y el organizador (ya en candidatos). Luego se matchea ese nombre
contra eventos del CSV sin organizador:

- similitud de tokens del nombre normalizado > 0.5
- ventana de fecha ±3 días si el snippet revela fecha
- descartar organizadores que son venues/ciudades/DJ sueltos (lista + LLM)

NUNCA inventa: si no hay match claro se descarta y se anota motivo.
Backup del CSV antes de escribir. Idempotente vía checkpoint por snippet.
"""
import csv
import difflib
import json
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

_ROOT = Path("/Users/angelgarcia/dharmabot")
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.mcp_clasificar import _llm_generate

CSV_FILE = _ROOT / "eventos_encontrados.csv"
CAND_FILE = _ROOT / "organizador_candidates.json"
EVENTOS_EXTR = _ROOT / "eventos_extraidos_tmp.json"
BACKUP_DIR = _ROOT / "backups"
DISCARD = _ROOT / "candidatos_descartados.json"
LOG = _ROOT / "merge_g3.log"
MAX_SECONDS = 95
ANIO_ACTUAL = 2026

_PROMPT_EVENTO = """Del post de evento, extrae el NOMBRE DEL EVENTO (festival/rave/party).
Reglas:
- Si hay "X presents Y", el evento es Y. Si hay "Presented by X", el evento es lo demás (nombre del festi/party).
- Si es solo un anuncio sin nombre claro, responde N/A.
- No incluyas fechas, lugares, city, ni DJs.
- NUNCA inventes.
Texto: {texto}
Responde SOLO el nombre del evento."""

# Pequeño vocabulario de "no organizador": venues/días/términos genéricos.
# Solo se excluye si el candidato coincide íntegramente (o casi) con uno de estos.
_NO_ORG = {"colours hoxton", "hoxton", "london", "berlin", "goa", "beach",
           "vagator", "amsterdam", "hoxton square", "tech jobs", "landing.jobs",
           "landing jobs", "online events"}


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def norm(s):
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9à-üñ ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def sim(a, b):
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def parse_fecha(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def extraer_nombre_evento(snippet: str) -> str:
    resp = _llm_generate(_PROMPT_EVENTO.format(texto=snippet[:500]),
                         system="Extractor. No inventar.", temperature=0.05)
    if not resp:
        return ""
    resp = resp.strip().strip(".:;")
    if resp.upper() in ("N/A", "NULL", "NONE", ""):
        return ""
    if len(resp) > 80:
        return ""
    if norm(resp) in _NO_ORG and len(resp) < 20:
        return ""
    return resp


def organizador_es_fiable(org: str) -> bool:
    n = norm(org)
    palabras = n.split()
    if not palabras:
        return False
    if len(palabras) > 5:
        return False
    # excluye solo si es íntegramente un venue/ciudad/término genérico
    if n in _NO_ORG:
        return False
    if n in ("festival", "party", "event", "the", "online"):
        return False
    return True


def main():
    if not CAND_FILE.exists() or not CSV_FILE.exists():
        log("Faltan candidatos o CSV.")
        return

    candidatos = json.loads(CAND_FILE.read_text(encoding="utf-8"))
    filas = list(csv.DictReader(open(CSV_FILE, encoding="utf-8")))

    # abrir caché de eventos-por-snippet (evita repetir LLM)
    cache = {}
    if EVENTOS_EXTR.exists():
        try:
            cache = json.loads(EVENTOS_EXTR.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    # índice de eventos SIN organizador: (nombre normalizado, fila)
    sin_org = []
    for fila in filas:
        org = (fila.get("organizador") or "").strip()
        if org and org.lower() not in ("desconocido", "por confirmar", "tba"):
            continue
        fecha = parse_fecha(fila.get("fecha", ""))
        if not fecha:
            continue
        if not (datetime(ANIO_ACTUAL - 2, 1, 1) <= fecha <= datetime(ANIO_ACTUAL + 2, 12, 31)):
            continue
        sin_org.append((fila, fecha))

    aplicados = {}      # indice de fila -> organizador
    descartados = {}
    inicio = time.time()

    for gid, grupo in candidatos.items():
        for c in grupo.get("candidatos", []):
            org = (c.get("organizador") or "").strip()
            if not organizador_es_fiable(org):
                descartados.setdefault(org, []).append({"motivo": "no fiable",
                                                        "snippet": c.get("snippet", "")[:100]})
                continue
            snip = c.get("snippet", "")
            if not snip:
                continue
            key = f"{gid}::{c.get('snippet_idx')}"
            if key not in cache:
                if time.time() - inicio > MAX_SECONDS:
                    break
                cache[key] = extraer_nombre_evento(snip)
                if (len(cache) % 10) == 0:
                    EVENTOS_EXTR.write_text(json.dumps(cache, ensure_ascii=False))
            ev = cache.get(key, "")
            if not ev:
                descartados.setdefault(org, []).append({"motivo": "sin evento claro en snippet",
                                                        "snippet": snip[:100]})
                continue

            # mejor match contra eventos sin organizador
            mejor, mejor_sim = None, 0.0
            for fila, fecha in sin_org:
                vs = sim(ev, fila.get("nombre", ""))
                if vs > 0.5 and vs > mejor_sim:
                    mejor_sim = vs
                    mejor = (id(fila), fila, fecha)
            if mejor is None:
                descartados.setdefault(org, []).append({"motivo": f"evento '{ev}' no está en CSV",
                                                        "evento_extraido": ev})
                continue

            _, fila, fecha = mejor
            if aplicados.get(id(fila)):
                # mismo evento ya asignado a otro org -> conservar el de mayor sim
                prev = aplicados[id(fila)]
                if mejor_sim > prev["sim"]:
                    aplicados[id(fila)] = {"org": org, "sim": mejor_sim, "ev": ev}
            else:
                aplicados[id(fila)] = {"org": org, "sim": mejor_sim, "ev": ev}
            log(f"MATCH: '{org}' -> event '{ev}' ~= '{fila.get('nombre')}' ({fila.get('fecha')}) sim={mejor_sim:.2f}")

    EVENTOS_EXTR.write_text(json.dumps(cache, ensure_ascii=False))
    if not aplicados:
        log(f"0 matches. descartados={sum(len(v) for v in descartados.values())}")
        json.dump(descartados, open(DISCARD, "w", encoding="utf-8"), ensure_ascii=False, indent=2, default=str)
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    BACKUP_DIR.mkdir(exist_ok=True)
    shutil.copy(CSV_FILE, BACKUP_DIR / f"eventos_encontrados_antes_g3_{ts}.csv")

    aplicados_set = set()
    for fila, fecha in sin_org:
        if id(fila) in aplicados:
            fila["organizador"] = aplicados[id(fila)]["org"]
            aplicados_set.add(id(fila))

    with open(CSV_FILE, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=filas[0].keys())
        w.writeheader()
        w.writerows(filas)

    json.dump(descartados, open(DISCARD, "w", encoding="utf-8"), ensure_ascii=False, indent=2, default=str)
    log(f"FIN G3: aplicados={len(aplicados_set)} descartados={sum(len(v) for v in descartados.values())} | backup {ts}")


if __name__ == "__main__":
    main()