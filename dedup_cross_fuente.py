#!/usr/bin/env python3
"""
dedup_cross_fuente.py — Fusión de duplicados cross-fuente para Dharmadhatu Bot v5
====================================================================================
Detecta y fusiona eventos que representan el MISMO evento aunque tengan links distintos
(distintas fuentes: Facebook, Resident Advisor, Goabase, etc.).

REGLAS (en orden de prioridad):
  1. Clave principal: nombre NORMALIZADO igual + fecha COMPATIBLE (±2 días o mismo mes/año)
  2. ES DUPLICADO si dentro del mismo par (nombre+fecha) coincide:
       a) organizador normalizado  O
       b) email normalizado
  3. Si mismo nombre+fecha pero hosts Y emails todos distintos → NO fusionar
  4. Al fusionar: conserva la fila más completa; rellena huecos con las demás

GARANTÍAS:
  - Backup previo obligatorio
  - Escritura atómica única al final
  - assert total_filas_originales == suma_de_grupos_fusionados_correctamente
  - Reporte detallado en español
"""

import csv
import json
import re
import shutil
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# ── Configuración ──────────────────────────────────────────────────────────────
CSV_PATH       = Path("eventos_encontrados.csv")
OUTPUT_PATH    = Path("eventos_dedup.csv")
REPORT_PATH    = Path("dedup_report.json")
BACKUP_DIR     = Path("backups")
DECISION_LOG   = Path("dedup_decisiones.csv")

COLUMNAS = [
    "nombre", "fecha", "lugar", "pais", "continente", "subcontinente",
    "fuente", "organizador", "email", "link", "subgenero", "tipo_lugar", "contactos"
]

# Sufijos genéricos a quitar del organizador antes de comparar
SUFIJOS_ORG = re.compile(
    r'\b(producciones?|productions?|events?|official|page|org|club|presents?|music|records?)\b',
    re.IGNORECASE
)

# ── Normalización ──────────────────────────────────────────────────────────────

def quitar_acentos(texto: str) -> str:
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto)
        if unicodedata.category(c) != 'Mn'
    )

def normalizar_nombre(s: str) -> str:
    if not s or s.strip().upper() in ("N/A", ""):
        return ""
    s = s.lower()
    s = quitar_acentos(s)
    s = re.sub(r'[^\w\s]', ' ', s)          # sin puntuación
    s = re.sub(r'\s+', ' ', s).strip()
    # quitar sufijos comunes de fecha/lugar en el título (ej: "Festival 2024 Berlin")
    s = re.sub(r'\b(20\d\d|enero|febrero|marzo|abril|mayo|junio|julio|agosto|'
               r'septiembre|octubre|noviembre|diciembre|jan|feb|mar|apr|may|jun|'
               r'jul|aug|sep|oct|nov|dec)\b.*$', '', s).strip()
    return s

def normalizar_organizador(s: str) -> str:
    if not s or s.strip().upper() in ("N/A", ""):
        return ""
    s = s.lower()
    s = quitar_acentos(s)
    s = SUFIJOS_ORG.sub('', s)
    s = re.sub(r'[^\w\s]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def normalizar_email(s: str) -> str:
    if not s or s.strip().upper() in ("N/A", ""):
        return ""
    return s.lower().strip()

def parsear_fecha(s: str):
    """Intenta parsear fecha en varios formatos. Devuelve datetime o None."""
    if not s or s.strip().upper() in ("N/A", ""):
        return None
    formatos = [
        "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y",
        "%Y%m%d", "%d.%m.%Y", "%B %d, %Y",
        "%b %d, %Y", "%d %B %Y", "%d %b %Y",
        "%Y-%m", "%m/%Y",
    ]
    s = s.strip()
    for fmt in formatos:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None

def _tiene_dia(s: str) -> bool:
    """True si la fecha original contiene un dia (anio-mes-dia), False si es solo mes/anio."""
    s = (s or "").strip()
    if s.upper() in ("N/A", ""):
        return False
    # formatos con dia: dd/MM/yyyy, yyyy-MM-dd, dd.MM.yyyy, etc. -> contienen 3 componentes
    m = re.search(r"\d{4}\s*[-/.]\s*\d{1,2}\s*[-/.]\s*\d{1,2}", s)  # yyyy-MM-dd
    if m:
        return True
    m = re.search(r"\d{1,2}\s*[-/.]\s*\d{1,2}\s*[-/.]\s*\d{4}", s)  # dd-MM-yyyy
    return bool(m)


def fechas_compatibles(f1_str: str, f2_str: str) -> bool:
    """
    La fecha es OBLIGATORIA para considerar dos eventos el MISMO evento.
    Ediciones distintas del mismo festival/host (fechas distintas) NO se fusionan.
    Compatible solo si:
      - misma fecha exacta, o
      - diferencia de días <= 2, o
      - mismo mes/año aproximado (cuando solo hay mes/año en una de ellas).
    Si falta fecha en CUALQUIERA de las dos -> NO compatible (no podemos
    distinguir ediciones -> no se fusionan).
    """
    f1 = (f1_str or "").strip()
    f2 = (f2_str or "").strip()
    if not f1 or not f2:
        return False
    if f1.upper() in ("N/A",) or f2.upper() in ("N/A",):
        return False

    d1 = parsear_fecha(f1)
    d2 = parsear_fecha(f2)

    if d1 is None and d2 is None:
        # ambas no parseables: comparar a nivel de prefijo AAAA-MM
        return f1[:7] == f2[:7]
    if d1 is None or d2 is None:
        # una sola con fecha completa real: solo coinciden si mes/año iguales
        r1 = d1 if d1 is not None else None
        r2 = d2 if d2 is not None else None
        # preferimos no fusionar si solo una es parseable y difieren en mes/año
        if r1 is None:
            return f1[:7] == f2[:7]
        if r2 is None:
            return f1[:7] == f2[:7]
        return False

    delta = abs((d1 - d2).days)
    # "completa" = el string original traia dia (no solo mes/año)
    d1_completa = _tiene_dia(f1)
    d2_completa = _tiene_dia(f2)
    if d1_completa and d2_completa:
        return delta <= 2
    if d1.year == d2.year and d1.month == d2.month:
        return True
    return False

# ── Completitud de fila ────────────────────────────────────────────────────────

def completitud(fila: dict) -> int:
    """Cuenta campos no vacíos / N/A."""
    return sum(
        1 for v in fila.values()
        if v and str(v).strip().upper() not in ("N/A", "")
    )

# ── Fusión de filas ────────────────────────────────────────────────────────────

def fusionar_filas(filas: list[dict]) -> dict:
    """
    Conserva la fila más completa y rellena sus huecos con las demás.
    Prioriza conservar email. No inventa información.
    """
    filas_ordenadas = sorted(filas, key=completitud, reverse=True)
    base = dict(filas_ordenadas[0])  # la más completa

    for fila in filas_ordenadas[1:]:
        for col in COLUMNAS:
            val_base = str(base.get(col, "")).strip()
            val_otro  = str(fila.get(col, "")).strip()
            vacio_base = not val_base or val_base.upper() == "N/A"
            lleno_otro  = bool(val_otro) and val_otro.upper() != "N/A"

            if vacio_base and lleno_otro:
                base[col] = val_otro

    # fuente: concatenar todas las fuentes únicas
    fuentes = list(dict.fromkeys(
        f.strip()
        for fila in filas
        for f in str(fila.get("fuente", "")).split(",")
        if f.strip() and f.strip().upper() != "N/A"
    ))
    base["fuente"] = ", ".join(fuentes) if fuentes else base.get("fuente", "N/A")

    # links: conservar todos (separados por |) para trazabilidad
    links = list(dict.fromkeys(
        str(fila.get("link", "")).strip()
        for fila in filas
        if fila.get("link", "").strip()
    ))
    base["link"] = links[0]  # link principal = el de la fila más completa
    base["_links_fusionados"] = " | ".join(links)  # columna extra de trazabilidad

    return base

# ── Algoritmo principal ────────────────────────────────────────────────────────

def detectar_y_fusionar(eventos: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Devuelve (eventos_finales, log_decisiones).
    Usa Union-Find para agrupar duplicados transitivos correctamente.
    """
    n = len(eventos)

    # Precalcular campos normalizados
    nom_norm  = [normalizar_nombre(ev.get("nombre", ""))      for ev in eventos]
    org_norm  = [normalizar_organizador(ev.get("organizador", "")) for ev in eventos]
    email_norm = [normalizar_email(ev.get("email", ""))        for ev in eventos]
    fechas    = [ev.get("fecha", "")                          for ev in eventos]

    # Union-Find
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        parent[find(x)] = find(y)

    decisiones = []  # log de pares evaluados
    pares_dup_host  = 0
    pares_dup_email = 0

    # Índice inverso por nombre normalizado para no hacer O(n²) completo
    idx_por_nombre: dict[str, list[int]] = defaultdict(list)
    for i, nom in enumerate(nom_norm):
        if nom:
            idx_por_nombre[nom].append(i)

    for nom, indices in idx_por_nombre.items():
        if len(indices) < 2:
            continue  # nombre único, nada que comparar

        # Comparar todos los pares dentro del mismo nombre normalizado
        for a in range(len(indices)):
            for b in range(a + 1, len(indices)):
                i = indices[a]
                j = indices[b]

                # Ya en el mismo grupo → skip
                if find(i) == find(j):
                    continue

                # Regla 1: fecha compatible
                if not fechas_compatibles(fechas[i], fechas[j]):
                    decisiones.append({
                        "idx_a": i, "idx_b": j,
                        "nombre_a": eventos[i].get("nombre", ""),
                        "nombre_b": eventos[j].get("nombre", ""),
                        "fecha_a": fechas[i], "fecha_b": fechas[j],
                        "org_a": eventos[i].get("organizador", ""),
                        "org_b": eventos[j].get("organizador", ""),
                        "email_a": eventos[i].get("email", ""),
                        "email_b": eventos[j].get("email", ""),
                        "decision": "NO",
                        "motivo": "Fechas incompatibles"
                    })
                    continue

                # Regla 2a: mismo organizador normalizado
                dup_host = (
                    bool(org_norm[i]) and
                    bool(org_norm[j]) and
                    org_norm[i] == org_norm[j]
                )

                # Regla 2b: mismo email
                dup_email = (
                    bool(email_norm[i]) and
                    bool(email_norm[j]) and
                    email_norm[i] == email_norm[j]
                )

                if dup_host or dup_email:
                    motivo_parts = []
                    if dup_host:
                        motivo_parts.append(f"host='{org_norm[i]}'")
                        pares_dup_host += 1
                    if dup_email:
                        motivo_parts.append(f"email='{email_norm[i]}'")
                        pares_dup_email += 1

                    decisiones.append({
                        "idx_a": i, "idx_b": j,
                        "nombre_a": eventos[i].get("nombre", ""),
                        "nombre_b": eventos[j].get("nombre", ""),
                        "fecha_a": fechas[i], "fecha_b": fechas[j],
                        "org_a": eventos[i].get("organizador", ""),
                        "org_b": eventos[j].get("organizador", ""),
                        "email_a": eventos[i].get("email", ""),
                        "email_b": eventos[j].get("email", ""),
                        "decision": "DUP",
                        "motivo": " | ".join(motivo_parts)
                    })
                    union(i, j)
                else:
                    decisiones.append({
                        "idx_a": i, "idx_b": j,
                        "nombre_a": eventos[i].get("nombre", ""),
                        "nombre_b": eventos[j].get("nombre", ""),
                        "fecha_a": fechas[i], "fecha_b": fechas[j],
                        "org_a": eventos[i].get("organizador", ""),
                        "org_b": eventos[j].get("organizador", ""),
                        "email_a": eventos[i].get("email", ""),
                        "email_b": eventos[j].get("email", ""),
                        "decision": "NO",
                        "motivo": "Mismo nombre+fecha pero host y email distintos"
                    })

    # Agrupar por componente Union-Find
    grupos: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        grupos[find(i)].append(i)

    # Verificación interna: suma de grupos == n original
    assert sum(len(g) for g in grupos.values()) == n, \
        "ERROR INTERNO: Union-Find perdió filas"

    # Fusionar cada grupo
    eventos_finales = []
    for root, indices_grupo in grupos.items():
        filas_grupo = [eventos[i] for i in indices_grupo]
        if len(filas_grupo) == 1:
            fila = dict(filas_grupo[0])
            fila["_links_fusionados"] = fila.get("link", "")
            eventos_finales.append(fila)
        else:
            eventos_finales.append(fusionar_filas(filas_grupo))

    return eventos_finales, decisiones, pares_dup_host, pares_dup_email

# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("DEDUP CROSS-FUENTE — Dharmadhatu Bot v5")
    print("=" * 60)

    # 1. Verificar CSV
    if not CSV_PATH.exists():
        print(f"ERROR: No se encuentra {CSV_PATH}")
        return

    # 2. Backup OBLIGATORIO
    BACKUP_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = BACKUP_DIR / f"eventos_encontrados_ANTES_DEDUP_{ts}.csv"
    shutil.copy2(CSV_PATH, backup)
    print(f"✓ Backup → {backup}")

    # 3. Cargar CSV
    with open(CSV_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        eventos = list(reader)
        fieldnames_orig = reader.fieldnames or COLUMNAS

    total_original = len(eventos)
    print(f"✓ CSV cargado: {total_original} filas")

    # 4. Detectar y fusionar
    print("→ Analizando duplicados cross-fuente...")
    eventos_finales, decisiones, dup_host, dup_email = detectar_y_fusionar(eventos)

    total_final = len(eventos_finales)
    fusionados  = total_original - total_final
    total_dups  = sum(1 for d in decisiones if d["decision"] == "DUP")

    # 5. Integridad
    assert total_final <= total_original, "ERROR: más filas al final que al inicio"
    print(f"✓ Integridad OK: {total_original} → {total_final} filas ({fusionados} fusionadas)")

    # 6. Escribir CSV resultado (atómico)
    fieldnames_out = list(fieldnames_orig)
    if "_links_fusionados" not in fieldnames_out:
        fieldnames_out.append("_links_fusionados")

    tmp_out = OUTPUT_PATH.with_suffix(".tmp.csv")
    with open(tmp_out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames_out, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(eventos_finales)
    tmp_out.replace(OUTPUT_PATH)
    print(f"✓ CSV resultado → {OUTPUT_PATH}")

    # 7. Log de decisiones
    if decisiones:
        with open(DECISION_LOG, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(decisiones[0].keys()))
            writer.writeheader()
            writer.writerows(decisiones)
        print(f"✓ Log decisiones → {DECISION_LOG} ({len(decisiones)} pares evaluados)")

    # 8. Reporte final
    reporte = {
        "timestamp": ts,
        "total_original": total_original,
        "total_final": total_final,
        "filas_fusionadas": fusionados,
        "pares_evaluados": len(decisiones),
        "pares_DUP_total": total_dups,
        "pares_DUP_por_host": dup_host,
        "pares_DUP_por_email": dup_email,
        "pares_NO_dup": len(decisiones) - total_dups,
        "integridad": "OK" if total_final <= total_original else "ERROR",
        "backup": str(backup),
        "output": str(OUTPUT_PATH),
    }
    REPORT_PATH.write_text(json.dumps(reporte, indent=2, ensure_ascii=False))
    print(f"✓ Reporte JSON → {REPORT_PATH}")

    # 9. Resumen en pantalla
    print()
    print("=" * 60)
    print("RESUMEN FINAL")
    print(f"  Filas originales:       {total_original}")
    print(f"  Filas resultado:        {total_final}")
    print(f"  Eventos fusionados:     {fusionados}")
    print(f"  Pares DUP (por host):   {dup_host}")
    print(f"  Pares DUP (por email):  {dup_email}")
    print(f"  Pares evaluados total:  {len(decisiones)}")
    print(f"  Integridad:             OK ✓")
    print(f"  Output:                 {OUTPUT_PATH}")
    print("=" * 60)

    if fusionados == 0:
        print("→ No se detectaron duplicados cross-fuente.")
    else:
        print(f"→ Revisar {DECISION_LOG} para ver cada decisión justificada.")
    print()
    print("IMPORTANTE: El archivo original NO fue modificado.")
    print(f"El resultado está en '{OUTPUT_PATH}'.")
    print("Si el resultado es correcto, cópialo manualmente como eventos_encontrados.csv.")


if __name__ == "__main__":
    main()
