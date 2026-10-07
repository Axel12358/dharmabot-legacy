import csv
import shutil
import time
import sys
from pathlib import Path

CSV = Path("/Users/angelgarcia/dharmabot/eventos_encontrados.csv")

# Mapeo país (en ES y EN) -> (continente, subcontinente)
PAIS_CONTINENTE = {
    "Alemania": ("Europa", "Europa occidental"), "Germany": ("Europa", "Europa occidental"),
    "España": ("Europa", "Europa meridional"), "Spain": ("Europa", "Europa meridional"),
    "Francia": ("Europa", "Europa occidental"), "France": ("Europa", "Europa occidental"),
    "Reino Unido": ("Europa", "Europa occidental"), "United Kingdom": ("Europa", "Europa occidental"), "UK": ("Europa", "Europa occidental"), "Inglaterra": ("Europa", "Europa occidental"),
    "Países Bajos": ("Europa", "Europa occidental"), "Netherlands": ("Europa", "Europa occidental"),
    "India": ("Asia", "Asia meridional"),
    "Italia": ("Europa", "Europa meridional"), "Italy": ("Europa", "Europa meridional"),
    "México": ("América del Norte", "América del Norte"),
    "Tailandia": ("Asia", "Asia sudoriental"),
    "Estados Unidos": ("América del Norte", "América del Norte"), "United States": ("América del Norte", "América del Norte"),
    "Brasil": ("América del Sur", "América del Sur"), "Brazil": ("América del Sur", "América del Sur"),
    "Japón": ("Asia", "Asia oriental"), "Japan": ("Asia", "Asia oriental"),
    "Israel": ("Asia", "Asia occidental"),
    "Suiza": ("Europa", "Europa occidental"), "Switzerland": ("Europa", "Europa occidental"),
    "Australia": ("Oceanía", "Oceanía"),
    "Portugal": ("Europa", "Europa meridional"),
    "Sudáfrica": ("África", "África austral"),
    "Indonesia": ("Asia", "Asia sudoriental"),
    "Austria": ("Europa", "Europa occidental"),
    "Bélgica": ("Europa", "Europa occidental"), "Belgium": ("Europa", "Europa occidental"),
    "Suecia": ("Europa", "Europa septentrional"),
    "Dinamarca": ("Europa", "Europa septentrional"),
    "Polonia": ("Europa", "Europa oriental"), "Poland": ("Europa", "Europa oriental"),
    "Argentina": ("América del Sur", "América del Sur"),
    "Turquía": ("Asia", "Asia occidental"),
    "República Checa": ("Europa", "Europa oriental"), "Czech Republic": ("Europa", "Europa oriental"),
    "Marruecos": ("África", "África septentrional"),
    "Grecia": ("Europa", "Europa meridional"), "Greece": ("Europa", "Europa meridional"),
    "Irlanda": ("Europa", "Europa occidental"), "Ireland": ("Europa", "Europa occidental"),
    "Egipto": ("África", "África septentrional"),
    "Hungría": ("Europa", "Europa oriental"),
    "Corea del Sur": ("Asia", "Asia oriental"),
    "Noruega": ("Europa", "Europa septentrional"),
    "Nueva Zelanda": ("Oceanía", "Oceanía"), "New Zealand": ("Oceanía", "Oceanía"),
    "Colombia": ("América del Sur", "América del Sur"),
    "Ucrania": ("Europa", "Europa oriental"),
    "Liberia": ("África", "África occidental"),
    "Eslovenia": ("Europa", "Europa meridional"), "Slovenia": ("Europa", "Europa meridional"),
    "Macedonia": ("Europa", "Europa meridional"),
    "Montenegro": ("Europa", "Europa meridional"),
    "Rumanía": ("Europa", "Europa oriental"), "Romania": ("Europa", "Europa oriental"),
    "Eslovaquia": ("Europa", "Europa oriental"), "Slovakia": ("Europa", "Europa oriental"),
    "Serbia": ("Europa", "Europa meridional"),
    "Croacia": ("Europa", "Europa meridional"), "Croatia": ("Europa", "Europa meridional"),
    # --- añadidos por auditoría de coherencia (países reales sin mapa) ---
    "Camboya": ("Asia", "Asia sudoriental"), "Cambodia": ("Asia", "Asia sudoriental"),
    "Bolivia": ("América del Sur", "América del Sur"),
    "Chile": ("América del Sur", "América del Sur"),
    "Perú": ("América del Sur", "América del Sur"), "Peru": ("América del Sur", "América del Sur"),
    "Uruguay": ("América del Sur", "América del Sur"),
    "Ecuador": ("América del Sur", "América del Sur"),
    "Paraguay": ("América del Sur", "América del Sur"),
    "Venezuela": ("América del Sur", "América del Sur"),
    "Thailand": ("Asia", "Asia sudoriental"),
    "Rusia": ("Europa", "Europa oriental"), "Russia": ("Europa", "Europa oriental"),
    "Norway": ("Europa", "Europa septentrional"),
    "Estonia": ("Europa", "Europa oriental"),
    "Mexico": ("América del Norte", "América del Norte"),
    "Malasia": ("Asia", "Asia sudoriental"), "Malaysia": ("Asia", "Asia sudoriental"),
    "Nepal": ("Asia", "Asia meridional"),
    "Panamá": ("América del Norte", "América del Norte"), "Panama": ("América del Norte", "América del Norte"),
    "Turkey": ("Asia", "Asia occidental"),
    "Malta": ("Europa", "Europa meridional"),
    "Hungary": ("Europa", "Europa oriental"),
    "Albania": ("Europa", "Europa meridional"),
    "Chipre": ("Europa", "Europa meridional"), "Cyprus": ("Europa", "Europa meridional"),
    "Vietnam": ("Asia", "Asia sudoriental"),
    "Georgia": ("Asia", "Asia occidental"),
    "El Salvador": ("América del Norte", "América del Norte"),
    "Palestina": ("Asia", "Asia occidental"), "Palestine": ("Asia", "Asia occidental"),
    "Taiwán": ("Asia", "Asia oriental"), "Taiwan": ("Asia", "Asia oriental"),
    "Denmark": ("Europa", "Europa septentrional"),
    "Singapur": ("Asia", "Asia sudoriental"), "Singapore": ("Asia", "Asia sudoriental"),
    "Holanda": ("Europa", "Europa occidental"),
    "Finlandia": ("Europa", "Europa septentrional"), "Finland": ("Europa", "Europa septentrional"),
    "Luxemburgo": ("Europa", "Europa occidental"), "Luxembourg": ("Europa", "Europa occidental"),
    "South Africa": ("África", "África austral"),
}

VACIOS = {"", "N/A", "None", "nan", "NA", "NONE"}


def main():
    if not CSV.exists():
        print("CSV no existe"); sys.exit(1)

    backup = CSV.with_name(f"backup_continente_{int(time.time())}.csv")
    shutil.copy2(CSV, backup)
    print("Backup:", backup.name)

    with open(CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    cols = list(rows[0].keys())
    total = len(rows)

    # Asegurar columnas continente/subcontinente
    if "continente" not in cols:
        for r in rows: r["continente"] = ""
        cols.append("continente")
    if "subcontinente" not in cols:
        for r in rows: r["subcontinente"] = ""
        cols.append("subcontinente")

    rellenados = 0
    sin_mapa = set()
    for r in rows:
        pais = (r.get("pais") or "").strip()
        cont = (r.get("continente") or "").strip().upper()
        if cont in VACIOS and pais and pais.upper() not in VACIOS:
            # normalizar título (Spain->España para match, pero ya tenemos ambos)
            meta = PAIS_CONTINENTE.get(pais)
            if meta is None:
                # intentar por case-insensitive
                for k, v in PAIS_CONTINENTE.items():
                    if k.lower() == pais.lower():
                        meta = v; break
            if meta:
                r["continente"] = meta[0]
                r["subcontinente"] = meta[1]
                rellenados += 1
            else:
                sin_mapa.add(pais)

    # escribir una sola vez
    with open(CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)

    print(f"Rellenados {rellenados}/{total} con continente desde país.")
    if sin_mapa:
        print("PAÍSES SIN MAPEO (quedaron en blanco):", sorted(sin_mapa))

    # verificar integridad
    with open(CSV, encoding="utf-8") as f:
        final = sum(1 for _ in csv.DictReader(f))
    ok = final == total
    print(f"Integridad: total_original={total} total_final={final} -> {'OK' if ok else 'FALLO'}")


if __name__ == "__main__":
    main()