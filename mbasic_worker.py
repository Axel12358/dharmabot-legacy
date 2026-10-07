"""Proceso hijo: acceso directo a grupo FB (mbasic / noscript) vía Tor con timeout HARD.

Devuelve JSON con análisis: login_wall, tamaño, título, texto visible, posts.
Usado por probe_mbasic.py.
"""
import sys
import json
import re

_ROOT = "/Users/angelgarcia/dharmabot"
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.http_client import get_html


def probar_grupo(gid: str, intentos: int = 2) -> dict:
    variantes = [
        f"https://mbasic.facebook.com/groups/{gid}",
        f"https://www.facebook.com/groups/{gid}?_fb_noscript=1",
        f"https://mbasic.facebook.com/groups/{gid}?v=timeline",
    ]
    for url in variantes:
        for imp in ("chrome110", "safari_ios_16", "safari15_3"):
            html = get_html(url, timeout=18, impersonate=imp)
            if not html:
                continue
            low = html.lower()
            login = ("log in" in low[:3000]) or ("login_form" in low)
            t = re.search(r"<title>(.*?)</title>", html, re.S)
            title = re.sub(r"\s+", " ", t.group(1))[:60] if t else ""
            if login:
                return {"gid": gid, "status": "login_wall", "variante": url,
                        "len": len(html), "title": title}
            if len(html) < 3000 or ("_fb_noscript" in url and len(html) < 20000 and "'posts'" not in low):
                continue  # shell vacía sin contenido
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text)
            posts = re.findall(r"/posts/", html)
            host_mentions = re.findall(
                r"(?:organized|organised|hosted|present)[^<]{0,40}", low)
            return {"gid": gid, "status": "ok", "variante": url, "len": len(html),
                    "title": title, "posts": len(posts),
                    "host_mentions": host_mentions[:3],
                    "text": text[:1500]}
    return {"gid": gid, "status": "fail", "len": 0}


if __name__ == "__main__":
    gid = sys.argv[1]
    print(json.dumps(probar_grupo(gid), ensure_ascii=False))