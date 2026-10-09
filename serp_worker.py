"""Proceso hijo: búsqueda SERP (DuckDuckGo html) con timeout HARD.

Corre con el python del venv. Sale por Tor (nunca IP real) via
core.http_client.get_html. Devuelve JSON con snippet results.
"""
import sys
import json
import re
import urllib.parse
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.http_client import get_html


def _serx(q: str, timeout: int = 20) -> dict:
    """SearXNG local (127.0.0.1:8888) con engines google+brave.
    Devuelve el mismo shape que DDG: {status, results:[{url,titulo,snippet}], error}.
    """
    import urllib.request

    url = (
        "http://127.0.0.1:8888/search?"
        + urllib.parse.urlencode({"q": q, "format": "json"})
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "dharma/v5"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        results = []
        for it in data.get("results", []) or []:
            titulo = re.sub(r"<[^>]+>", "", it.get("title") or "").strip()
            snip = re.sub(r"<[^>]+>", "", it.get("content") or "").strip()
            url_r = it.get("url") or ""
            if not titulo and not url_r:
                continue
            results.append({"url": url_r, "titulo": titulo, "snippet": snip})
        return {"status": 200 if results else 0, "results": results, "error": ""}
    except Exception as e:
        return {"status": 0, "results": [], "error": str(e)[:200]}


def search(query: str, timeout: int = 20) -> dict:
    # 1) DuckDuckGo para la IP neutral (Tor) cuando responde
    try:
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        html = get_html(url, timeout=timeout)
        if html and len(html) >= 500 and "result__a" in html:
            bloqueado = re.search(
                r"anomaly|unusual traffic|captcha|cannot verify|blocked", html, re.I
            )
            if not (bloqueado and "result__a" not in html):
                results = []
                for m in re.finditer(
                    r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
                    r'.*?class="result__snippet"[^>]*>(.*?)</div>',
                    html, re.S,
                ):
                    href, titulo, snip = m.group(1), m.group(2), m.group(3)
                    titulo = re.sub(r"<[^>]+>", "", titulo).strip()
                    snip = re.sub(r"<[^>]+>", "", snip).strip()
                    dec = urllib.parse.unquote(href)
                    mm = re.search(r"uddg=([^&]+)", dec)
                    if mm:
                        dec = urllib.parse.unquote(mm.group(1))
                    results.append({"url": dec, "titulo": titulo, "snippet": snip})
                if results:
                    return {"status": 200, "results": results, "error": ""}
    except Exception:
        pass
    # 2) SearXNG local (engines google+brave) como fallback
    r = _serx(query, timeout)
    if r.get("status") == 200:
        return r
    return {"status": 0, "results": [], "error": r.get("error") or "no-results"}


if __name__ == "__main__":
    query = sys.argv[1]
    timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    print(json.dumps(search(query, timeout)))