import sys
import time
from pathlib import Path

_ROOT = Path("/Users/angelgarcia/dharmabot")
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.enriquecer_fb_og import enriquecer

if __name__ == "__main__":
    print("TEST 2: enriquecer 10 links, rotacion cada 40 (rara)", flush=True)
    t0 = time.time()
    stats = enriquecer(
        max_fetches=10,
        rotar_cada=40,
        timeout_por_url=10,
        tiempo_max_seg=150,
    )
    print("Stats:", stats, flush=True)
    print("Tiempo total: %.1fs" % (time.time() - t0), flush=True)