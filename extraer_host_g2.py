"""Fase G2: Extraer organizador/host de los snippets de grupos (grupos_snippets.json).

Tier 1 — regex sobre el snippet:
    Presented by X | organized by X | hosted by X | X present/presents
    "SUN PROJECT" -> candidato si aparece con "Come back" (colectivo).
Tier 2 — LLM (mcp_clasificar / freellmpool): dado el snippet, "¿quién organiza?"

Solo candidates con confianza alta se podrán usar en G3 para match con eventos
del CSV por fecha ±3 días + ciudad + subgénero. Nunca inventar.
Output: organizador_candidates.json (checkpoint: recorre snippets sin procesar).
"""
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

_ROOT = Path("/Users/angelgarcia/dharmabot")
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.mcp_clasificar import _llm_generate

SNIPPETS_FILE = _ROOT / "grupos_snippets.json"
CANDIDATOS_FILE = _ROOT / "organizador_candidates.json"
CHECKPOINT = _ROOT / "grupos_g2_checkpoint.json"
LOG_FILE = _ROOT / "grupos_g2.log"
MAX_SECONDS = 95
MAX_LLM_POR_BLOQUE = 25


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# --- Tier 1: regex ---
_PATRONES = [
    # "Presented by X" / "organized by X" / "hosted by X" / "promoted by X"
    re.compile(r"(?:presented|presenting|hosted)\s+by\s*:?\s*([A-ZÀ-Ü][A-Za-zÀ-ü0-9&'&/.]*(?:\s+[A-Za-zÀ-ü0-9&'&/.]+){0,6})", re.I),
    # Cabecera típica: "X present/presents/presenting" al inicio (multiline) o tras "☉/—/·"
    re.compile(r"(?:^|[·:—])[ \t]*([A-ZÀ-Ü][A-Za-zÀ-ü0-9&'&/.]*(?:\s+[A-Za-zÀ-ü0-9&'&/.]+){0,5})\s+(?:presents?|presenting|present)\b", re.M),
    # "X presents  Y"  -> X (organizador) antes del verbo
    re.compile(r"([A-ZÀ-Ü][A-Za-zÀ-ü0-9&'&/]*(?:\s+[A-Za-zÀ-ü0-9&'&/.]+){0,5})\s+presents?\s", re.I),
    # "by @Xcrew" / "by X Collective/Crew"
    re.compile(r"by\s+(@?[A-Z][A-Za-zÀ-ü0-9_&']{2,40})\s+(?:crew|collective|records|productions|events|family|bookings?)", re.I),
    # "For our X Festival/Party" al inicio (negación implícita: patrón 1-3 cubre mejor)
]


_BAD_WORDS = {"sounds", "music", "mind", "brains", "brain", "party", "beach",
              "journey", "weekly", "monday", "wednesday", "friday", "saturday",
              "sunday", "tuesday", "thursday", "others", "and", "the", "from",
              "drum", "rhythm", "body", "morning", "session", "tonight"}


def host_regex(snippet: str) -> str:
    if not snippet:
        return ""
    candidatos = []
    for pat in _PATRONES:
        m = pat.search(snippet)
        if m:
            h = m.group(1).strip()
            # cortar en dígitos o palabras de detalle (at/on/for/in + fecha/hora)
            h = re.split(r"\d|\bat\b|\bon\b|\bfor\b|\bin\b|\bfrom\b|\buntil\b|\b-\b|\b−\b", h, maxsplit=1)[0].strip(" .,;:•–-")
            candidatos.append(h)
    # elegir el candidato más corto (más probable nombre limpio)
    for h in sorted(candidatos, key=len):
        palabras = re.findall(r"[A-Za-zÀ-ü]+", h.lower())
        if len(h) < 3 or len(h) > 45:
            continue
        if len(palabras) >= 4 and h.count(" ") > 3:
            continue
        if any(w in _BAD_WORDS for w in palabras):
            continue
        if re.search(r"\d", h):
            continue
        return re.sub(r"\s+", " ", h).strip()
    return ""


# --- Tier 2: LLM ---
_PROMPT_HOST = """Dado el texto de un post de evento, extrae el ORGANIZADOR o COLECTIVO que lo presenta.
Reglas:
- Si dice "Presented by X", "organized by X", "X presents", la cabecera del evento, usa X.
- Si es solo un artista/DJ (no es organizador), IGNÓRALO.
- Si no hay organizador claro, responde N/A.
- NUNCA inventes.
Texto: {texto}
Responde SOLO con el nombre del organizador (sin JSON, sin texto extra). Ejemplo: PSY NATION"""


def host_llm(snippet: str) -> str:
    resp = _llm_generate(_PROMPT_HOST.format(texto=snippet[:500]),
                        system="Extractor. No inventar.", temperature=0.05)
    if not resp:
        return ""
    resp = resp.strip()
    # Respuesta directa limpia: solo el nombre (con whitespace pero sin puntuación extra)
    if len(resp) <= 45 and not re.search(r"\n|\.\s|[:,]", resp) and re.match(r"^[A-Za-zÀ-ü0-9&' .(){}\[\]]+$", resp):
        if resp.upper() not in ("N/A", "NULL", "NONE", ""):
            return resp
    m = re.search(r"\{.*\}", resp, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            org = (data.get("organizador") or "").strip()
            if org.upper() not in ("N/A", "", "NULL", "NONE"):
                return org[:80]
        except Exception:
            pass
    # Fallback: extraer nombres citados en prosa (negritas, comillas, tras "por")
    m2 = re.search(r"\*\*([^*]+)\*\*|「([^」]+)」|«([^»]+)»|\"([^\"]+)\"|(?:organizado por|por)\s+([A-ZÀ-Ü][A-Za-zÀ-ü0-9&' .]{2,40})", resp)
    if not m2:
        return ""
    extraido = next((g for g in m2.groups() if g), "")
    extraido = extraido.strip(" .,;•:–\n")
    if extraido.upper() in ("N/A", "NULL", "NONE", ""):
        return ""
    if len(extraido) < 3 or len(extraido) > 45:
        return ""
    return extraido


def main():
    if not SNIPPETS_FILE.exists():
        log("Sin grupos_snippets.json. Fin.")
        return
    snippets = json.loads(SNIPPETS_FILE.read_text(encoding="utf-8"))

    cand = {}
    if CANDIDATOS_FILE.exists():
        try:
            cand = json.loads(CANDIDATOS_FILE.read_text(encoding="utf-8"))
        except Exception:
            cand = {}

    ckpt = {}
    if CHECKPOINT.exists():
        try:
            ckpt = json.loads(CHECKPOINT.read_text())
        except Exception:
            ckpt = {}
    hechas = set(ckpt.get("hechas", []))

    # cola: pares (grupo_id, snippet_idx) sin procesar
    cola = []
    for gid, g in snippets.items():
        for idx, sn in enumerate(g.get("snippets", [])):
            key = f"{gid}::{idx}"
            if key not in hechas:
                cola.append((key, gid, idx, sn.get("snippet", "")))
    log(f"Snippets: {len(cola)} pendientes")
    if not cola:
        log("TODO procesado. Fin.")
        return

    inicio = time.time()
    llm_llamadas = 0
    matches = 0
    for key, gid, idx, snippet in cola:
        if time.time() - inicio > MAX_SECONDS:
            log(f"Tope {MAX_SECONDS}s. Guardando...")
            break

        org = host_regex(snippet)
        via = "regex"
        if not org and llm_llamadas < MAX_LLM_POR_BLOQUE:
            org = host_llm(snippet)
            via = "llm" if org else "regex"
            llm_llamadas += 1

        if org:
            matches += 1
            if gid not in cand:
                cand[gid] = {"id": gid, "nombre": snippets[gid].get("nombre", ""),
                             "url": snippets[gid].get("url", ""), "candidatos": []}
            cand[gid]["candidatos"].append({
                "organizador": org,
                "via": via,
                "snippet_idx": idx,
                "snippet": snippet[:250],
            })
        hechas.add(key)

        if (matches and matches % 5 == 0) or (llm_llamadas and llm_llamadas % 10 == 0):
            CANDIDATOS_FILE.write_text(json.dumps(cand, ensure_ascii=False, indent=2))
            CHECKPOINT.write_text(json.dumps({"hechas": sorted(hechas)}))
            log(f"progreso: candidatos={sum(len(v['candidatos']) for v in cand.values())} llm={llm_llamadas}")

    CANDIDATOS_FILE.write_text(json.dumps(cand, ensure_ascii=False, indent=2))
    CHECKPOINT.write_text(json.dumps({"hechas": sorted(hechas)}))
    log(f"FIN G2: grupos_con_cand={sum(1 for v in cand.values() if v['candidatos'])} "
        f"matches={matches} llm={llm_llamadas} pendientes={len(cola)}")


if __name__ == "__main__":
    main()