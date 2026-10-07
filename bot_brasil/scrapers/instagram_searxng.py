import time, random, csv
import requests
from datetime import datetime

SEARXNG_URL = "http://localhost:8888/search"
HASHTAGS = [
    "raveundergroundbr", "psytrance", "freepartybrasil",
    "psicodelicobr", "psytrancebrasil", "undergroundrave"
]
DORKS = [
    'site:instagram.com "{hashtag}" "São Paulo" OR "Rio" OR "Brasil" "ingresso" OR "lineup" OR "TBA"',
    'site:instagram.com "{hashtag}" "free party" OR "secret location" OR "floresta"',
]

def fetch_ig_via_searxng(hashtag: str, dork_template: str) -> list[dict]:
    query = dork_template.format(hashtag=hashtag)
    params = {
        "q": query,
        "engines": "google,brave",
        "format": "json",
        "language": "pt-BR",
    }
    try:
        r = requests.get(SEARXNG_URL, params=params, timeout=20)
        r.raise_for_status()
        results = r.json().get("results", [])
        eventos = []
        for res in results:
            if "instagram.com/p/" in res.get("url", ""):
                eventos.append({
                    "url": res["url"],
                    "titulo": res.get("title", ""),
                    "snippet": res.get("content", ""),
                    "fuente": "instagram_searxng",
                    "fecha_scrape": datetime.utcnow().isoformat(),
                    "hashtag": hashtag,
                })
        return eventos
    except Exception as e:
        print(f"[IG-SEARXNG] Error {hashtag}: {e}")
        return []

def run_batch():
    todos = []
    for hashtag in HASHTAGS:
        for dork in DORKS:
            results = fetch_ig_via_searxng(hashtag, dork)
            todos.extend(results)
            delay = random.uniform(12, 20)
            print(f"[IG-SEARXNG] {hashtag}: {len(results)} resultados → pausa {delay:.1f}s")
            time.sleep(delay)
        time.sleep(random.uniform(30, 45))
    return todos

if __name__ == "__main__":
    eventos = run_batch()
    print(f"Total IG via SearXNG: {len(eventos)}")
    # vuelco opcional a bot_brasil
    if eventos:
        import pathlib
        out = pathlib.Path("/Users/angelgarcia/dharmabot/bot_brasil/eventos_brasil.csv")
        # no sobrescribe, solo log
        pathlib.Path("/tmp/ig_searxng.json").write_text(__import__('json').dumps(eventos, ensure_ascii=False, indent=2))
