#!/usr/bin/env python3
"""Atacante paralelo: barrido yandex por ciudad + cosecha de emails de
organizadores reales. Corre en paralelo a loop_completar.py (mismo CSV y
mismo lock core/csv_lock → escrituras serializadas).

Frentes:
  A) Org: barrido SERP (yandex) por ciudad → organizador vía slug/snippet.
     Reutiliza minar_organizadores_fb_serp (el canal que sí produce orgs).
  B) Email: para organizadores reales (no placeholder) con eventos sin email,
     DDG→web→email y propagación al organizador (todas sus filas).

Checkpoint propio: atacante_checkpoint.json. Log: atacante_run.log.
"""
import json
import re
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
CHECKPOINT = PROJECT_ROOT / "atacante_checkpoint.json"
LOG = PROJECT_ROOT / "atacante_run.log"

from core.csv_lock import csv_locked_rows
import loop_completar as L

CIUDADES_POR_PASADA = 4
ORGS_EMAIL_POR_PASADA = 3
PAUSA_ENTRE_PASADAS = 45
RE_SWEEP_HORAS = 4


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    with open(LOG, "a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def _cargar_checkpoint():
    if CHECKPOINT.exists():
        try:
            return json.loads(CHECKPOINT.read_text())
        except Exception:
            pass
    return {"ciudades_ultimo_sw": {}, "org_email_intentos": {}, "emails_aplicados": 0}


def _guardar_checkpoint(cp):
    CHECKPOINT.write_text(json.dumps(cp, indent=2, ensure_ascii=False))


def _ciudades_sin_org():
    """Ciudades con eventos FB sin organizador, con conteo y años/subgéneros."""
    from collections import Counter
    sin_org = L.cargar_eventos_sin_org()
    agru = {}
    for r in sin_org:
        if 'Facebook' not in r.get('fuente', ''):
            continue
        c = (r.get('lugar', '') or '').strip()
        if not c or c.lower() in ('n/a', 'online'):
            continue
        a = agru.setdefault(c, {"n": 0, "anios": Counter(), "subs": Counter()})
        a["n"] += 1
        y = (r.get('fecha', '') or '')[:4]
        if y.isdigit() and y >= '2024':
            a["anios"].update([y])
        sg = (r.get('subgenero', '') or '').strip()
        if sg and sg.lower() != 'n/a':
            a["subs"].update([sg])
    return agru


def _proxima_ciudad(cp, agru):
    now = time.time()
    for c in sorted(agru, key=lambda k: (cp["ciudades_ultimo_sw"].get(k, 0), -agru[k]["n"])):
        if now - cp["ciudades_ultimo_sw"].get(c, 0) > RE_SWEEP_HORAS * 3600:
            return c
    return None


def _org_parece_basura(org):
    o = (org or '').strip()
    if L._es_org_placeholder(o):
        return True
    wo = re.split(r'\s+', o)
    if len(wo) >= 5:
        return True
    if wo[-1].lower() in ('default', 'llc', 'inc', 'official', 'fl', 'usa', 'germany', 'spain'):
        return True
    if re.search(r'\b(blvd|street|st\.|avenue|av\.|road|rd\.|lane|bvd|boulevard)\b', o, re.I):
        return True
    if re.search(r'\b\d{2,}\b', o):
        return True
    return False


# Conocimiento experto verificado (fuente: verificación manual + websearch,
# no apropiarse de emails ajenos). Clave = fragmento exacto del link.
CONOCIDOS_LINK_ORG_EMAIL = {
    'iono_berlin': ('IONO Music', 'info@iono-music.com'),
    's.u.n._festival': ('S.U.N. Festival', None),
    'amfite%c3%a1tr-na-hore': ('Žasnem z. s.', None),
}
# Organizador VERIFICADO con su contacto oficial (propagable por fila).
CONOCIDO_ORG_EMAIL = {
    'iono music': 'info@iono-music.com',
}


def _aplicar_conocidos():
    """Aplica el conocimiento experto (slug->org / org->email) a filas
    sin org o sin email. Operación cerrada y reversible (solo rellena).
    Devuelve (orgs, emails) aplicados."""
    orgs = emails = 0
    with csv_locked_rows(L.CSV_FILE) as (todas, _):
        for r in todas:
            l = (r.get('link', '') or '').lower()
            for frag, (org, email) in CONOCIDOS_LINK_ORG_EMAIL.items():
                if frag in l and (r.get('organizador', '') or '').strip() in ('', 'N/A'):
                    r['organizador'] = org
                    orgs += 1
                    if email and not (r.get('email', '') or '').strip():
                        r['email'] = email
                        emails += 1
                    break
            else:
                o = (r.get('organizador', '') or '').strip().lower()
                if o and o in CONOCIDO_ORG_EMAIL and not (r.get('email', '') or '').strip():
                    r['email'] = CONOCIDO_ORG_EMAIL[o]
                    emails += 1
    return orgs, emails


def _aplicar_email_por_org(org, email):
    """Propaga email a todas las filas de `org` que no tengan email."""
    email = (email or '').strip()
    org = (org or '').strip()
    if not email or not org:
        return 0
    aplicados = 0
    with csv_locked_rows(L.CSV_FILE) as (todas, fieldnames):
        for r in todas:
            if (r.get('email', '') or '').strip():
                continue
            if (r.get('organizador', '') or '').strip().lower() == org.lower():
                r['email'] = email
                aplicados += 1
    return aplicados


def ataque_org(cp, agru, limite=CIUDADES_POR_PASADA):
    total = 0
    for _ in range(limite):
        c = _proxima_ciudad(cp, agru)
        if not c:
            break
        a = agru[c]
        anios = [y for y, _ in a["anios"].most_common(2)]
        subs = [sg for sg, _ in a["subs"].most_common(4)]
        try:
            mapa = L.minar_organizadores_fb_serp([c], anios=anios, subgeneros=subs, max_por_ciclo=1)
        except Exception as e:
            log(f"  ⚠️ sweep {c}: {str(e)[:80]}")
            mapa = {}
        ganado = L._aplicar_mapa_org(mapa) if mapa else 0
        cp["ciudades_ultimo_sw"][c] = time.time()
        total += ganado
        log(f"  🛰️ {c}: {len(mapa)} resultados → {ganado} orgs aplicados")
        time.sleep(2)
    if total:
        log(f"  FASE ORG: +{total} organizadores")
    return total


def ataque_email(cp, limite=ORGS_EMAIL_POR_PASADA):
    """Organizadores reales con eventos sin email, priorizando más eventos."""
    from collections import Counter
    pend = Counter()
    with csv_locked_rows(L.CSV_FILE) as (todas, _):
        pend.update((r.get('organizador', '') or '').strip()
                    for r in todas
                    if not (r.get('email', '') or '').strip()
                    and (r.get('organizador', '') or '').strip())
    if not pend:
        return 0
    total = 0
    for org, n in pend.most_common():
        if total >= limite:
            break
        if L._es_org_placeholder(org):
            continue
        if _org_parece_basura(org):
            continue
        it = cp["org_email_intentos"].get(org.lower(), 0)
        if it >= 3:
            continue
        if time.time() - cp.get("org_email_ult", {}).get(org.lower(), 0) < 3600:
            continue
        email = CONOCIDO_ORG_EMAIL.get(org.lower(), '')
        if not email:
            try:
                email = L.minar_email_organizador(org, '')
            except Exception as e:
                log(f"  ⚠️ email {org[:30]}: {str(e)[:60]}")
        if email:
            aplic = _aplicar_email_por_org(org, email)
            total += aplic
            cp["emails_aplicados"] = cp.get("emails_aplicados", 0) + aplic
            log(f"  ✉️ {org[:35]} ({n} ev) → {email} ({aplic} filas)")
        else:
            cp["org_email_intentos"][org.lower()] = it + 1
            cp.setdefault("org_email_ult", {})[org.lower()] = time.time()
            log(f"  · {org[:35]}: sin email (intento {it+1}/3)")
        time.sleep(1)
    if total:
        log(f"  FASE EMAIL: +{total} emails")
    return total


def main():
    cp = _cargar_checkpoint()
    log("Atacante paralelo arrancando (orgs + emails).")
    while True:
        try:
            g = _aplicar_conocidos()
            if g[0] or g[1]:
                log(f"  🧠 conocimiento experto: +{g[0]} orgs, +{g[1]} emails")
            agru = _ciudades_sin_org()
            log(f"Frentes: {sum(a['n'] for a in agru.values())} eventos FB sin org "
                f"en {len(agru)} ciudades")
            ataque_org(cp, agru)
            ataque_email(cp)
            _guardar_checkpoint(cp)
        except Exception as e:
            log(f"⚠️ error pasada: {str(e)[:120]}")
        time.sleep(PAUSA_ENTRE_PASADAS)


if __name__ == "__main__":
    main()