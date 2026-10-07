import sys
import time
from pathlib import Path

_ROOT = Path("/Users/angelgarcia/dharmabot")
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.enriquecer_fb_og import enriquecer

# Presupuesto por lote y máximo total de fetchs
LOTE = 300        # cuántos fetch por llamada a enriquecer()
TIEMPO_LOTE = 300 # 5 min por lote
MAX_LOTES = 40    # hasta 12000 fetchs posibles (redundante, es incremental)
PAUSA = 45        # entre lotes para no saturar Tor

total_fetchs = 0
for lote in range(1, MAX_LOTES + 1):
    print(f"\n=== LOTE {lote}/{MAX_LOTES} ===", flush=True)
    try:
        stats = enriquecer(max_fetches=LOTE, rotar_cada=8,
                           timeout_por_url=12, tiempo_max_seg=TIEMPO_LOTE)
        print(f"Lote {lote} stats: {stats}", flush=True)
    except Exception as e:
        print(f"Lote {lote} error: {e}", flush=True)
        time.sleep(PAUSA)
        continue

    total_fetchs += stats.get("revisadas", 0) if isinstance(stats, dict) else 0
    # Si ya no hay filas FB vacías, paramos (incremental consume todo)
    if isinstance(stats, dict) and stats.get("revisadas", 0) == 0:
        print("Sin mas filas FB por enriquecer. Terminando.", flush=True)
        break
    print(f"Acumulado fetchs: {total_fetchs}", flush=True)
    time.sleep(PAUSA)

print("DONE enriquecimiento FB-OG", flush=True)