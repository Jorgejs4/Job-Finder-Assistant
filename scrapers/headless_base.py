import asyncio
import time
from typing import List, Dict, Any, Optional
from abc import abstractmethod
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper
import config


class HeadlessScraper(BaseScraper):
    """
    Clase base para scrapers que requieren un navegador headless (Playwright).
    Gestiona el ciclo de vida del browser y proporciona helpers comunes.
    """
    MAX_RETRIES = 2
    PAGE_TIMEOUT = 30000
    NAVIGATION_TIMEOUT = 25000

    def __init__(self):
        super().__init__()
        self._browser = None
        self._context = None

    async def _ensure_browser(self):
        if self._browser is not None:
            return
        try:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ]
            )
            self._context = await self._browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                locale="es-ES",
                viewport={"width": 1920, "height": 1080},
                extra_http_headers={
                    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
                }
            )
        except ImportError:
            raise RuntimeError(
                "Playwright no instalado. Ejecuta: pip install playwright && playwright install chromium"
            )

    async def _get_page_html(self, url: str, wait_selector: Optional[str] = None,
                             wait_time: int = 3000) -> str:
        """Navega a la URL y espera a que el contenido se renderice."""
        await self._ensure_browser()
        page = await self._context.new_page()
        try:
            await page.goto(url, timeout=self.NAVIGATION_TIMEOUT, wait_until="domcontentloaded")
            if wait_selector:
                try:
                    await page.wait_for_selector(wait_selector, timeout=self.PAGE_TIMEOUT)
                except Exception:
                    pass
            else:
                await page.wait_for_timeout(wait_time)
            html = await page.content()
            return html
        finally:
            await page.close()

    async def _scroll_and_collect(self, url: str, card_selector: str,
                                  max_items: int = 50, scroll_pauses: int = 3) -> str:
        """Navega, hace scroll para cargar más ofertas y devuelve el HTML final."""
        await self._ensure_browser()
        page = await self._context.new_page()
        try:
            await page.goto(url, timeout=self.NAVIGATION_TIMEOUT, wait_until="domcontentloaded")
            try:
                await page.wait_for_selector(card_selector, timeout=10000)
            except Exception:
                pass

            for _ in range(scroll_pauses):
                current_count = await page.evaluate(
                    f'document.querySelectorAll("{card_selector}").length'
                )
                if current_count >= max_items:
                    break
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)

            await page.wait_for_timeout(1000)
            return await page.content()
        finally:
            await page.close()

    async def close(self):
        """Cierra el navegador. Llámalo después de todas las extracciones."""
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if hasattr(self, '_playwright') and self._playwright:
            await self._playwright.stop()

    @abstractmethod
    async def scrape_jobs_async(self, search_query: str, locations: List[str]) -> List[Dict[str, Any]]:
        pass

    def scrape_jobs(self, search_query: str, locations: List[str]) -> List[Dict[str, Any]]:
        """Wrapper síncrono. Usa un event loop limpio en cada llamada."""
        async def _run():
            try:
                r = await self.scrape_jobs_async(search_query, locations)
                return r
            finally:
                await self.close()
        try:
            return asyncio.run(_run())
        except Exception as e:
            print(f"[Headless] Error en event loop: {e}")
            return []
