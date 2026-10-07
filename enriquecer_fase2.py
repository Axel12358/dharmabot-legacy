"""Fase 2: Enriquecer organizador de eventos FB sin organizador vía SERP.

Para cada evento con link facebook.com/events/ y sin organizador:
1. Buscar en DDG el nombre del evento (quoted) + facebook
2. Parsear el snippet: "Event in <lugar> by <ORGANIZER> on <fecha>"
3. Validar coherencia: fecha del evento coincide (±2 días) si es posible;
   si no, al menos el URL del resultado apunta a facebook.com/events/
4. Aplicar el mejor organizador al CSV

Checkpoint por link. Escribir CSV incremental. subprocess+SIGKILL. Tor.
"""
import csv
import json
import os
import random
import re
import signal
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

_ROOT = Path("/Users/angelgarcia/dharmabot")
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

VENV_PY = str(_ROOT / ".venv/bin/python")
WORKER = str(_ROOT / "serp_worker.py")
CSV_PATH = _ROOT / "eventos_encontrados.csv"
CHECKPOINT = _ROOT / "fase2_checkpoint.json"
LOG_FILE = _ROOT / "fase2.log"

HARD_TIMEOUT = 20
ROTATE_EVERY = 10
CHECKPOINT_EVERY = 10
MAX_SECONDS = 95
VACIOS = {"", "N/A", "None", "nan", "NA", "NONE"}
parses_exitos = 0
parses_totales = 0


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
    except Exception as exc:
        return {"status": 0, "results": [], "error": str(exc)[:100]}


def _normalizar_fecha(f):
    f = (f or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(f[:10], fmt)
        except ValueError:
            pass
    m = re.match(r"(\d{4})-(\d{2})", f)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), 15)
        except ValueError:
            return None
    return None


def _fecha_de_snippet(s):
    m = re.search(
        r"\b(?:jan\.?|january|feb\.?|february|mar\.?|march|apr\.?|april|may|jun\.?|june|jul\.?|july|aug\.?|august|sep\.?|sept\.?|september|oct\.?|october|nov\.?|november|dec\.?|december)"
        r"\s+\d{1,2},?\s+(\d{4})",
        s, re.I,
    )
    if not m:
        return None
    mes = m.group(0).split()[0]
    dia = re.search(r"\d{1,2}", m.group(0)).group(0)
    anio = m.group(1)
    meses = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
             "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
    mid = mes.lower().replace(".", "")[:3]
    try:
        return datetime(int(anio), meses[mid], int(dia))
    except ValueError:
        return None


def _organizador_de_snippet(s):
    # Patrón A: "Event in <lugar> by <ORG> on <fecha>"
    m = re.search(
        r"\b(?:Event|Dance event|Art event|Music event|Live music event|Party|Outdoor event)"
        r"\s+in\s+.+?\bby\s+([^·\n]{0,80}?)(?=\s+on\s+\w+\s+\d|\s+and\s+\d|\s*$)",
        s, re.I,
    )
    if m:
        org = m.group(1).strip().rstrip(".,;")
        org = re.split(r"\s+on\s+|\s+and\s+\d+|\s+\d+\s+others?", org, flags=re.I)[0].strip()
        org = org.strip(",.")
        # FB muestra "X and Y" -> quedarse con el primer perfil principal
        org = re.split(r"\s+and\s+", org, flags=re.I)[0].strip() if re.search(r"\sand\s", org, re.I) else org
        if 3 <= len(org) <= 60 and not re.search(r"\d{5}", org):
            return org
    # Patrón B: "Public · Hosted by <ORG> <fecha>"
    m2 = re.search(r"Hosted\s+by\s+([^·\n]{0,80}?)(?=\s+(?:on|Saturday|Sunday|Monday|Tuesday|Wednesday|Thursday|Friday)\b|\s*$)",
                   s, re.I)
    if m2:
        org = m2.group(1).strip().rstrip(".,;")
        if 3 <= len(org) <= 60 and not re.search(r"\d{5}", org):
            return org
    return None


def _organizador_de_url(url):
    """facebook.com/<perfil>/posts/... -> el perfil suele ser el organizador."""
    try:
        dec = urllib.parse.unquote(url)
        m = re.search(r"facebook\.com/(?:www\.)?([\w.\-]+)/(?:posts|events|videos)/", dec)
        if not m:
            return None
        perfil = m.group(1)
        if perfil.lower() in ("groups", "events", "pages", "share", "profile", "home", "p", "stories"):
            return None
        perfil = perfil.replace("-", " ").replace(".", " ").strip()
        perfil = re.sub(r"\s+", " ", perfil).title()
        if 3 <= len(perfil) <= 60 and perfil.isascii():
            return perfil
    except Exception:
        pass
    return None


def parsear_resultado(r):
    global parses_exitos, parses_totales
    parses_totales += 1
    org = _organizador_de_snippet(r.get("snippet", ""))
    if not org:
        org = _organizador_de_url(r.get("url", ""))
    if org and any(x in r.get("url", "") for x in ("facebook.com/events", "facebook.com/groups",
                                                   "facebook.com/", "/posts/", "/events/", "/videos/")):
        parses_exitos += 1
        return org
    return None


def _slug_query(link):
    """Extrae el nombre real del evento desde el slug de la URL."""
    try:
        dec = urllib.parse.unquote(link)
        m = re.search(r"/events/(.+?)/?\d+(?:/.*)?$", dec)
        if not m:
            return None
        segs = [s for s in m.group(1).split("/") if s and not re.fullmatch(r"\d+", s)]
        if segs and segs[0].lower() in ("s", "travel", "explore"):
            segs = segs[1:]
        seg = " ".join(segs)
        seg = seg.replace("_", " ").replace("-", " ")
        seg = re.sub(r"\s+", " ", seg).strip()
        if not re.search(r"[A-Za-z]{4,}", seg):
            return None
        if len(seg) < 6 or len(seg) > 60:
            return None
        return seg.title().strip()
    except Exception:
        return None


def _fechas_compatibles(f_ev, f_snip, ev_approx):
    if f_ev is None or f_snip is None:
        return True
    diff = abs((f_ev - f_snip).days)
    if diff <= 2:
        return True
    if ev_approx and abs(f_ev.day - 15) == 0 and diff <= 20:
        return True
    return False


def construir_cola(eventos, procesados):
    cola = []
    vistos = set()
    for ev in eventos:
        link = (ev.get("link") or "").strip()
        if "facebook.com/events" not in link and "facebook.com/groups" not in link:
            continue
        org = (ev.get("organizador") or "").strip()
        if org.upper() in VACIOS and link not in procesados and link not in vistos:
            nombre = (ev.get("nombre") or "").strip()
            if len(nombre) >= 8:
                cola.append(ev)
                vistos.add(link)

    def rank(ev):
        sq = _slug_query(ev.get("link", ""))
        if sq and sq.isascii():
            return 0
        nombre = (ev.get("nombre") or "").strip()
        if nombre.isascii():
            return 1
        return 2
    cola.sort(key=rank)
    return cola


def main():
    with open(CSV_PATH, encoding="utf-8") as f:
        eventos = list(csv.DictReader(f))
    total_original = len(eventos)
    cols = list(eventos[0].keys())
    idx = {ev.get("link"): i for i, ev in enumerate(eventos)}

    procesados = {}
    if CHECKPOINT.exists():
        try:
            procesados = json.loads(CHECKPOINT.read_text())
        except Exception:
            procesados = {}
    n_hash = sum(1 for v in procesados.values() if v)
    log(f"Checkpoint: {len(procesados)} vistos, {n_hash} con organizador")

    cola = construir_cola(eventos, set(procesados.keys()))
    if not cola:
        log("Nada que hacer (todo procesado).")
        return
    log(f"Cola Fase2: {len(cola)} eventos")

    inicio = time.time()
    exitos = fallos = 0

    for i, ev in enumerate(cola):
        if time.time() - inicio > MAX_SECONDS:
            log(f"Tope {MAX_SECONDS}s. Guardando...")
            break
        link = (ev.get("link") or "").strip()
        nombre = (ev.get("nombre") or "").strip()
        slug_q = _slug_query(link)
        anio = re.search(r"(20\d{2})", ev.get("fecha") or "")
        queries_candidatas = []
        if slug_q and slug_q.isascii():
            queries_candidatas.append(f'"{slug_q}" facebook')
            if anio:
                queries_candidatas.append(f'"{slug_q}" {anio.group(1)}')
        if nombre and nombre != slug_q and nombre.isascii():
            queries_candidatas.append(f'"{nombre[:45]}" facebook')
            if anio:
                queries_candidatas.append(f'"{nombre[:35]}" {anio.group(1)} event')
        if not queries_candidatas:
            queries_candidatas = [f'"{nombre[:45]}" facebook event']
        if i % ROTATE_EVERY == 0 and i > 0:
            rotar_tor()
        mejor = None
        for query in queries_candidatas:
            resp = fetch_serp(query)
            if resp.get("status") != 200:
                continue
            f_ev = _normalizar_fecha(ev.get("fecha"))
            for r in resp.get("results", []):
                org = parsear_resultado(r)
                f_snip = _fecha_de_snippet(r.get("snippet", ""))
                if org and _fechas_compatibles(f_ev, f_snip, True):
                    mejor = org
                    break
            if mejor:
                break

        procesados[link] = mejor or ""
        if mejor:
            pos = idx.get(link)
            if pos is not None:
                eventos[pos]["organizador"] = mejor
                exitos += 1
        else:
            fallos += 1

        if (i + 1) % CHECKPOINT_EVERY == 0:
            CHECKPOINT.write_text(json.dumps(procesados))
            tmp = CSV_PATH.with_suffix(".nuevo.csv")
            with open(tmp, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=cols)
                w.writeheader(); w.writerows(eventos)
            tmp.replace(CSV_PATH)
            log(f"  [{i+1}/{len(cola)}] exitos={exitos} fallos={fallos} "
                f"parses={parses_exitos}/{parses_totales}")
        time.sleep(random.uniform(6, 10))

    CHECKPOINT.write_text(json.dumps(procesados))
    tmp = CSV_PATH.with_suffix(".nuevo.csv")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader(); w.writerows(eventos)
    tmp.replace(CSV_PATH)

    final = sum(1 for ev in eventos if (ev.get("organizador") or "").strip().upper() not in VACIOS)
    if len(eventos) != total_original:
        log(f"INTEGRIDAD ROTA: {len(eventos)} != {total_original}")
        return
    log(f"FIN Fase2: exitos={exitos} fallos={fallos} cobertura_org={final}/{total_original} "
        f"({100*final/total_original:.1f}%) parses_serp={parses_exitos}/{parses_totales}")


if __name__ == "__main__":
    main()