#!/usr/bin/env python3
"""Paso 2: propagación masiva de email por organizador desde fuentes fiables.

Construye caché org -> email a partir de filas de fuentes fiables con email
válido (RA, Goabase, Setline, Ektoplazm, Psymedia, Partyflock, Psytrance.pl,
Meetup, Telegram, Reddit) y lo aplica a TODAS las filas FB sin email que ya
tengan ese organizador.

Reglas críticas:
  - Nunca restar. Solo toca filas con email vacío/placeholder.
  - Filtrar placeholders en AMBOS lados (caché y objetivo).
  - Con fcntl lock del CSV (core.csv_lock.csv_locked_rows).
"""
import csv
import re
import sys
from collections import Counter
from pathlib import Path

PROJECT = Path(__file__).parent
sys.path.insert(0, str(PROJECT))
from core.csv_lock import csv_locked_rows
from loop_completar import es_email_valido, _es_org_placeholder, es_org_slugderivado

CSV_FILE = PROJECT / 'eventos_encontrados.csv'

FUENTES_FIABLES = {
    'Resident Advisor', 'Goabase', 'Setline', 'Ektoplazm', 'Psymedia',
    'Partyflock', 'Psytrance.pl', 'Meetup', 'Telegram', 'Reddit',
}

GENERIC_LOCALS = {
    'n/a', 'na', 'none', 'no email', 'unknown', '-', '',
    'info', 'contact', 'hello', 'hola', 'mail', 'email', 'booking',
}
GENERIC_DOMAINS = {
    'gmail.com', 'hotmail.com', 'hotmail.es', 'yahoo.com', 'outlook.com',
    'mail.com', 'proton.me', 'protonmail.com',
}

def _email_utilizable(e):
    e = (e or '').strip().lower()
    if not e or e in GENERIC_LOCALS:
        return False
    if not es_email_valido(e):
        return False
    if e.split('@')[0] in GENERIC_LOCALS:
        return False
    domain = e.split('@')[1] if '@' in e else ''
    if domain in GENERIC_DOMAINS:
        return False
    return True

def repropagar_cache():
    """Construye caché org->email desde fuentes fiables y lo aplica a filas FB
    sin email con ese organizador. Devuelve nº de emails aplicados.
    Idempotente y seguro: solo toca filas con email vacío (nunca sobrescribe).
    """
    with csv_locked_rows(CSV_FILE) as (todas, _):
        cache = {}
        fiable_total = 0
        for r in todas:
            fuente = (r.get('fuente', '') or '').strip()
            if fuente not in FUENTES_FIABLES:
                continue
            org = (r.get('organizador', '') or '').strip()
            email = (r.get('email', '') or '').strip()
            if not org or _es_org_placeholder(org):
                continue
            if es_org_slugderivado(org):
                continue
            if not _email_utilizable(email):
                continue
            cache.setdefault(org.lower(), Counter())[email] += 1
            fiable_total += 1

        org_email = {}
        for org, cnt in cache.items():
            if not cnt:
                continue
            email, _ = cnt.most_common(1)[0]
            org_email[org] = email

        print(f"Caché limpio: {len(org_email)} organizadores (de {fiable_total} filas fiables)")

        ganado = 0
        for r in todas:
            if (r.get('email', '') or '').strip():
                continue
            org = (r.get('organizador', '') or '').strip()
            if not org:
                continue
            email = org_email.get(org.lower())
            if not email:
                continue
            r['email'] = email
            ganado += 1

        print(f"✅ Propagados: {ganado} emails aplicados a filas FB sin email")
    return ganado


def main():
    repropagar_cache()
    print("Listo.")

if __name__ == '__main__':
    main()