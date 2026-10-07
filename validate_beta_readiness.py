import csv
import sys

def na(v): return (v or '').strip().lower() in ('','n/a','na')


def validate_beta(csv_path):
    rows = list(csv.DictReader(open(csv_path, encoding='utf-8')))
    total = len(rows)
    
    checks = {}
    
    # 1. total_events
    checks["total_events"] = (total >= 2200, f"✓ {total} events (meta: 2200+)")
    
    # 2. email_coverage
    email_na = sum(1 for r in rows if na(r.get('email','')))
    email_pct = ((total - email_na) / total * 100) if total > 0 else 0
    checks["email_coverage"] = (email_pct >= 90, f"✓ {email_pct:.1f}% emails (meta: 90%+)")
    
    # 3. organizer_coverage
    org_na = sum(1 for r in rows if na(r.get('organizador','')))
    org_pct = ((total - org_na) / total * 100) if total > 0 else 0
    checks["organizer_coverage"] = (org_pct >= 85, f"✓ {org_pct:.1f}% organizers (meta: 85%+)")
    
    # 4. subgenre_psytrance
    psytrance = sum(1 for r in rows if r.get('subgenero','').strip().lower() == 'psytrance')
    psy_pct = (psytrance / total * 100) if total > 0 else 0
    checks["subgenre_psytrance"] = (psy_pct >= 60, f"✓ {psy_pct:.1f}% psytrance (meta: 60%+)")
    
    # 5. country_normalized
    pais_na = sum(1 for r in rows if na(r.get('pais','')))
    pais_pct = ((total - pais_na) / total * 100) if total > 0 else 0
    checks["country_normalized"] = (pais_pct >= 95, f"✓ {pais_pct:.1f}% countries (meta: 95%+)")
    
    # 6. continent_complete
    cont_na = sum(1 for r in rows if na(r.get('continente','')))
    cont_pct = ((total - cont_na) / total * 100) if total > 0 else 0
    checks["continent_complete"] = (cont_pct >= 98, f"✓ {cont_pct:.1f}% continents (meta: 98%+)")
    
    # 7. date_coverage
    fecha_na = sum(1 for r in rows if na(r.get('fecha','')))
    fecha_pct = ((total - fecha_na) / total * 100) if total > 0 else 0
    checks["date_coverage"] = (fecha_pct >= 80, f"✓ {fecha_pct:.1f}% dates (meta: 80%+)")
    
    # 8. dedup_integrity
    dedup_rows = len(set((r.get('nombre',''), r.get('fecha',''), r.get('lugar','')) for r in rows))
    checks["dedup_integrity"] = (dedup_rows == total, f"✓ No duplicates (total:{total}, dedup:{dedup_rows})")
    
    # 9. geo_diversity
    pais_unicos = len(set(r.get('pais','').strip() for r in rows if r.get('pais')))
    checks["geo_diversity"] = (pais_unicos >= 50, f"✓ {pais_unicos} unique countries (meta: 50+)")
    
    # 10. organizer_diversity
    org_unicos = len(set(r.get('organizador','').strip() for r in rows if r.get('organizador')))
    checks["organizer_diversity"] = (org_unicos >= 200, f"✓ {org_unicos} unique organizers (meta: 200+)")
    
    passed = sum(1 for ok, _ in checks.values() if ok)
    total_c = len(checks)
    
    print(f"\n{'='*60}")
    print(f"BETA READINESS VALIDATION: {passed}/{total_c} checks passed")
    print(f"{'='*60}\n")
    
    for criterion, (ok, msg) in checks.items():
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"{status} — {msg}")
    
    print(f"\n{'='*60}")
    if passed == total_c:
        print("🎉 BOT IS BETA-READY!")
        return True
    else:
        print(f"⚠️  {total_c - passed} checks failed. See above.")
        return False
    
    print("\n" + "="*60)
    print("QUALITY METRICS")
    print("="*60)
    print(f"Subgenre distribution:")
    # print(rows['subgenero'].value_counts().head(10))  # skip for speed
    print(f"\nTop countries: {len(set(r.get('pais','').strip() for r in rows if r.get('pais')))} unique")
    print(f"\nTop organizers: {len(set(r.get('organizador','').strip() for r in rows if r.get('organizador')))} unique")
    print(f"\nDate range: need to check")
    
    return False


if __name__ == '__main__':
    csv_path = sys.argv[1] if len(sys.argv) > 1 else 'eventos_encontrados.csv'
    validate_beta(csv_path)