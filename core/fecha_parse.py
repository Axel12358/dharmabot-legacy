import re
from unicodedata import normalize

MES = {
    'es': {'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,'julio':7,
            'agosto':8,'septiembre':9,'setiembre':9,'octubre':10,'noviembre':11,'diciembre':12},
    'en': {'january':1,'february':2,'march':3,'april':4,'may':5,'june':6,'july':7,
            'august':8,'september':9,'october':10,'november':11,'december':12},
    'pt': {'janeiro':1,'fevereiro':2,'março':3,'marco':3,'abril':4,'maio':5,'junho':6,
            'julho':7,'agosto':8,'setembro':9,'outubro':10,'novembro':11,'dezembro':12},
    'de': {'januar':1,'februar':2,'märz':3,'marz':3,'april':4,'mai':5,'juni':6,'juli':7,
            'august':8,'september':9,'oktober':10,'november':11,'dezember':12},
    'fr': {'janvier':1,'février':2,'fevrier':2,'mars':3,'avril':4,'mai':5,'juin':6,
            'juillet':7,'août':8,'aout':8,'septembre':9,'octobre':10,'novembre':11,'décembre':12,'decembre':12},
    'it': {'gennaio':1,'febbraio':2,'marzo':3,'aprile':4,'maggio':5,'giugno':6,
            'luglio':7,'agosto':8,'settembre':9,'ottobre':10,'novembre':11,'dicembre':12},
    'pl': {'stycznia':1,'lutego':2,'marca':3,'kwietnia':4,'maja':5,'czerwca':6,
            'lipca':7,'sierpnia':8,'września':9,'września':9,'października':10,'listopada':11,'grudnia':12},
    'nl': {'januari':1,'februari':2,'maart':3,'april':4,'mei':5,'juni':6,'juli':7,
            'augustus':8,'september':9,'oktober':10,'november':11,'december':12},
}

_MESES = {}
for _mp in MES.values():
    for _m, _n in _mp.items():
        _MESES[normalize('NFKD', _m).encode('ascii','ignore').decode().lower()] = _n
for _extra, _n in [('sept',9),('sep',9),('dic',12),('ene',1),('mar',3)]:
    _MESES[_extra]=_n

_num_c = r'([0-9]{1,2}(?:st|nd|rd|th)?)'

def _muni(s):
    return normalize('NFKD', s).encode('ascii','ignore').decode().lower()

def _limpiar_num(x):
    return int(re.sub(r'\D', '', x))

def parse_fecha(desc, fallback_year=None):
    if not desc:
        return None
    s = desc.strip()
    m = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f'{y:04d}-{mo:02d}-{d:02d}'
    m = re.search(r'\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b', s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        for d, mo in ((a, b), (b, a)):
            if 1 <= mo <= 12 and 1 <= d <= 31:
                return f'{y:04d}-{mo:02d}-{d:02d}'
    tl = _muni(s)
    mn = '|'.join(sorted(_MESES, key=len, reverse=True))
    m = re.search(rf"({mn})\s+{_num_c}\s*,?\s*(\d{{4}})", tl)
    if m:
        mo, d, y = _MESES[m.group(1)], _limpiar_num(m.group(2)), int(m.group(3))
        if 1 <= d <= 31:
            return f'{y:04d}-{mo:02d}-{d:02d}'
    m = re.search(rf"{_num_c}\s+(?:de\s+|del\s+)?({mn})\s+(?:de\s+)?\s*,?\s*(\d{{4}})", tl)
    if m:
        d, mo, y = _limpiar_num(m.group(1)), _MESES[m.group(2)], int(m.group(3))
        if 1 <= d <= 31:
            return f'{y:04d}-{mo:02d}-{d:02d}'
    if fallback_year:
        m = re.search(rf"\b{_num_c}\s+(?:de\s+)?({mn})\s*[,.$]?\s*$", tl)
        if m:
            d, mo = _limpiar_num(m.group(1)), _MESES[m.group(2)]
            if 1 <= d <= 31 and 2025 <= int(fallback_year) <= 2028:
                return f'{int(fallback_year):04d}-{mo:02d}-{d:02d}'
    return None