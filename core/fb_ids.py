#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extracción de IDs de eventos de Facebook (versión única del proyecto)."""
import re


def extraer_id(link: str):
    """Extrae el ID numérico de FB de un link de evento. Soporta:
      - https://www.facebook.com/events/<ID>
      - https://www.facebook.com/events/<lugar>/<slug>/<ID>   (5,775 filas)
      - https://www.facebook.com/events.php?id=<ID>
    El ID NUNCA es prefijo: es el ÚLTIMO número de 10+ dígitos del link
    (los 5,775 IDs reales del CSV miden 15-17 dígitos, los cortos son años/horarios).
    """
    link = (link or '').strip()
    m = re.search(r'[?&]id=(\d{10,})', link)
    if m:
        return m.group(1)
    nums = re.findall(r'(\d{10,})', link)
    if nums:
        return nums[-1]
    return None
