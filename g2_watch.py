"""Wrapper: relanza extraer_host_g2.py mientras G1 acumula snippets nuevos."""
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path("/Users/angelgarcia/dharmabot")
PY = str(_ROOT) + ("/.venv/bin/python")
SCRIPT = str(_ROOT / "extraer_host_g2.py")
CHECK = _ROOT / "organizador_candidates.json"

ult = None
if CHECK.exists():
    ult = (CHECK.stat().st_mtime, str((_ROOT / "grupos_g2_checkpoint.json").stat().st_mtime
           if (_ROOT / "grupos_g2_checkpoint.json").exists() else 0))
ciclos_vacio = 0

while True:
    try:
        r = subprocess.run([PY, SCRIPT], cwd=str(_ROOT),
                           capture_output=True, timeout=130)
        out = (r.stdout or b"").decode(errors="ignore")
        for line in out.strip().splitlines():
            print(line, flush=True)
        # si no hay pendientes y pasa tiempo sin cambios, salir (el launcher decide)
        if "0 pendientes" in out or "TODO procesado" in out:
            ciclos_vacio += 1
        else:
            ciclos_vacio = 0
        if ciclos_vacio >= 10:
            print("G2: varios ciclos vacíos. Fin.", flush=True)
            break
        time.sleep(20)
    except subprocess.TimeoutExpired:
        print("G2: timeout de proceso (Tore).", flush=True)
        try:
            import signal, os
            os.killpg(os.getpgid(r.pid), signal.SIGKILL)
        except Exception:
            pass
        time.sleep(5)

sys.exit(0)