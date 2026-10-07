import sys
import time
sys.path.insert(0, "/Users/angelgarcia/dharmabot")
from enrich_loop import enriquecer_campo, extraer_organizador

BLOQUE = 95  # segundos por trama, < 120 seg limite de la herramienta

if __name__ == "__main__":
    # Paso 1: organizador (solo Facebook). Se ejecuta por tramos cortos y resume por checkpoint.
    while True:
        res = enriquecer_campo(
            "organizador",
            lambda h, url: extraer_organizador(h, url),
            url_filtro="facebook.com/events/",
            max_seconds=BLOQUE,
        )
        if res and res.get("cortado"):
            # quedan mas eventos; nueva trama
            time.sleep(1)
            continue
        break  # cola vacia o completo