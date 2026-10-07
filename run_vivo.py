#!/usr/bin/env python3
"""
Run del orquestador en primer plano (output en vivo en terminal).
Uso: python3 run_vivo.py
"""
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.orquestador import orquestar_scrapers

def main():
    print("=" * 60)
    print("🚀 Run VIVO del Orquestador — output en terminal")
    print("=" * 60)
    nuevos = orquestar_scrapers()
    print("\n" + "=" * 60)
    print(f"✅ TOTAL EVENTOS NUEVOS AÑADIDOS: {len(nuevos)}")
    for n in nuevos[:30]:
        print(f"   • {n.get('nombre','?')} | {n.get('fuente','?')} | {n.get('pais','')}")
    print("=" * 60)

if __name__ == "__main__":
    main()
