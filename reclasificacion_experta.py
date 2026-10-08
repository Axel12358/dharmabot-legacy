"""Reclasificación experta de los pools de eventos 'eliminados' del pipeline.

Nunca borra: cada fila se ubica en el CSV correcto:
  - eventos_encontrados.csv  : psy real, en rango 2025-2028
  - non_psy.csv              : evento/ruido NO psy (fiesta house, meetup, etc.)
  - eventos_deadstock_2021_2024.csv / eventos_historicos_pre2021.csv : psy fuera de rango
El juicio es experto (marcas de NO-psy inconfundibles + overrides explícitos
por link para los casos que el clasificador etiquetó mal).

Uso:  python reclasificacion_experta.py   (imprime plan y lo aplica con lock)
"""
import csv
import re
from core.csv_lock import csv_locked_rows

CSV_MAIN = 'eventos_encontrados.csv'
CSV_NONPSY = 'non_psy.csv'
CSV_DEAD = 'eventos_deadstock_2021_2024.csv'
CSV_HIST = 'eventos_historicos_pre2021.csv'

# --- Señales de NO-psy (nombre): un match -> NON_PSY, con excepciones
NOPSY_PAT = re.compile(
    r'\b(meetup|workshop|retreat|yoga|acupuncture|biathlon|fish festival|fish & '
    r'shrimp|fish festival|tango|karaoke|balboa|swing|seminar|conference|congress|'
    r'state of trance|metal night|boxing|kickbox|kpop|beer festival|cider|sausage|'
    r'comic|marvel|convention|banquet|fundraiser|networking|board|pool party|'
    r'integration group|travel meetup|travel class|buddhist|eckankar|shire|harvest '
    r'fest|gul\w*fest|guláš|goulash|live du maire|hobbit|skinner brothers|druidess|'
    r'chef|clinic|kinder|open house|ribbon cutting|city festival|camino|solo-but|'
    r'tour:|psychedelic (society|salon|integration|recovery)|bold women|50\+|'
    r'sushi|kinky|gongbad|healing &|pharmacy|palestine|boiler room|dreamstate|'
    r'book launch|hitchhiker|birthday|hard techno|elrow|anjunabeats|ministry of '
    r'sound|fsoe|boat party|metal fest|\bbjj\b|stafetten|markt|market|christmas|'
    r'ratha yatra|alafia|3ballmty|weekender|mid-autumn|wearable art|language '
    r'exchange|progressive house|our house|orchestra|hippie|food festival|bnoccr|'
    r'tantric|polyamory|glitter|sugar rush|\bexpo\b|\bsnack|burns night|naughty '
    r'night|punsch|elektro welle|forest school|\btour \b|\btour\b shuttle|'
    r'0fa does|soul weekender|tribe of us|\blevel 3\b)\b|'
    r'\u53c2\u62dc|\u795e\u793e|\bmagic: the gathering\b|\bsolstice\b',
    re.I,
)

# Overrides explícitos por fragmento de link (ganan sobre las señales).
# (frag_link, subgenero_deseado) -> destino
OVERRIDES = {
    # psy reales en non_psy (restaurar)
    'mo%C5%99e-u-rybn%C3': 'MAIN',          # Equinox Summer Psytrance Closing Open Air
    'studiestr%C3%A6de-': 'MAIN',           # The Gathering x Hemeroscopium x Paradansu
    't.me/s/afishagoa': 'MAIN',             # Aфиша Гоа: calendario de parties
    't.me/s/phanganparty': 'MAIN',          # party calendar Phangan
    'amfite%C3%A1tr-na-hore': 'MAIN',       # Festival Paseka (recuperado antes)
    # psy viejo rescatado del bucket non_psy -> histórico
    'loop-bar/unstable': 'HIST',            # 2015 Zenon Records Label Party
    # no-psy que el clasificador etiquetó como psy
    'sushi-festival': 'NONPSY',
    'place-guillaume-le': 'NONPSY',         # Live du maire
    'studio-yoga-arenas': 'NONPSY',
    'roskilde-universit': 'NONPSY',
    'el-patio/neverdogs': 'NONPSY',
    'freud-club/when-in': 'NONPSY',
    'rua-do-centro-cult': 'NONPSY',
    'na%C4%84da/rave-1': 'NONPSY',
    'universitet-ignatianum': 'NONPSY',     # psicología
    'electric-ballroom/': 'NONPSY',
    'the-star-and-garter': 'NONPSY',
    'food-festival': 'NONPSY',
    # viejo psy -> rango correspondiente
    'walnut-park-petalu': 'HIST',           # 2016 prog festival
    '1208692620031212': 'DEAD',             # PSYMSARA 2023
    '833299766705053': 'HIST',              # Psy Secret Minds 2015
}


# Exclusión experta de nombres: ruido inequívoco aunque el tag sea psy
EXCL_NOPSY = (
    'meetup.com', 'naidoc', 'movie night', 'amsterdam techno', 'languages music',
    'space odyssey', 'hack the music', 'phantom group', 'progressive friday',
    'paal69', 'last days of summer', 'kadinsky', 'ninsa b2b', 'carina lawrence',
    'tausend house', 'sumpfkr', 'lescat', 'thompson u', 'amsterdam open air',
    'rhs glow', 'pop & psy', 'chart 2025', 'copenhagen open and camp',
    'copenhagen open 2025', 'rwfl', 'limitowane', 'öppet hus', 'ibiza trance event',
    'costa festival', 'velvet ibiza', 'food & culture indonesian', 'hrmny',
    'sunset pool', '8-hour boat', 'hard techno rave', 'ban sabai', 'we roof',
    'zuger port', 'label night', 'byoga', 'jolly b2b',
)


def _destino(r, sobreescribe=None):
    """Devuelve el CSV destino de una fila. sobreescribe: dict link->destino ya
    resuelto por un paso previo (para no re-resolver)."""
    if sobreescribe and r.get('link'):
        d = sobreescribe.get(r.get('link'), '')
        if d:
            return d
    nombre = r.get('nombre') or ''
    l = ((r.get('link') or '') + nombre).lower()
    # sin link -> basura/test -> archivo histórico (no se pierde)
    if not (r.get('link') or '').strip():
        return 'HIST'
    # ruido inequívoco por nombre/dominio (juicio experto)
    if any(e in l for e in EXCL_NOPSY):
        return 'NONPSY'
    for frag, d in OVERRIDES.items():
        if frag in l:
            return d
    y = (r.get('fecha') or '').strip()[:4]
    años = re.findall(r'20(2[5-9])', nombre)
    if not (y.isdigit() and len(y) == 4):
        y = ('20' + años[0]) if años else y
    en_rango = y.isdigit() and y >= '2025' and y <= '2028'
    # canales/portales psy de confianza: su calendario es psy por definición
    if any(t in l for t in ('t.me/s/afishagoa', 't.me/s/phanganparty',
                            'goabase.net', 'reddit.com/r/psytrance')):
        return 'MAIN' if en_rango else ('HIST' if (y.isdigit() and y < '2021') else 'DEAD')
    # 1) ¿parece NO-psy?
    if NOPSY_PAT.search(nombre):
        return 'NONPSY'
    sub = (r.get('subgenero') or '').strip().lower()
    # 2) ¿subgénero no-psy explícito?
    if sub == 'no_psy':
        return 'NONPSY'
    # 3) psy real: por rango
    if en_rango:
        return 'MAIN'
    if y.isdigit():
        return 'HIST' if y < '2021' else 'DEAD'
    return 'HIST'  # sin año: a histórico (no se pierde, queda archivado)


def cargar(p, key='link'):
    try:
        with open(p, encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        return [], set()
    return rows, {(r.get(key) or '').strip() for r in rows if r.get(key)}


def main():
    # leer hogares actuales
    main_rows, main_links = cargar(CSV_MAIN)
    _, npsy_links = cargar(CSV_NONPSY)
    _, dead_links = cargar(CSV_DEAD)
    _, hist_links = cargar(CSV_HIST)
    all_links = main_links | npsy_links | dead_links | hist_links

    # filas de los pools a reclasificar
    pools = []
    import os
    for p in ['backup_20260918_132600_contaminado.csv',
              'eventos_encontrados.csv.bak_no_psy_1787802410']:
        if os.path.exists(p):
            rows, _ = cargar(p)
            pools.append((p, rows))
            print(f'pool {p}: {len(rows)} filas\n')
    # cola de filas (todas las filas de todos los pools, sin repetir link)
    por_link = {}
    for p, rows in pools:
        for r in rows:
            l = r.get('link', '').strip()
            if l and l not in por_link:
                por_link[l] = r
            elif not l:
                por_link.setdefault(('__nok__', p), r)
    print(f'filas únicas por link a revisar: {len(por_link)}\n')

    # resolver destino de cada una
    plan = {'MAIN': [], 'NONPSY': [], 'DEAD': [], 'HIST': []}
    for k, r in por_link.items():
        l = (r.get('link') or '').strip()
        if l and l in all_links:
            continue  # ya tiene hogar
        d = _destino(r)
        plan[d].append(r)

    for d, rows in plan.items():
        print(f'  {d:6} -> {len(rows)}  {(" " + ", ".join(r["nombre"][:34] for r in rows[:3])) if rows else ""}...')
    print()

    if not input('¿Aplicar? (s/N): ').strip().lower() == 's':
        print('cancelado')
        return

    # MAIN no toca intro manualmente: re-abre bajo lock y usa csv_locked_rows
    for destino in ('MAIN', 'NONPSY', 'DEAD', 'HIST'):
        rows = plan[destino]
        if not rows:
            continue
        path = {'MAIN': CSV_MAIN, 'NONPSY': CSV_NONPSY,
                'DEAD': CSV_DEAD, 'HIST': CSV_HIST}[destino]
        with csv_locked_rows(path, timeout=300) as (all_rows, _):
            final = {(r.get('link') or '').strip() for r in all_rows}
            agreg = [r for r in rows if not (r.get('link') or '').strip() or (r.get('link') or '').strip() not in final]
            all_rows.extend(agreg)
            print(f'{destino:6}: +{len(agreg)} filas (ya había {len(rows) - len(agreg)})')


if __name__ == '__main__':
    main()