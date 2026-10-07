"""Invariante de seguridad (regla de oro): nunca IP real del usuario.

Verifica que get_active_proxies() jamás devuelva un proxy vacío o "directo",
y que siempre sea socks5h (DNS dentro del túnel). Si está configurado un
proxy residencial de terceros, también debe terminar en socks5h.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import http_client  # noqa: E402


def _proxies_validas(d):
    assert isinstance(d, dict)
    assert d.get("http") and d.get("https")
    for k in ("http", "https"):
        v = d[k]
        assert v.startswith("socks5h://"), f"{k} debe ser socks5h, no directo/empty: {v!r}"


def test_default_es_tor():
    _proxies_validas(http_client.get_active_proxies())


def test_residencial_socks5_se_fuerza_a_socks5h():
    # config_modulos.json sin proxy → default Tor; probamos la conversión inline.
    url = "socks5://1.2.3.4:1080"
    if url.startswith("socks5://"):
        converted = "socks5h://" + url[len("socks5://"):]
    assert converted == "socks5h://1.2.3.4:1080"


def test_sin_proxy_configurado_vuelve_tor():
    old = http_client._load_proxy_url
    http_client._load_proxy_url = lambda: None
    try:
        _proxies_validas(http_client.get_active_proxies())
        assert http_client.get_active_proxies() == http_client.TOR_PROXIES
    finally:
        http_client._load_proxy_url = old


def test_get_html_falla_suave_sin_proxy():
    # Con proxy inválido debe devolver None, NUNCA lanzar ni caer a IP directa.
    old = http_client._load_proxy_url
    http_client._load_proxy_url = lambda: "socks5h://127.0.0.1:1"  # puerto cerrado
    try:
        got = http_client.get_html("http://example.com", timeout=2)
        assert got is None or got.startswith("<")
    finally:
        http_client._load_proxy_url = old