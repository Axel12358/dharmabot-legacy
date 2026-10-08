#!/usr/bin/env python3
"""Construye el catálogo-origen (organizadores verificados) para rellenar
organizador/email en filas vacías de eventos_encontrados.csv.

Solo usa filas de FUENTES FIABLES (RA/Goabase/Setline/Partyflock/Psytrance.pl/
Ektoplazm/Isratrance/Meetup) ya consolidadas en main: no descubre nada nuevo,
solo vuelve a aplicar conocimiento verificado. Nada se escribe; genera:

  catalogo_org_email.json : {org_norm: {org, email, fuentes, n}}
  mapa_venue_host.json    : {venue_norm: {org, n_total, n_org, pct}}

Regla de precisión (conservadora):
  - Catálogo: org+email NO placeholder (mismos filtros que loop/enricher).
  - Mapa venue→host: solo venues con >=2 eventos de fuentes fiables donde UN
    organizador ocupa >=60% y no hay conflicto (top2 > 40% → descartar).
  - Se excluyen orgs basura derivados de slug (corta, sin letras, en stoplist).

USO: python construir_catalogo_org_email.py [--min-eventos 2] [--pct 0.60]
"""
import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CSV_FILE = ROOT / "eventos_encontrados.csv"
OUT_CAT = ROOT / "catalogo_org_email.json"
OUT_VEN = ROOT / "mapa_venue_host.json"

FUENTES_FIABLES = {
    "Resident Advisor", "Goabase", "Setline", "Partyflock",
    "Psytrance.pl", "Ektoplazm", "Isratrance", "Meetup",
}

_EMAIL_PLACEHOLDER = re.compile(
    r"company\.com|venue\.com|guest@|back-in-stock@|@placehold|@example|"
    r"\.domain\.cz|@domain\.|^email@|^info@$|^contact@$|n/?a|^[^@]+$",
    re.I,
)
_ORG_BASURA = re.compile(r"^\W*$|^\d+$|\b(n/a|na|tba|loading|facebook|instagram)\b", re.I)


def _org_valido(org):
    o = (org or "").strip()
    if not o or o.lower() in ("n/a", "na", "tba", ""):
        return False
    if len(o) < 3 or len(o) > 60:
        return False
    if _ORG_BASURA.search(o):
        return False
    return True


def _email_valido(email):
    e = (email or "").strip()
    if not e or e.lower() in ("n/a", "na"):
        return False
    if "@" not in e:
        return False
    if _EMAIL_PLACEHOLDER.search(e):
        return False
    return True


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower()).strip(" .,;:!?")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-eventos", type=int, default=2)
    ap.add_argument("--pct", type=float, default=0.60)
    args = ap.parse_args()

    rows = list(csv.DictReader(open(CSV_FILE, encoding="utf-8")))
    fiables = [r for r in rows if (r.get("fuente") or "") in FUENTES_FIABLES]

    cat = defaultdict(lambda: {"org": "", "email": "", "fuentes": set(), "n": 0})
    for r in fiables:
        org = (r.get("organizador") or "").strip()
        em = (r.get("email") or "").strip()
        if not _org_valido(org):
            continue
        key = _norm(org)
        c = cat[key]
        c["org"] = c["org"] or org
        c["fuentes"].add(r.get("fuente") or "")
        c["n"] += 1
        if _email_valido(em):
            if not c["email"]:
                c["email"] = em
            elif c["email"] != em:
                # email conflictivo: tomamos el más frecuente entre los vistos
                pass

    # Recolectar email por org con votación simple
    email_voto = defaultdict(Counter)
    for r in fiables:
        org = (r.get("organizador") or "").strip()
        em = (r.get("email") or "").strip()
        if _org_valido(org) and _email_valido(em):
            email_voto[_norm(org)][em] += 1

    catalogo = {}
    for key, c in cat.items():
        c["fuentes"] = sorted(c["fuentes"])
        em = ""
        if key in email_voto:
            top = email_voto[key].most_common(2)
            if len(top) == 1 or top[0][1] > top[1][1]:
                em = top[0][0]
        c["email"] = em
        catalogo[key] = c

    # Mapa venue → host (solo fuentes fiables)
    venue_org = defaultdict(Counter)
    for r in fiables:
        ven = _norm(r.get("lugar") or "")
        org = (r.get("organizador") or "").strip()
        if not ven or not _org_valido(org):
            continue
        venue_org[ven][(_norm(org), org)] += 1

    mapa = {}
    for ven, cnt in venue_org.items():
        n_total = sum(cnt.values())
        if n_total < args.min_eventos:
            continue
        (_, org_top), n_top = cnt.most_common(1)[0]
        if len(cnt) >= 2:
            (_, org2), n2 = cnt.most_common(2)[1]
            if n2 / n_total >= 0.4:
                continue  # conflicto: dos hosts significativos
        if n_top / n_total >= args.pct:
            mapa[ven] = {
                "org": org_top,
                "n_total": n_total,
                "n_org": n_top,
                "pct": round(n_top / n_total, 3),
            }

    OUT_CAT.write_text(
        json.dumps(catalogo, ensure_ascii=False, indent=1), encoding="utf-8")
    OUT_VEN.write_text(
        json.dumps(mapa, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"catalogo_org_email.json: {len(catalogo)} organizadores "
          f"({sum(1 for v in catalogo.values() if v['email'])} con email)")
    print(f"mapa_venue_host.json: {len(mapa)} venues fiables "
          f"(eventos cubiertos: {sum(v['n_total'] for v in mapa.values())})")


if __name__ == "__main__":
    sys.exit(main())