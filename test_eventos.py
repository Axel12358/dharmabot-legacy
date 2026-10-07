import asyncio
import random
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

async def test_eventos():
    query = "psytrance festival"  # Query más simple posible
    url = f"https://www.facebook.com/search/events/?q={query.replace(' ', '%20')}"
    
    print(f"🌐 Probando: {url}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=['--no-sandbox'])
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = await context.new_page()
        
        try:
            await page.goto(url, timeout=30000, wait_until='networkidle')
            await asyncio.sleep(5)
            
            # Ver qué hay en la página
            title = await page.title()
            print(f"📄 Título: {title}")
            
            # Tomar screenshot
            await page.screenshot(path="test_eventos.png")
            print("📸 Screenshot guardado: test_eventos.png")
            
            # Buscar cualquier texto que parezca evento
            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
            
            # Buscar cualquier div con texto
            textos = soup.find_all(['div', 'span'], text=True)
            eventos_texto = []
            for t in textos:
                text = t.get_text(strip=True)
                if text and len(text) > 20 and ('festival' in text.lower() or 'party' in text.lower() or 'event' in text.lower()):
                    eventos_texto.append(text[:100])
            
            print(f"🔎 Textos de eventos encontrados: {len(eventos_texto)}")
            for t in eventos_texto[:5]:
                print(f"   - {t}...")
            
        except Exception as e:
            print(f"❌ Error: {e}")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_eventos())
