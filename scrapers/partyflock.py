#!/usr/bin/env python3
"""
Scraper de Partyflock.nl — agenda pública de fiestas (psy/trance EDM, NL/EU).

Fuente: https://partyflock.nl/agenda
- Calendario estructurado, sin login, sin SERP, sin bans por escalado.
- Directo recibe 403 (protección); vía Tor (get_active_proxies) va 200.
- Parseo BS4 de las tablas `partylist`: cada día agrupa filas con
  nombre, sede y ciudad, y el link /party/<id>:<slug> para dedup.

Requiere: requests, bs4, lxml
"""
import re
import sys
import time
from pathlib import Path
from typing import List, Dict

import requests
from bs4 import BeautifulSoup

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

try:
    from core.http_client import get_active_proxies
except Exception:
    def get_active_proxies():
        return {}

BASE_URL = "https://partyflock.nl"
AGENDA_URL = BASE_URL + "/agenda"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 "
                   "Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}
MAX_EVENTOS = 150

# Deja fuera lineups ocultos (filas de artistas colapsadas)
CLASES_RELEVANTES = ("basehl", "hl")

# Solo conserva fiestas del universo techno/trance/psy (Partyflock lista todo:
# latin nights, bingo, 80's, etc.). Con estas keywords el match es útil.
KEYWORDS_ACA = {
    "trance": "trance", "acid": "acid", "goa": "goa", "psy": "psytrance",
    "darkpsy": "darkpsy", "forest": "forest", "progressive": "progressive",
    "hi-tech": "hi-tech", "hitech": "hi-tech", "tribe": "psychill",
    "tribal": "psychill", "techno": "techno", "hardstyle": "hardstyle",
    "hardtrance": "hardtrance", "handsup": "handsup", "suomisaundi": "suomisaundi",
    "zenon": "darkpsy", "fractal": "darkpsy", "twilight": "twilight",
    "full-on": "full-on", "relaxed": "psychill", "glitch": "glitch",
    "schranz": "schranz", "raw": "hardstyle", "hardcore": "hardcore",
    "gabber": "hardcore",
}


def _sesion():
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _normalizar_fecha(yyyymmdd: str) -> str:
    """Convierte '20260917' → '2026-09-17'."""
    yyyymmdd = (yyyymmdd or "").strip()
    if re.fullmatch(r"\d{8}", yyyymmdd):
        return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"
    return "N/A"


def _extraer_sede(texto: str) -> tuple:
    """Divide el texto de la fila en (nombre, sede, lugar).

    Formato observado: 'Nombre de la fiesta [precio] Sede , Ciudad'.
    """
    t = texto.strip()
    # Quitar el precio (número al inicio suelto tipo '3')
    t = re.sub(r"\s+\d+\s+", " ", t)
    sede = "N/A"
    lugar = "N/A"
    if "," in t:
        partes = [p.strip() for p in t.rsplit(",", 1)]
        if len(partes) == 2:
            resto, lugar = partes
            lugares = [p.strip() for p in resto.split(" ")]
            if lugares:
                sede = lugares[-1] if lugares[-1] else "N/A"
    return t, sede, lugar


def scrape_partyflock(max_eventos=MAX_EVENTOS) -> List[Dict]:
    """Scrapea el calendario de Partyflock (agenda general)."""
    print("🇳🇱 Scraping Partyflock.nl (agenda)...")
    s = _sesion()
    s.proxies.update(get_active_proxies())  # Tor fallback (directo = 403)
    r = None
    for intento in (1, 2):
        try:
            r = s.get(AGENDA_URL, timeout=40)
            if r.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(3)
    if r is None or r.status_code != 200:
        print(f"  ❌ Partyflock: HTTP {r.status_code if r else 'sin respuesta'}")
        return []

    soup = BeautifulSoup(r.text, "lxml")
    tab = soup.find("table", class_=re.compile("partylist"))
    if not tab:
        print("  ❌ Partyflock: tabla partylist no encontrada")
        return []

    eventos = []
    fecha_actual = None
    for tb in tab.find_all("tbody"):
        cls = tb.get("class") or []
        if "party-day" in cls:
            tm = tb.find("time")
            fecha_actual = _normalizar_fecha(tm["datetime"] if tm else "")
            continue
        # Filas de lineup ocultas (solo artistas) → saltar
        if any("lineuprow" in c for c in cls):
            continue
        if not any(any(c.startswith(rc) for rc in CLASES_RELEVANTES) for c in cls):
            continue
        if len(eventos) >= max_eventos:
            break
        tr = tb.find("tr")
        if not tr:
            continue
        a = tr.find("a", href=True)
        link = ""
        if a and "/party/" in a["href"]:
            link = a["href"]
        if not link:
            continue
        nombre, sede, lugar = _extraer_sede(
            tr.get_text(" ", strip=True)
        )
        if not nombre or len(nombre) < 3:
            continue
        kw_hit = next((k for k in KEYWORDS_ACA if k in nombre.lower()), None)
        if not kw_hit:
            continue
        link_abs = link if link.startswith("http") else BASE_URL + link
        eventos.append({
            "nombre": nombre[:120],
            "fecha": fecha_actual,
            "lugar": lugar,
            "pais": "Países Bajos" if not lugar or lugar == "N/A" else "N/A",
            "fuente": "Partyflock",
            "organizador": "N/A",
            "email": "N/A",
            "link": link_abs,
            "subgenero": KEYWORDS_ACA[kw_hit],
            "descripcion": f"Partyflock: {nombre} en {sede} ({lugar})",
        })
        if sede != "N/A":
            eventos[-1]["tipo_lugar"] = "club"

    print(f"  ✅ Partyflock: {len(eventos)} eventos")
    return eventos[:max_eventos]


if __name__ == "__main__":
    evs = scrape_partyflock()
    for ev in evs[:15]:
        print(f"  - {ev['nombre'][:45]} | {ev['fecha']} | {ev['lugar']} | {ev['link'][:40]}")