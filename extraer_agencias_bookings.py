#!/usr/bin/env python3
"""Alias histórico de `buscar_agencias.py`.

Antes extraía solo del dataset; ahora delega en el extractor canónico para
evitar dos formatos/salidas divergentes sobre `agencias_bookings.csv`.
Mantiene los mismos flags (`--solo-escena`, `--min-menciones`).

Uso: .venv/bin/python extraer_agencias_bookings.py [--solo-escena] [--min-menciones N]
"""
from buscar_agencias import main

if __name__ == '__main__':
    main()
