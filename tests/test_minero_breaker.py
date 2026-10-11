"""Regresión del circuit-breaker del minero (defense-in-depth).

Causa raíz que cubre: en la pasada 5, con el SERP muerto (DDG + SearXNG
caídos), `minar_org` devolvía '' en silencio y el lote masticaba ~929 ceros.
El breaker debe abortar el lote tras N llamadas consecutivas sin status 200.

Estas funciones NO tocan red (se registran status a mano). Runnable con pytest
o directo: python3 tests/test_minero_breaker.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from minero_top_orgs import SerpBreaker  # noqa: E402


def test_no_aborta_con_pocos_fallos():
    b = SerpBreaker()
    for _ in range(b.LIMITE - 1):
        b.registrar(0, 'sin-red')
    assert not b.abortado


def test_exito_resetea_la_racha():
    b = SerpBreaker()
    for _ in range(b.LIMITE - 1):
        b.registrar(0, 'sin-red')
    b.registrar(200)
    assert b.fallos == 0
    for _ in range(b.LIMITE - 1):
        b.registrar(0, 'sin-red')
    assert not b.abortado


def test_aborta_a_limite_fallos_consecutivos():
    b = SerpBreaker()
    for _ in range(b.LIMITE):
        b.registrar(0, 'no-results')
    assert b.abortado
    assert 'SERP caído' in b.motivo


def test_aborto_es_idempotente_no_revive():
    b = SerpBreaker()
    for _ in range(b.LIMITE):
        b.registrar(0, 'x')
    assert b.abortado
    b.registrar(200)
    assert b.abortado


def test_minar_org_corta_sin_red_si_abortado():
    import minero_top_orgs as m
    m.minar_breaker = m.SerpBreaker()
    m.minar_breaker.abortado = True
    assert m.minar_org('org de prueba') == ''


if __name__ == '__main__':
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    fallos = 0
    for fn in pruebas:
        try:
            fn()
            print(f'  OK  {fn.__name__}')
        except AssertionError as e:
            fallos += 1
            print(f'  FALLO {fn.__name__}: {e}')
    print(f'\n{len(pruebas)-fallos}/{len(pruebas)} pruebas OK')
    sys.exit(1 if fallos else 0)
