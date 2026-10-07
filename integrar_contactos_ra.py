#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integra contactos de ra_promoter_contacts.json al CSV eventos_encontrados.csv.
Matchea por nombre del organizador (fuzzy) o por URL de RA.
"""
import csv
import json
import os
import re
import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent)
_CSV_FILE = Path(_PROJECT_ROOT) / "eventos_encontrados.csv"
_CONTACTS_FILE = Path(_PROJECT_ROOT) / "ra_promoter_contacts.json"
_BACKUP_FILE = Path(_PROJECT_ROOT) / "eventos_encontrados.csv.bak_ra_integrate"


def normalize_name(name: str) -> str:
    """Normaliza un nombre para comparación."""
    name = name.lower().strip()
    name = re.sub(r'[^\w\s]', '', name)
    name = re.sub(r'\s+', ' ', name)
    return name


def load_contacts() -> dict:
    """Carga contactos y crea índices por nombre y por URL."""
    if not _CONTACTS_FILE.exists():
        return {}, {}
    
    with open(_CONTACTS_FILE, 'r', encoding='utf-8') as f:
        contacts = json.load(f)
    
    by_name = {}
    by_url = {}
    
    for c in contacts:
        nombre = c.get('nombre', '')
        email = c.get('email', '')
        fuente_ra = c.get('fuente_ra', '')
        
        if not email:
            continue
        
        # Index by normalized name
        norm = normalize_name(nombre)
        if norm and len(norm) >= 3:
            by_name[norm] = email
        
        # Index by RA URL (extract promoter/DJ ID)
        if 'ra.co/' in fuente_ra:
            m = re.search(r'ra\.co/(?:promoters?|dj|labels?)/(\d+)', fuente_ra)
            if m:
                by_url[m.group(1)] = email
            # Also match by slug
            m2 = re.search(r'ra\.co/(?:promoters?|dj|labels?)/([a-z0-9-]+)', fuente_ra)
            if m2:
                by_url[m2.group(1)] = email
    
    return by_name, by_url


def extract_ra_id(link: str) -> str:
    """Extrae el ID de RA de un link de evento."""
    if not link:
        return ''
    m = re.search(r'ra\.co/events/(\d+)', link)
    return m.group(1) if m else ''


def extract_organizer_from_link(link: str) -> str:
    """Intenta extraer el slug del organizador del link."""
    if not link:
        return ''
    # ra.co/events/12345 → no organizer info
    # But we can try to match by venue name in the event
    return ''


def integrate():
    """Integra contactos al CSV."""
    if not _CSV_FILE.exists():
        print("CSV no encontrado")
        return
    
    by_name, by_url = load_contacts()
    print(f"Contactos cargados: {len(by_name)} por nombre, {len(by_url)} por URL")
    
    # Backup
    import shutil
    shutil.copy2(_CSV_FILE, _BACKUP_FILE)
    print(f"Backup creado: {_BACKUP_FILE}")
    
    # Read CSV
    rows = []
    updated = 0
    with open(_CSV_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        
        for row in reader:
            # Skip if already has email
            if row.get('email', '').strip():
                rows.append(row)
                continue
            
            # Only process RA events
            fuente = row.get('fuente', '')
            if 'Resident Advisor' not in fuente:
                rows.append(row)
                continue
            
            # Try matching by organizer name
            org = row.get('organizador', '')
            norm_org = normalize_name(org)
            
            # Also try matching by event name (lineup often mentions artists/DJs)
            nombre = row.get('nombre', '')
            norm_nombre = normalize_name(nombre)
            
            email = ''
            
            # 1. Match by exact organizer name
            if norm_org in by_name:
                email = by_name[norm_org]
            
            # 2. Match by partial name (organizer contains contact name or vice versa)
            if not email:
                for norm_name, e in by_name.items():
                    if len(norm_name) >= 5 and len(norm_org) >= 5:
                        if norm_name in norm_org or norm_org in norm_name:
                            email = e
                            break
            
            # 3. Match by event name (check if promoter/DJ name appears in event title)
            if not email:
                for norm_name, e in by_name.items():
                    if len(norm_name) >= 4 and norm_name in norm_nombre:
                        email = e
                        break
            
            if email:
                row['email'] = email
                updated += 1
            
            rows.append(row)
    
    # Write back
    with open(_CSV_FILE, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    print(f"CSV actualizado: {updated} eventos con email nuevo")
    print(f"Total eventos: {len(rows)}")
    
    # Stats
    with_email = sum(1 for r in rows if r.get('email', '').strip())
    print(f"Con email: {with_email} ({with_email*100/len(rows):.1f}%)")


if __name__ == "__main__":
    integrate()
