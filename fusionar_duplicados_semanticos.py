import csv
import re
import shutil
import sys
import time
import unicodedata
from pathlib import Path

CSV = Path("/Users/angelgarcia/dharmabot/eventos_encontrados.csv")
VACIOS = {"", "N/A", "None", "nan", "NA", "NONE"}


def norm(s):
    """minúsculas, sin acentos, sin puntuación extrema, espacios simples."""
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def norm_org(s):
    s = norm(s)
    # quitar sufijos genéricos irrelevantes para comparar host
    for suf in (" org", " events", " page", " official", " producciones", " productions"):
        if s.endswith(suf) and len(s) > len(suf) + 1:
            s = s[: -len(suf)].strip()
    return s


def norm_email(s):
    if not s:
        return ""
    return (s or "").strip().lower()


def norm_fecha(s):
    """fecha normalizada YYYYMMDD; si no, intenta extraer mes/año."""
    s = (s or "").strip()
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        y, mo, d = m.groups()
        return f"{y}{int(mo):02d}{int(d):02d}"
    m2 = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", s)  # dd/mm/yyyy
    if m2:
        d, mo, y = m2.groups()
        return f"{y}{int(mo):02d}{int(d):02d}"
    return ""


def completo(r):
    return sum(1 for k, v in r.items() if (v or "").strip() not in VACIOS)


def fechas_compatibles(a, b):
    """misma fecha, o diferencia <=2 dias, o mismo mes/anio sin dia (fecha aproximada)."""
    if not a or not b:
        return True
    fa, fb = norm_fecha(a), norm_fecha(b)
    if fa and fb and len(fa) == 8 and len(fb) == 8:
        import datetime
        try:
            da = datetime.date(int(fa[:4]), int(fa[4:6]), int(fa[6:8]))
            db = datetime.date(int(fb[:4]), int(fb[4:6]), int(fb[6:8]))
            return abs((db - da).days) <= 2
        except ValueError:
            pass
    # igual mes/anio
    if fa and fb and len(fa) >= 6 and len(fb) >= 6 and fa[:6] == fb[:6]:
        return True
    return False


def es_duplicado(a, b):
    """mismo nombre normalizado + (mismo organizador/host o mismo email)."""
    na, nb = norm(a.get("nombre", "")), norm(b.get("nombre", ""))
    if not na or not nb or na != nb:
        return False
    # 1) mismo host/organizador
    oa, ob = norm_org(a.get("organizador", "")), norm_org(b.get("organizador", ""))
    if oa and ob and oa == ob:
        return True
    # 2) mismo email de contacto (aunque no coincida organizador)
    ea, eb = norm_email(a.get("email", "")), norm_email(b.get("email", ""))
    if ea and eb and ea == eb and not _misma_fila(a, b):
        return True
    return False


def _misma_fila(a, b):
    return a is b


def main():
    if not CSV.exists():
        print("CSV no existe"); sys.exit(1)

    backup = CSV.with_name(f"backup_dedup_semantico_{int(time.time())}.csv")
    shutil.copy2(CSV, backup)
    print("Backup:", backup.name)

    with open(CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    cols = list(rows[0].keys())
    total = len(rows)

    # agrupar por nombre normalizado
    grupos = {}
    for r in rows:
        n = norm(r.get("nombre", ""))
        if not n:
            continue
        grupos.setdefault(n, []).append(r)

    fusionados = 0
    mantener = []
    for n, g in grupos.items():
        if len(g) == 1:
            mantener.append(g[0])
            continue
        # dentro del grupo, fusionar pares que comparten host o email
        usados = [False] * len(g)
        for i in range(len(g)):
            if usados[i]:
                continue
            # buscar con quien fusionar
            base = g[i]
            j = i + 1
            while j < len(g):
                if not usados[j] and es_duplicado(base, g[j]):
                    # fusionar: quedarse con la mas completa, rellenando vacios
                    mejor = base if completo(base) >= completo(g[j]) else g[j]
                    otras = [g[j]] if mejor is base else [base]
                    for o in otras:
                        for k in cols:
                            if (mejor.get(k) or "").strip() in VACIOS and (o.get(k) or "").strip():
                                mejor[k] = o[k]
                    base = mejor
                    usados[j] = True
                    fusionados += 1
                j += 1
            usados[i] = True
            mantener.append(base)

    # atomic write
    tmp = CSV.with_name("_dedup.nuevo.csv")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(mantener)
    tmp.replace(CSV)

    with open(CSV, encoding="utf-8") as f2:
        fcount = sum(1 for _ in csv.DictReader(f2))

    print(f"Original:        {total}")
    print(f"Duplicados fusionados: {fusionados}")
    print(f"Eventos finales: {len(mantener)}")
    print(f"Integridad: {len(mantener)} filas == {fcount} leidas -> {'OK' if fcount==len(mantener) else 'FALLO'}")


if __name__ == "__main__":
    main()