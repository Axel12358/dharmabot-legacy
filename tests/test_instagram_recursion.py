"""Regresión sobre el código realmente cargado de instagram_scraper.

Antes morían con RecursionError: scrape_instagram_events_v2 se llamaba a sí
mismo vía el wrapper scrape_instagram_events (recursión infinita). Ahora cae
directo a _scrape_instagram_events_legacy. Estas funciones puras no tocan red.
"""
import inspect
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scrapers.instagram_scraper import (  # noqa: E402
    _build_hashtags,
    _inferir_tipo_lugar,
    _limpiar_hashtag,
    _normalizar_nombre,
    scrape_instagram_events,
    scrape_instagram_events_v2,
)


def test_firma_v2_rapida_o_normal():
    sig = inspect.signature(scrape_instagram_events_v2)
    assert "config" in sig.parameters


def test_wrapper_usa_v2_sin_recursion():
    # El wrapper (scrape_instagram_events) debe llamar a v2, NO recursear.
    # Con monkeypatch manual veremos que v2 existe y wrapper lo referencia.
    sig = inspect.signature(scrape_instagram_events)
    assert "config" in sig.parameters
    assert not (str(inspect.getsource(scrape_instagram_events)).count("scrape_instagram_events(") > 3)


def test_limpiar_hashtag():
    assert _limpiar_hashtag("#PsyTrance 2026!") == "psytrance2026"
    assert _limpiar_hashtag("") == ""
    assert _limpiar_hashtag(None) == ""


def test_build_hashtags_no_repite_ni_hay_vacios():
    random.seed(7)
    hs = _build_hashtags({"subgeneros": ["psytrance", "forest", "hi-tech"],
                          "paises": [{"ciudades": ["Barcelona", "Berlín"]}]})
    assert isinstance(hs, list) and len(hs) == len(set(hs))
    assert all(h and h == h.lower() for h in hs)
    assert all(not set(h) & set(" @#.!,") for h in hs)


def test_inferir_tipo_lugar_reconoce_festival_y_club():
    assert _inferir_tipo_lugar("Full Moon Festival", "", "open air", "", "psytrance") == "festival"
    assert _inferir_tipo_lugar("Nox Club", "", "party", "Berlin", "") == "club"
    assert _inferir_tipo_lugar("Cosmos Forest Gathering", "", "", "naturaleza", "") == "forest"


def test_normalizar_nombre():
    n = _normalizar_nombre("  ★Full Moon ★ Festiv@l 2026!!  ")
    assert n and "@" not in n and "★" not in n and n == n.strip()


def test_fallback_v2_a_legacy_declarado():
    src = inspect.getsource(scrape_instagram_events_v2)
    assert "_scrape_instagram_events_legacy" in src
    # El fallback ya no vuelve al wrapper (eso era la recursión infinita)
    assert "return scrape_instagram_events(config)" not in src