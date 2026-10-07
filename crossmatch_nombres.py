#!/usr/bin/env python3
"""Crossmatch FB sin org/email -> fuentes fiables por nombre normalizado.

Correcto para el formato real: fechas FB son placeholder (solo año), lugar FB
= ciudad. Por eso NO se usa fecha ni venue; se matchea por tokens de nombre +
país. Solo escribe cuando hay evidencia fuerte y el target no es genérico.

dry-run por defecto (--apply para escribir).
"""
import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

PROJECT = Path(__file__).parent
sys.path.insert(0, str(PROJECT))
from core.csv_lock import csv_locked_rows
from loop_completar import es_email_valido, _es_org_placeholder, es_org_slugderivado
from propagacion_caché_limpio import _email_utilizable

CSV_FILE = PROJECT / 'eventos_encontrados.csv'

FUENTES_MAESTRO = {
    'Resident Advisor', 'Goabase', 'Setline', 'Ektoplazm', 'Psymedia',
    'Partyflock', 'Psytrance.pl', 'Meetup', 'Telegram', 'Reddit',
}

GEN = re.compile(
    r'\b(psytrance|psy\s?trance|goa trance|goa open air|psy ?chill|trance party|'
    r'open air|festival|party|gathering|event|celebration|rave|fullon|'
    r'dance|music|concert|night|weekend)\b', re.I)

def tokens(n):
    n = re.sub(r'\b(\d{4}|\d{1,2}[/-]\d{1,2})\b', ' ', n, flags=re.I)
    n = re.sub(r'[-_.–—|/:()\[\]{}&+]+', ' ', n)
    t = [w for w in re.findall(r'[a-záéíóúüñßç\']+', n.lower()) if len(w) >= 4]
    return set(t), t

def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)

def es_nombre_real(nombre):
    t, _ = tokens(nombre)
    # Excluir genéricos: quedan <2 tokens útiles o son un simple descriptor
    if not t:
        return False
    no_gen = [w for w in t if not GEN.match(w)]
    return len(no_gen) >= 2

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='escribir cambios')
    args = ap.parse_args()

    with csv_locked_rows(CSV_FILE) as (todas, _):
        maestros = []          # (tokens, org, email, pais, nombre)
        fb_sin = []
        org_email_maestro = {}
        for r in todas:
            fuente = (r.get('fuente', '') or '').strip()
            org = (r.get('organizador', '') or '').strip()
            email = (r.get('email', '') or '').strip()
            pais = (r.get('pais', '') or '').strip()
            nombre = (r.get('nombre', '') or '').strip()
            if fuente in FUENTES_MAESTRO and org and not _es_org_placeholder(org):
                tok, _ = tokens(nombre)
                maestros.append((tok, org, email, pais, nombre))
                if _email_utilizable(email):
                    org_email_maestro.setdefault(org.lower(), set()).add(email)
            elif 'Facebook' in fuente and (not org or org.lower() == 'n/a'):
                fb_sin.append(r)

        # Organizadores de FB (dorks) con email ya válido como fuente adicional
        for r in todas:
            fuente = (r.get('fuente', '') or '').strip()
            org = (r.get('organizador', '') or '').strip()
            email = (r.get('email', '') or '').strip()
            if fuente == 'Facebook (dorks)' and org and _email_utilizable(email):
                org_email_maestro.setdefault(org.lower(), set()).add(email)

        # Agrupar maestros por pais para buscar solo ahí
        por_pais = defaultdict(list)
        for m in maestros:
            por_pais[m[3]].append(m)

        definidos = {}
        for r in fb_sin:
            nombre = (r.get('nombre', '') or '').strip()
            if not es_nombre_real(nombre):
                continue
            tok, _ = tokens(nombre)
            pais = (r.get('pais', '') or '').strip()
            best, bestj = None, 0.0
            for _, org, email, mpais, mnom in por_pais.get(pais, []):
                if not tok or not _:
                    continue
                j = jaccard(tok, _)
                if j > bestj:
                    bestj, best = j, (org, email, mnom)
            # Umbral conservador: alto jaccard, match decide con margen real
            if bestj >= 0.60 and best:
                orgm, emailm, mnom = best
                definidos[id(r)] = (orgm, emailm, mnom, bestj, nombre)

        print(f"Maestros: {len(maestros)} | FB sin org elegibles: {len(fb_sin)} | "
              f"matches >=0.60: {len(definidos)}")

        # distribucion de umbrales para calibración
        dist = defaultdict(int)
        for _, _, _, j, _ in definidos.values():
            dist[round(j, 2)] += 1
        print("Distribución jaccard:", dict(sorted(dist.items(), reverse=True)))

        if not args.apply:
            print("DRY-RUN (usa --apply para escribir)")
            for vid, (orgm, emailm, mnom, j, nombre) in list(definidos.items())[:8]:
                print(f"  {j:.2f} | {nombre[:45]} <= {mnom[:35]} | {orgm} | {emailm}")
            return

        ganado_org = 0
        ganado_email = 0
        for r in fb_sin:
            d = definidos.get(id(r))
            if not d:
                continue
            orgm, emailm, mnom, j, nombre = d
            if (r.get('organizador', '') or '').strip() not in ('', 'N/A'):
                continue
            r['organizador'] = orgm
            r['tipo_organizador'] = 'promoter' if not es_org_slugderivado(orgm) else 'venue'
            ganado_org += 1
            if _email_utilizable(emailm) and not (r.get('email', '') or '').strip():
                r['email'] = emailm
                ganado_email += 1

        # Segundo pase: propagar email a FB matriz con el MISMO org ya resuelto
        # por crossmatch (org ahora conocido -> usa maestro email si aplica)
        for r in todas:
            if (r.get('email', '') or '').strip():
                continue
            org = (r.get('organizador', '') or '').strip()
            if _es_org_placeholder(org) or es_org_slugderivado(org):
                continue
            cands = org_email_maestro.get(org.lower())
            if not cands:
                continue
            for e in cands:
                if _email_utilizable(e):
                    r['email'] = e
                    ganado_email += 1
                    break

        print(f"✅ Aplicados: {ganado_org} orgs, {ganado_email} emails")

if __name__ == '__main__':
    main()