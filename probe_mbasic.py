"""Probe: mide hit-rate de acceso directo (mbasic/noscript) a grupos FB vía Tor."""
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path("/Users/angelgarcia/dharmabot")
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

VENV_PY = str(_ROOT / ".venv/bin/python")
WORKER = str(_ROOT / "mbasic_worker.py")
HARD_TIMEOUT = 60


def rotar():
    try:
        from core.tor_manager import renovar_identidad_tor
        renovar_identidad_tor()
    except Exception as e:
        print("rot fail:", e)


def fetch(gid):
    try:
        proc = subprocess.Popen([VENV_PY, WORKER, gid], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, cwd=str(_ROOT))
        try:
            out, _ = proc.communicate(timeout=HARD_TIMEOUT)
            return json.loads(out.decode())
        except subprocess.TimeoutExpired:
            try:
                import os
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                proc.kill()
            return {"gid": gid, "status": "HARD_TIMEOUT"}
    except Exception as e:
        return {"gid": gid, "status": "error", "err": str(e)[:80]}


if __name__ == "__main__":
    grupos = json.load(open(_ROOT / "grupos_encontrados.json"))
    gs = grupos if isinstance(grupos, list) else grupos.get("groups", [])
    # Priorizar grupos numéricos (más vieja que mbasic da posts) y con nombre psy
    num = [g for g in gs if g.get("id", "").isdigit()]
    texto = [g for g in gs if not g.get("id", "").isdigit()]
    sel = (num + texto)[:12]
    stats = {"ok": 0, "login": 0, "fail": 0, "timeout": 0}
    for g in sel:
        rotar()
        r = fetch(g["id"])
        st = r.get("status")
        stats[st if st in stats else "fail"] = stats.get(st if st in stats else "fail", 0) + 1
        extra = f"title={r.get('title','')[:30]} posts={r.get('posts')} len={r.get('len')}" if st == "ok" else ""
        print(f"{g['id']:<20} {st:<12} {g['nombre'][:35]:<35} {extra}")
        time.sleep(2)
    print("\nSTATS:", stats, "| hit_rate_ok:", round(100*stats["ok"]/len(sel), 1))
    json.dump(sel, open(_ROOT / "grupos_probe.json", "w"), ensure_ascii=False, indent=2)