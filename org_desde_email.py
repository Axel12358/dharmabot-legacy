#!/usr/bin/env python3
"""Deriva el ORGANIZADOR desde el EMAIL de cada fila (señal real y verificable,
no inventada). Escribe propuestas a `propuestas_org.jsonl` (se fusiona con las
existentes, sin duplicar por clave). NO toca el CSV.

- Dominio propio (no free): confianza ALTA (base del dominio → nombre).
- Gmail/free: confianza MEDIA (local-part → nombre); se descartan local-parts
  genéricos (info, contact, booking…).
- `--llm`: limpia/divide nombres concatenados vía LLM (p.ej.
  'tweaksoundsystem' → 'Tweak Sound System'), sin inventar si es genérico.
"""
import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from loop_completar import es_nombre_gen_org

try:
    from core.mcp_clasificar import _llm_generate
except Exception:
    _llm_generate = None

ROOT = Path(__file__).resolve().parent
CSV = ROOT / "eventos_encontrados.csv"
OUT = ROOT / "propuestas_org.jsonl"

FREE_DOMAINS = {
    "gmail.com", "googlemail.com", "hotmail.com", "hotmail.es", "outlook.com",
    "outlook.es", "yahoo.com", "yahoo.es", "yahoo.co.uk", "icloud.com",
    "protonmail.com", "proton.me", "proton.mx", "gmx.com", "gmx.de", "web.de",
    "mail.com", "yandex.com", "yandex.ru", "aol.com", "live.com", "msn.com",
    "zoho.com", "gmx.net", "mail.ru", "tutanota.com", "qq.com", "163.com",
}
GENERIC_LOCAL = {
    "info", "contact", "contacto", "booking", "bookings", "reservas", "admin",
    "hello", "hola", "hi", "mail", "email", "mailbox", "events", "event",
    "eventos", "music", "musica", "promo", "promos", "promotion", "promotions",
    "management", "office", "team", "support", "soporte", "press", "prensa",
    "tickets", "ticket", "festival", "records", "label", "sales", "hello",
    "no-reply", "noreply", "donotreply", "marketing", "media", "agency",
}
GENERIC_TOKENS = {"the", "de", "la", "el", "los", "las", "and", "y", "music",
                  "records", "sounds", "sound", "label", "events", "event"}

SYS = ("Limpias nombres de organizadores de eventos. Dado un token (local-part "
       "de un email) devuelve SOLO JSON con el nombre legible separando palabras, "
       "o nombre vacío si el token es genérico (info, contact, booking…). No "
       "inventes palabras que no estén implícitas en el token.")


def _vacio(c):
    return (c or "").strip() in ("", "N/A")


def _es_fb(r):
    return (r.get("fuente") or "").lower().startswith("facebook")


def _clave(r):
    return f"{(r.get('nombre') or '').strip().lower()}|{(r.get('lugar') or '').strip().lower()}"


def _title(s):
    return " ".join(w if w.isupper() and len(w) <= 3 else w.capitalize()
                    for w in s.split())


def _org_ok(org):
    if not org or not (3 <= len(org) <= 48) or len(org.split()) > 5:
        return False
    toks = [t for t in re.split(r"\W+", org.lower()) if t]
    return any(t not in GENERIC_TOKENS and t not in GENERIC_LOCAL for t in toks)


def _llm_clean(token):
    if not _llm_generate:
        return ""
    try:
        txt = _llm_generate(f'Token: "{token}"\nDevuelve JSON: {{"nombre":""}}',
                            system=SYS, temperature=0.02) or ""
    except Exception:
        return ""
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return ""
    try:
        return (json.loads(m.group(0)).get("nombre") or "").strip()
    except Exception:
        return ""


def _org_desde_email(email, usar_llm):
    email = (email or "").strip().lower()
    if "@" not in email:
        return None
    local, _, dom = email.partition("@")
    if dom in FREE_DOMAINS:
        tok = re.split(r"[._\-+]", local)[0]
        if tok in GENERIC_LOCAL or len(tok) < 4:
            return None
        org = _llm_clean(tok) if usar_llm else ""
        return (org or _title(tok), "media")
    label = dom.split(".")[0]
    if label in ("www",):
        label = dom.split(".")[1] if len(dom.split(".")) > 1 else label
    org = _title(re.sub(r"\d+", "", label.replace("-", " ").replace("_", " ")))
    return (org, "alta")


def _proponer(r, usar_llm):
    if not _vacio(r.get("organizador")) or _vacio(r.get("email")):
        return None
    ev = _org_desde_email(r.get("email"), usar_llm)
    if not ev:
        return None
    org, conf = ev
    if not _org_ok(org):
        return None
    return {
        "clave": _clave(r), "link": r.get("link") or "", "nombre": r.get("nombre") or "",
        "lugar": r.get("lugar") or "", "fecha": r.get("fecha") or "",
        "organizador": org, "email": r.get("email") or "",
        "fuente_url": "email:" + (r.get("email") or ""),
        "confianza": conf, "metodo": "email",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="limpiar tokens concatenados vía LLM")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limite", type=int, default=0)
    args = ap.parse_args()

    import csv
    rows = list(csv.DictReader(open(CSV, encoding="utf-8")))
    resid = {id(r) for r in rows if _es_fb(r) and es_nombre_gen_org(r.get("nombre") or "")}
    cand = [r for r in rows if id(r) not in resid and _vacio(r.get("organizador")) and not _vacio(r.get("email"))]
    if args.limite:
        cand = cand[:args.limite]
    print(f"candidatos (sin org, con email): {len(cand)} | LLM={'sí' if args.llm else 'no'}")

    props, vistos = [], set()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for p in pool.map(lambda r: _proponer(r, args.llm), cand):
            if p and p["clave"] not in vistos:
                vistos.add(p["clave"])
                props.append(p)

    # fusionar con propuestas previas (dedup por clave)
    prev = []
    if OUT.exists():
        for ln in OUT.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                prev.append(json.loads(ln))
    ya = {p["clave"] for p in props}
    final = props + [p for p in prev if p.get("clave") not in ya]
    with open(OUT, "w", encoding="utf-8") as f:
        for p in final:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    altas = sum(1 for p in props if p["confianza"] == "alta")
    print(f"nuevas propuestas: {len(props)} (alta: {altas}, media: {len(props)-altas}) | total jsonl: {len(final)}")
    for p in props[:20]:
        print(f"  [{p['confianza']}] {p['nombre'][:34]:34s} | {p['email'][:34]:34s} → {p['organizador']}")


if __name__ == "__main__":
    main()
