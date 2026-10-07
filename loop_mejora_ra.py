#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Loop de mejora continua para el CSV de eventos.

Ejecuta periódicamente:
  1. RA Promoter Dorks (búsqueda de contactos)
  2. Integración de contactos al CSV
  3. Estadísticas de progreso

Corre como background process. Checkpoint para reanudar.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent)
_CSV_FILE = Path(_PROJECT_ROOT) / "eventos_encontrados.csv"
_STATE_FILE = Path(_PROJECT_ROOT) / "loop_mejora_state.json"
_LOG_FILE = Path(_PROJECT_ROOT) / "loop_mejora.log"

# Config
ITERATION_PAUSE = 600  # 10 minutes between iterations
MAX_ITERATIONS = 50    # Max iterations before stopping
DORKS_LIMITE = 20      # Promoters per iteration


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_state() -> dict:
    if _STATE_FILE.exists():
        try:
            with open(_STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {"iteration": 0, "total_emails_found": 0, "last_run": None}


def save_state(state: dict) -> None:
    try:
        with open(_STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def get_csv_stats() -> dict:
    """Obtiene estadísticas del CSV."""
    try:
        import csv
        with open(_CSV_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        total = len(rows)
        with_email = sum(1 for r in rows if r.get('email', '').strip())
        with_org = sum(1 for r in rows if r.get('organizador', '').strip() and r.get('organizador', '') != 'N/A')
        ra_events = sum(1 for r in rows if 'Resident Advisor' in r.get('fuente', ''))
        ra_with_email = sum(1 for r in rows if 'Resident Advisor' in r.get('fuente', '') and r.get('email', '').strip())
        
        return {
            "total": total,
            "with_email": with_email,
            "email_pct": with_email * 100 / total if total else 0,
            "with_org": with_org,
            "org_pct": with_org * 100 / total if total else 0,
            "ra_events": ra_events,
            "ra_with_email": ra_with_email,
        }
    except Exception as e:
        return {"error": str(e)}


def run_dorks(limite: int) -> int:
    """Ejecuta RA Promoter Dorks y devuelve emails encontrados."""
    log(f"Ejecutando RA Promoter Dorks (limite={limite})...")
    
    try:
        result = subprocess.run(
            [sys.executable, "scrapers/ra_promoter_dorks.py", "--limite", str(limite)],
            cwd=_PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=600,  # 10 min timeout
        )
        
        # Parse output
        output = result.stdout + result.stderr
        emails_found = 0
        for line in output.split('\n'):
            if 'con email' in line:
                # "3 contactos, 1 con email"
                parts = line.split(',')
                for p in parts:
                    p = p.strip()
                    if 'con email' in p:
                        try:
                            emails_found = int(p.split()[0])
                        except Exception:
                            pass
        
        log(f"Dorks completado: {emails_found} emails encontrados")
        return emails_found
    
    except subprocess.TimeoutExpired:
        log("Dorks timeout (600s)")
        return 0
    except Exception as e:
        log(f"Error en dorks: {e}")
        return 0


def run_integrate() -> int:
    """Ejecuta integración de contactos al CSV."""
    log("Integrando contactos al CSV...")
    
    try:
        result = subprocess.run(
            [sys.executable, "integrar_contactos_ra.py"],
            cwd=_PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        
        output = result.stdout
        updated = 0
        for line in output.split('\n'):
            if 'actualizado' in line:
                # "CSV actualizado: 1 eventos con email nuevo"
                try:
                    updated = int(line.split(':')[1].split()[0])
                except Exception:
                    pass
        
        log(f"Integración completada: {updated} eventos actualizados")
        return updated
    
    except Exception as e:
        log(f"Error en integración: {e}")
        return 0


def iteration(state: dict) -> dict:
    """Ejecuta una iteración del loop de mejora."""
    state["iteration"] += 1
    log(f"=== Iteración {state['iteration']}/{MAX_ITERATIONS} ===")
    
    # Get initial stats
    stats_before = get_csv_stats()
    log(f"CSV antes: {stats_before.get('total', 0)} eventos, "
        f"{stats_before.get('with_email', 0)} con email ({stats_before.get('email_pct', 0):.1f}%), "
        f"{stats_before.get('ra_events', 0)} RA events, "
        f"{stats_before.get('ra_with_email', 0)} RA con email")
    
    # Run dorks
    emails_found = run_dorks(DORKS_LIMITE)
    state["total_emails_found"] += emails_found
    
    # Integrate
    updated = run_integrate()
    
    # Get final stats
    stats_after = get_csv_stats()
    log(f"CSV después: {stats_after.get('total', 0)} eventos, "
        f"{stats_after.get('with_email', 0)} con email ({stats_after.get('email_pct', 0):.1f}%), "
        f"{stats_after.get('ra_events', 0)} RA events, "
        f"{stats_after.get('ra_with_email', 0)} RA con email")
    
    state["last_run"] = datetime.now().isoformat()
    state["last_stats"] = stats_after
    
    return state


def main():
    log("=== Loop de mejora RA iniciado ===")
    
    state = load_state()
    log(f"Estado: iteración {state['iteration']}, "
        f"{state['total_emails_found']} emails encontrados previamente")
    
    while state["iteration"] < MAX_ITERATIONS:
        try:
            state = iteration(state)
            save_state(state)
            
            if state["iteration"] < MAX_ITERATIONS:
                log(f"Pausando {ITERATION_PAUSE}s antes de siguiente iteración...")
                time.sleep(ITERATION_PAUSE)
        
        except KeyboardInterrupt:
            log("Interrumpido por usuario")
            break
        except Exception as e:
            log(f"Error en iteración: {e}")
            time.sleep(60)  # Wait 1 min on error
    
    log(f"=== Loop completado: {state['iteration']} iteraciones, "
        f"{state['total_emails_found']} emails encontrados ===")


if __name__ == "__main__":
    main()
