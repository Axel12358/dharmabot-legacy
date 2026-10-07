import asyncio, random, csv, logging, re
from datetime import datetime
from pathlib import Path
import httpx

logger = logging.getLogger("underground_br")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
SEARXNG_URL = "http://localhost:8888/search"

UNDERGROUND_DORKS_BR = [
    '"t.me" "free party" OR "festa free" OR "localizacao TBA" "psytrance" brasil',
    'site:telegra.ph "free party" "psytrance" "brasil"',
    'site:sympla.com.br "mata" OR "floresta" "psytrance" "free"',
    '"goabase.net" "brasil" "free party" OR "forest" psytrance',
    'site:psicodelia.org "free party" OR "TBA" "brasil" psytrance',
]

OUTPUT_CSV = Path("/Users/angelgarcia/dharmabot/bot_brasil/eventos_brasil.csv")
BATCH_SIZE = 3
DELAY_BETWEEN = (18, 35)
PAUSE_AFTER_BATCH = (45, 90)
MAX_403_RETRIES = 3

UNDERGROUND_SIGNALS = {
    r'\bTBA\b': 2, r'\bTBD\b': 2,
    r'loca[cl][aao]\s+(a\s+)?confirmar': 2,
    r'endere[cl]o.*confirmar': 2,
    r'coordenadas.*enviad': 2,
    r'secret\s+location': 2,
    r'free\s+party': 1, r'festa\s+free': 1,
    r'forest\s+(gathering|party|rave)': 1,
    r'mata\s+(gathering|rave|party)': 1,
    r'entrada\s+(livre|free|gratuita)': 1,
    r't\.me/': 1, r'grupo\s+whatsapp': 1,
}
FALSE_POSITIVE_GUARDS = [
    r'ingresso(s)?\s+(a\s+partir|R\$\s*\d{3,})',
    r'capacidade\s*:\s*[5-9]\d{3,}',
    r'hotel\s+parceiro',
]

def score_underground(text):
    tl = text.lower()
    for g in FALSE_POSITIVE_GUARDS:
        if re.search(g, tl, re.I):
            return False, -1, []
    score = 0
    matched = []
    for pat, w in UNDERGROUND_SIGNALS.items():
        if re.search(pat, text, re.I):
            score += w
            matched.append(pat)
    return score >= 2, score, matched

async def fetch_searxng(query, engines="bing", retries=0):
    params = {"q": query, "format": "json", "engines": engines, "language": "pt-BR"}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(SEARXNG_URL, params=params)
            if resp.status_code in (403, 429):
                if retries >= MAX_403_RETRIES:
                    logger.warning("Max retries 403: %s", query[:50])
                    return []
                wait = (2 ** retries) * 30 + random.randint(10, 30)
                logger.info("403/429 -> backoff %ss", wait)
                await asyncio.sleep(wait)
                return await fetch_searxng(query, engines, retries + 1)
            if resp.status_code != 200:
                return []
            return resp.json().get("results", [])
    except Exception as e:
        logger.error("Error fetch: %s", e)
        return []

def extract_evento(result):
    snippet = result.get("content", "") + " " + result.get("title", "")
    url = result.get("url", "")
    is_under, score, signals = score_underground(snippet)
    return {
        "nombre": result.get("title", "").strip()[:60],
        "fecha": "",
        "lugar": "TBA" if is_under else "",
        "pais": "Brasil",
        "organizador": "",
        "email": "",
        "link": url,
        "subgenero": "psytrance" if is_under else "",
        "tipo_lugar": "TBA" if is_under else "",
        "contactos": snippet[:100],
        "fuente": result.get("engine", "searxng"),
        "descripcion": snippet[:500],
        "underground": "yes" if is_under else "no",
        "underground_score": score,
    }

async def run_underground_dorks():
    resultados = []
    for i, dork in enumerate(UNDERGROUND_DORKS_BR):
        logger.info("[%d/%d] %s", i + 1, len(UNDERGROUND_DORKS_BR), dork[:60])
        results = await fetch_searxng(dork)
        logger.info("  -> %d resultados crudos", len(results))
        for r in results:
            e = extract_evento(r)
            if e:
                resultados.append(e)
        if (i + 1) % BATCH_SIZE == 0:
            pause = random.uniform(*PAUSE_AFTER_BATCH)
            logger.info("  Pausa batch: %.0fs", pause)
            await asyncio.sleep(pause)
        else:
            await asyncio.sleep(random.uniform(*DELAY_BETWEEN))
    existing = set()
    if OUTPUT_CSV.exists():
        with open(OUTPUT_CSV, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing.add(row.get("link", ""))
    nuevos = [e for e in resultados if e["link"] not in existing]
    if nuevos:
        fieldnames = ["nombre", "fecha", "lugar", "pais", "organizador", "email",
                      "link", "subgenero", "tipo_lugar", "contactos", "fuente", "descripcion"]
        with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            for e in nuevos:
                w.writerow({k: e.get(k, "") for k in fieldnames})
    under = sum(1 for e in resultados if e["underground"] == "yes")
    logger.info("Scraped: %d total | %d underground | %d nuevos", len(resultados), under, len(nuevos))
    return resultados

if __name__ == "__main__":
    asyncio.run(run_underground_dorks())
