from abc import ABC, abstractmethod
from typing import List, Dict, Any
import httpx
import config

class BaseScraper(ABC):
    """
    Clase base para todos los scrapers de portales de empleo.
    Proporciona cabeceras comunes y utilidades de red.
    """
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Connection": "keep-alive"
        }
        self.client = httpx.Client(headers=self.headers, follow_redirects=True, timeout=config.REQUEST_TIMEOUT)

    @abstractmethod
    def scrape_jobs(self, search_query: str, locations: List[str]) -> List[Dict[str, Any]]:
        """
        Debe ser implementado por cada scraper.
        Retorna una lista de diccionarios con la estructura:
        {
            "title": str,
            "company": str,
            "location": str,
            "link": str,
            "description": str,
            "date_posted": str,  # Formato YYYY-MM-DD o texto descriptivo
            "source": str        # InfoJobs, LinkedIn, etc.
        }
        """
        pass

    def get_html(self, url: str, params: dict = None) -> str:
        """Helper para realizar peticiones GET seguras."""
        try:
            response = self.client.get(url, params=params)
            response.raise_for_status()
            return response.text
        except Exception as e:
            print(f"Error cargando la URL {url}: {e}")
            return ""
