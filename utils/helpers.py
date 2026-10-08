#!/usr/bin/env python3
"""
Funciones auxiliares para el bot.
"""

import csv
import json
from pathlib import Path

def load_config(config_path="configs_exitosas/config_grupos.json"):
    """Carga la configuración desde un archivo JSON."""
    try:
        with open(config_path) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"⚠️ Configuración no encontrada: {config_path}")
        return {}

def deduplicar_eventos(eventos, claves=("nombre", "fecha", "lugar")):
    """Elimina duplicados basándose en una clave compuesta.

    Args:
        eventos: lista de dicts con datos de eventos.
        claves: tupla de campos para formar la clave de deduplicación.

    Returns:
        Lista de eventos sin duplicados (conserva el primero encontrado).
    """
    vistos = set()
    unicos = []
    for ev in eventos:
        k = tuple(str(ev.get(c, "") or "").strip().lower() for c in claves)
        if k not in vistos:
            vistos.add(k)
            unicos.append(ev)
    return unicos


def validar_evento(evento):
    """Verifica que un evento tenga datos mínimos de calidad.

    Criterios:
    - fecha: formato YYYY-MM-DD o "N/A" (aceptable si fuente es
      especializada como Goabase).
    - lugar: no vacío ni "N/A" para fuentes generales.
    - link: URL http(s) válida.
    - nombre: no vacío.

    Returns:
        True si el evento pasa la validación.
    """
    nombre = (evento.get("nombre") or "").strip()
    if not nombre or nombre == "N/A":
        return False

    link = (evento.get("link") or "").strip()
    if not link or not link.startswith("http"):
        return False

    fecha = (evento.get("fecha") or "").strip()
    if fecha and fecha != "N/A":
        import re as _re
        if not _re.match(r"^\d{4}-\d{2}-\d{2}", fecha):
            return False

    lugar = (evento.get("lugar") or "").strip()
    fuente = (evento.get("fuente") or "").strip()
    # Fuentes donde el lugar no siempre está disponible
    fuentes_sin_lugar = {"Goabase", "Psytrance.pl", "IsraTrance",
                         "Ektoplazm", "Songkick", "Facebook (público SERP)"}
    if fuente not in fuentes_sin_lugar:
        if not lugar or lugar == "N/A":
            return False

    return True


def limpiar_eventos(eventos):
    """Filtra eventos inválidos y duplicados.

    Aplica `validar_evento` y luego `deduplicar_eventos`.
    """
    validos = [ev for ev in eventos if validar_evento(ev)]
    return deduplicar_eventos(validos)


def save_csv(data, filename="eventos_encontrados.csv"):
    """Guarda datos en un archivo CSV de forma ADITIVA (nunca sobrescribe).

    Fusiona `data` con las filas ya existentes en el CSV (dedup por
    link+fuente), respetando la regla del proyecto "sumar nunca restar":
    los eventos previos nunca se pierden aunque un scrapeador falle.

    Usa el lock cooperativo core.csv_lock para no pisar a otros procesos
    (orquestador, loop_completar, venue_enricher, mcp_clasificar).
    """
    if not data:
        print("⚠️ No hay datos nuevos para guardar (se conserva el CSV existente)")
        return
    try:
        def _clave(ev):
            return (
                (ev.get("link") or ev.get("url") or ev.get("source_url") or "").strip().lower(),
                (ev.get("fuente") or "").strip().lower(),
            )

        from core.csv_lock import csv_locked_rows

        # Reclasificación: eventos no-psy nunca entran a main; van a su CSV.
        if filename == "eventos_encontrados.csv":
            _no_psy = [e for e in data
                       if (e.get("subgenero") or "").strip().lower() == "no_psy"]
            if _no_psy:
                save_csv(_no_psy, "non_psy.csv")
                print(f"🔄 {len(_no_psy)} no-psy redirigidos a non_psy.csv")
            data = [e for e in data
                    if (e.get("subgenero") or "").strip().lower() != "no_psy"]
            if not data:
                print("✅ CSV sin filas psy nuevas; solo no_psy redirigidos (no se toca main)")
                return

        with csv_locked_rows(filename, timeout=180) as (existentes, fieldnames):
            vistos = {_clave(e) for e in existentes}
            nuevos = 0
            for ev in data:
                ev = dict(ev)
                link = (ev.get("link") or ev.get("url") or ev.get("source_url") or "N/A")
                ev["link"] = link
                k = _clave(ev)
                if k not in vistos:
                    vistos.add(k)
                    existentes.append(ev)
                    nuevos += 1
        print(f"✅ CSV guardado (aditivo): {filename} ({len(existentes)} filas, +{nuevos} nuevos)")
    except Exception as e:
        print(f"❌ Error guardando CSV: {e}")
