#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Guarda central: distingue emails de contacto reales de basura/rellenos.

Fuente única de verdad para el saneo de emails (usada por depurar_emails_masivos,
el loop (auto-sanado) y el escritor fusionado). No importa nada pesado.
"""
import re

# Plantillas, reportes, pasarelas y artefactos de parseo: nunca son del organizador
JUNK_RE = re.compile(
    r'^u003[ce]'                                   # artefactos urlencoded "\u003e"
    r'|^scams@|^reportphishing@|^abuse@'
    r'|^privacy-requests@|^group-subscriptions@'
    r'|^yhteydenotto@'                              # "contacto" en plantilla finlandesa
    r'|legal@partyx\.info'
    r'|khalti\.com'
    r'|newcastleherald\.com\.au'
    r'|support\.yandex'
    r'|policies@di\.fm'
    r'|eliteadultcasting\.com'
    r'|@example\.|@domain\.|@esimerkki\.|@community\.org$'
    r'|@email\.(fr|nl|fi|cz|it|de)$|@dominio\.|@correo\.'
    r'|linktr\.ee|beacons\.ai|linkin\.bio|bio\.fm'
    r'|^(votre|jouw|you|your)@',
    re.I,
)

# Default masivo: se limpia salvo que el evento sea de ese propio colectivo
DEFAULT_MASIVO = 'alteredstatepsy@gmail.com'
RE_ALTERED = re.compile(r'\baltered\b|\baltered state\b')

# Emails verificados manualmente como ajenos a la escena (personas/entidades no-psy)
KNOWN_FALSOS = {
    'impallari@gmail.com',                 # tipógrafo (otro tema)
    'snadella@microsoft.com',              # corporativo, otro tema
    'business@stockholm.se',               # gobierno de Estocolmo
    'sales@fortifiedestate.com',           # inmobiliaria
    'edu@readymag.com',                    # herramienta de diseño
    'coaching@wayofdk.de',                 # coaching
    'ticketing@tate.org.uk',               # museo (Tate)
    'rowan.wijnberg@marriott.com',         # cadena hotelera
    'customerservices@panchotours.com',
        'thomas.tachelet@outlook.com',    # tours turísticos
    'jurriola-schonewolf@asburyfirst.org', # iglesia
}


def _altered_legit(row):
    blob = ((row.get('organizador') or '') + ' ' + (row.get('nombre') or '')).lower()
    return bool(RE_ALTERED.search(blob))


def es_email_basura(email, row=None):
    """¿Este email es basura/relleno (no un contacto de organizador real)?

    `row` permite la excepción del default masivo (filas del propio colectivo).
    """
    e = (email or '').strip().lower()
    if not e or '@' not in e:
        return False if e in ('', 'n/a') else True
    if e in KNOWN_FALSOS:
        return True
    if JUNK_RE.search(e):
        return True
    if e == DEFAULT_MASIVO and row is not None and not _altered_legit(row):
        return True
    return False
