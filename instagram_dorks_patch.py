# ─────────────────────────────────────────────────────────────────────────────
# FIX: _buscar_google_con_reintentos_ig como función de NIVEL MÓDULO
# (antes estaba anidada dentro de _parse_google_results_ig — des-indentada aquí)
# ─────────────────────────────────────────────────────────────────────────────

def _buscar_google_con_reintentos_ig(dork: str, max_reintentos: int = 2) -> list:
    """Busca en Google vía Playwright stealth (si disponible).

    Retorna lista de resultados crudos [{titulo,url,snippet,motor}] o [].
    """
    if not STEALTH_AVAILABLE:
        return []
    for intento in range(max_reintentos):
        try:
            html = _google_search_playwright_ig(dork)
            if html:
                return _parse_google_results_ig(html)
        except Exception as e:
            print(f"  ⚠️  Google IG intento {intento+1}/{max_reintentos} falló: {e}")
        _random_sleep()
    return []


# ─────────────────────────────────────────────────────────────────────────────
# FUNCIÓN PÚBLICA — descubierta por core/plugin_loader.py
# ─────────────────────────────────────────────────────────────────────────────

def scrape_instagram_dorks(
    timeout: int = 180,
    rotar_tor: bool = True,
    max_dorks: int = 10,
    **kwargs,
) -> list:
    """Scraper público de Instagram vía dorks (DDG → Mojeek → Google stealth).

    timeouts
    --------
    timeout   : presupuesto de tiempo total en segundos (default 180).
    rotar_tor : rotar identidad Tor entre motores (default True).
    max_dorks : cuántos dorks procesar por ejecución (default 10).

    Retorna lista de dicts con las 13 columnas del CSV. Siempre aditivo:
    nunca elimina filas existentes de eventos_encontrados.csv.
    """
    import os
    import time
    from core.csv_lock import csv_locked_rows

    t0 = time.time()
    eventos_nuevos: list = []

    ESTADO_DIR = os.path.join(os.path.dirname(__file__), "instagram_dorks")
    os.makedirs(ESTADO_DIR, exist_ok=True)
    URLS_VISTAS_PATH = os.path.join(ESTADO_DIR, "urls_vistas.json")
    urls_vistas: set = set(_leer_json(URLS_VISTAS_PATH, default=[]))

    try:
        config = _cargar_config()
    except Exception as e:
        print(f"⚠️  instagram_dorks: no se pudo cargar config: {e}")
        config = {}

    try:
        _get_sesion()          # valida que Tor/proxy responda (adapta al flag)
        _get_anti()
    except Exception as e:
        print(f"❌ instagram_dorks: sesión/anti-block falló: {e}")
        return []

    try:
        dorks = _generar_dorks(config)[:max_dorks]
    except Exception as e:
        print(f"❌ instagram_dorks: _generar_dorks falló: {e}")
        return []

    if not dorks:
        print("ℹ️  instagram_dorks: sin dorks generados (bloqueo anterior ?).")
        return []

    print(f"🔍 instagram_dorks: {len(dorks)} dorks — presupuesto {timeout}s")

    for dork in dorks:
        if time.time() - t0 > timeout:
            print("⏱️  instagram_dorks: presupuesto agotado, saliendo.")
            break

        print(f"  🔎 dork: {dork[:80]}")
        items: list = []

        # DDG
        try:
            r = _buscar_ddg(dork)
            if r:
                items.extend(r)
            else:
                print("  🚫 DDG no devolvió resultados (bloqueo o sin hits)")
        except Exception as e:
            print(f"  ⚠️  DDG error: {e}")

        _random_sleep()

        # Mojeek (si DDG no dio suficiente)
        if len(items) < 3:
            try:
                r = _buscar_mojeek(dork)
                if r:
                    items.extend(r)
            except Exception as e:
                print(f"  ⚠️  Mojeek error: {e}")

        _random_sleep()

        # Google Playwright (solo si stealth disponible y aún hay tiempo)
        if STEALTH_AVAILABLE and time.time() - t0 < timeout - 20:
            try:
                items.extend(_buscar_google_con_reintentos_ig(dork))
            except Exception as e:
                print(f"  ⚠️  Google stealth error: {e}")

        # Dedup local por url dentro del mismo dork
        vistos_dork = set()
        unicos = []
        for it in items:
            u = (it.get("url") or "").rstrip("/")
            if u and u not in vistos_dork:
                vistos_dork.add(u)
                unicos.append(it)
        items = unicos

        for item in items:
            if time.time() - t0 > timeout:
                break
            url = (item.get("url") or "").rstrip("/")
            titulo = item.get("titulo", "")
            snippet = item.get("snippet", "")

            if not url or url in urls_vistas:
                continue

            texto_rapido = f"{titulo} {snippet}"
            if not _es_relevante_ig(texto_rapido):
                urls_vistas.add(url)
                continue

            if _es_post_instagram(url):
                # Post/reel: se registra como hallazgo con título limpio.
                nombre = _limpiar_titulo_post_ig(titulo, snippet)
                try:
                    autor = _extraer_autor_de_post(url)
                except Exception:
                    autor = None
                if not nombre or not _es_relevante_ig(nombre):
                    urls_vistas.add(url)
                    continue
                fila = {
                    "nombre": nombre[:120],
                    "fecha": "", "lugar": "", "pais": "", "continente": "",
                    "subcontinente": "",
                    "fuente": "instagram_dorks",
                    "organizador": (author_to_organizer(autor) if autor else ""),
                    "email": "", "link": url,
                    "subgenero": "", "tipo_lugar": "", "contactos": "",
                }
            elif _es_perfil_instagram(url) or _es_organizador_instagram(url):
                # Perfil/organizador: registrar pero no como evento
                print(f"  👤 perfil/organizador: {url[:60]}")
                urls_vistas.add(url)
                continue
            else:
                urls_vistas.add(url)
                continue

            try:
                with csv_locked_rows("eventos_encontrados.csv") as (filas, _fn):
                    links = {f.get("link", "") for f in filas}
                    if fila["link"] not in links:
                        filas.append(fila)
                        eventos_nuevos.append(fila)
                        print(f"  ✅ nuevo evento IG: {fila['nombre'][:50]}")
            except Exception as e:
                print(f"  ❌ CSV lock error: {e}")

            urls_vistas.add(url)

        # Rotar identidad Tor entre dorks
        if rotar_tor:
            try:
                _rotar_identidad_tor()
            except Exception:
                pass

    try:
        _escribir_json(URLS_VISTAS_PATH, sorted(urls_vistas))
    except Exception as e:
        print(f"⚠️  instagram_dorks: no se guardó urls_vistas: {e}")

    elapsed = round(time.time() - t0, 1)
    print(f"🏁 instagram_dorks: {len(eventos_nuevos)} nuevos en {elapsed}s")
    return eventos_nuevos


def author_to_organizer(autor_url: str) -> str:
    """Convierte una URL de perfil de Instagram en nombre legible de organizador."""
    a = (autor_url or "").rstrip("/")
    if a and "/" in a:
        return a.rstrip("/").split("/")[-1].replace("_", " ").strip().title()
    return a or ""


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    print("🧪 Corriendo instagram_dorks directamente…")
    resultados = scrape_instagram_dorks(timeout=180)
    print(f"\n📦 Eventos encontrados: {len(resultados)}")
    for ev in resultados[:5]:
        print(json.dumps(ev, ensure_ascii=False, indent=2))