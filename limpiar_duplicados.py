import csv
import shutil
import time
import sys
from pathlib import Path

CSV = Path("/Users/angelgarcia/dharmabot/eventos_encontrados.csv")
VACIOS = {"", "N/A", "None", "nan", "NA", "NONE"}

BASURA_LINKS = {
    "https://www.facebook.com/events/",
    "https://setlineapp.com/festivals/genre/psytrance",
    "https://psymedia.co.za/calendar/",
    "N/A", "",
}


def es_clave_raya(l):
    """un link-lista/duplicado obvio de eventos"""
    if not isinstance(l, str) or not l.strip():
        return True
    l = l.strip()
    return l.startswith("facebook.com/events") and len(l) < 42


def completo(r):
    """puntuacion de la fila: mas campos poblados = mejor"""
    return sum(1 for k, v in r.items() if (v or "").strip() not in VACIOS)


def main():
    if not CSV.exists():
        print("CSV no existe"); sys.exit(1)

    backup = CSV.with_name(f"backup_prelimpieza_{int(time.time())}.csv")
    shutil.copy2(CSV, backup)
    print("Backup:", backup.name)

    with open(CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    cols = list(rows[0].keys())
    total = len(rows)

    # 1. Separar basura (link no-evento)
    mantienen = []
    basura = 0
    for r in rows:
        l = (r.get("link") or "").strip()
        if l in BASURA_LINKS:
            basura += 1
            continue
        mantienen.append(r)

    # 2. Colapsar duplicados por link, conservando la fila mas completa
    mejores = {}
    for r in mantienen:
        l = (r.get("link") or "").strip()
        actual = mejores.get(l)
        if actual is None or completo(r) > completo(actual):
            mejores[l] = r

    final = list(mejores.values())
    dup_colapsados = len(mantienen) - len(final)

    # escribir una sola vez
    with open(CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(final)

    print(f"Original: {total}")
    print(f"Basura eliminada: {basura}")
    print(f"Duplicados colapsados: {dup_colapsados}")
    print(f"Eventos unicos finales: {len(final)}")

    # verificar integridad
    with open(CSV, encoding="utf-8") as f:
        fcount = sum(1 for _ in csv.DictReader(f))
    print(f"Integridad escritura: {len(final)} filas == {fcount} leidas -> {'OK' if fcount==len(final) else 'FALLO'}")


if __name__ == "__main__":
    main()