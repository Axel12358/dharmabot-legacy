#!/usr/bin/env python3
"""
Loop reclasificador — restaura eventos eliminados por filtro_falsos
si son EVENTO real (fecha+lugar+link).

Criterio EVENTO: tiene link + fecha + lugar + keyword psy en nombre/lugar/org.
Solo RUIDO si: sin link y sin fecha, o promo sin estructura de evento.

Psy keywords válidos (NO spam): zenon, dark psy, forest, prog, goa, fullon, etc.
"""
import csv, re, os
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent
BAK = ROOT / "eventos_encontrados.csv.bak_filtro_falsos"
CSV = ROOT / "eventos_encontrados.csv"
PSY_KEYS = ["psy","goa","zenon","forest","dark","prog","progressive","twilight","hitech","hi-tech","fullon","full on","chill","suomi","trance","ritual","gathering","ceremony","celebration"]

def es_evento(r):
    if not r.get("link","").strip():
        return False
    if not r.get("fecha","").strip() or r.get("fecha","").strip().lower()=="n/a":
        return False
    nombre = (r.get("nombre","")+r.get("lugar","")+r.get("organizador","")).lower()
    return any(k in nombre for k in PSY_KEYS)

def subgenero_de(nombre):
    n=nombre.lower()
    if any(k in n for k in ["zenon"]): return "zenon"
    if "dark" in n: return "darkpsy"
    if "forest" in n: return "forest"
    if "progressive" in n or n.strip()=="prog ceremony" or "prog " in n: return "progressive"
    if "goa" in n: return "goa"
    if "hitech" in n or "hi-tech" in n: return "hitech"
    if "fullon" in n or "full on" in n: return "fullon"
    if "chill" in n: return "psychill"
    if "twilight" in n: return "twilight"
    return "psytrance"

bak = list(csv.DictReader(open(BAK, encoding="utf-8")))
cur = list(csv.DictReader(open(CSV, encoding="utf-8")))
cur_links = set(r.get("link","") for r in cur)
eliminados = [r for r in bak if r.get("link","") not in cur_links]
a_restaurar = [r for r in eliminados if es_evento(r)]
ruido = [r for r in eliminados if not es_evento(r)]
print(f"Eliminados: {len(eliminados)}")
print(f"A restaurar (EVENTO): {len(a_restaurar)}")
print(f"Ruido real: {len(ruido)}")
print("Top nombres a restaurar:", Counter(r.get("nombre","") for r in a_restaurar).most_common(5))
for r in a_restaurar:
    if not r.get("subgenero","").strip():
        r["subgenero"]=subgenero_de(r.get("nombre",""))
# merge sin duplicar
fieldnames = list(cur[0].keys()) if cur else list(bak[0].keys())
merged = cur + a_restaurar
# dedup por link
seen={}
for r in merged:
    k=r.get("link","") or r.get("nombre","")+r.get("fecha","")
    if k not in seen:
        seen[k]=r
out=list(seen.values())
print(f"CSV final: {len(out)} filas (antes {len(cur)}, +{len(out)-len(cur)} restauradas)")
# backup antes de escribir
import shutil
shutil.copy(CSV, str(CSV)+".bak_antes_restaura")
with open(CSV,"w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    w.writerows(out)
print(f"Escrito {CSV}. Backup en {CSV}.bak_antes_restaura")
