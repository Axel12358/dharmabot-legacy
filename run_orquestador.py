#!/usr/bin/env python3
"""Wrapper para ejecutar el orquestador con el path correcto."""
import sys
sys.path.insert(0, "/Users/angelgarcia/dharmabot")
from core.orquestador import orquestar_scrapers

if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    nuevos = orquestar_scrapers(dry_run=dry)
    print(f"\n(CLI) Eventos nuevos añadidos: {len(nuevos)}")
