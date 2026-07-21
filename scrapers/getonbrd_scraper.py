import re
import json
from typing import List, Dict, Any
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper
import config


class GetOnBoardScraper(BaseScraper):
    """
    Scraper de GetOnBoard (getonbrd.com) — LATAM tech jobs vía HTML.
    Busca trabajos remotos de programación.
    """
    BASE_URL = "https://www.getonbrd.com/jobs/programming"
    MAX_RESULTS = config.MAX_JOBS_PER_SCRAPER

    def _fetch(self, url: str) -> str:
        """Fetch con curl_cffi."""
        try:
            from curl_cffi import requests as cffi_requests
            headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            }
            resp = cffi_requests.get(url, headers=headers, impersonate="chrome131", timeout=20)
            if resp.status_code == 200:
                return resp.text
            print(f"[GetOnBoard] curl_cffi status {resp.status_code}")
        except ImportError:
            print("[GetOnBoard] curl_cffi no disponible")
        except Exception as e:
            print(f"[GetOnBoard] Error: {e}")
        return ""

    def _parse_job_card(self, card) -> dict:
        """Parsea un link de trabajo de GetOnBoard."""
        try:
            href = card.get("href", "")
            if not href or href.endswith("/programming") or href.endswith("/programacion"):
                return None
            if "/jobs/programming/" not in href and "/jobs/programacion/" not in href:
                return None

            text = card.get_text(separator="|", strip=True)
            parts = [p.strip() for p in text.split("|") if p.strip()]

            title = parts[0] if parts else ""
            if not title or len(title) < 3:
                return None

            company = ""
            location = ""
            for p in parts[1:]:
                if "·" in p:
                    company, location = p.split("·", 1)
                    company = company.strip()
                    location = location.strip()
                elif not company and len(p) < 60:
                    company = p.strip()

            if not href.startswith("http"):
                href = "https://www.getonbrd.com" + href

            return {
                "title": title,
                "company": company or "No especificada",
                "location": location or "LATAM",
                "link": href,
                "description": title,
                "date_posted": "Reciente",
                "source": "GetOnBoard",
            }
        except Exception:
            return None

    def scrape_jobs(self, search_query: str, locations: List[str]) -> List[Dict[str, Any]]:
        print(f"[GetOnBoard] Buscando ofertas para '{search_query}'...")
        jobs = []

        html = self._fetch(self.BASE_URL)
        if not html:
            html = self.get_html(self.BASE_URL)

        if not html:
            print("[GetOnBoard] No se pudo obtener HTML")
            return []

        soup = BeautifulSoup(html, "html.parser")

        # Buscar links de trabajos de programación
        cards = soup.select("a[href*='/jobs/programming/'], a[href*='/jobs/programacion/']")
        seen = set()
        parsed = []

        for card in cards:
            result = self._parse_job_card(card)
            if result and result["link"] not in seen:
                seen.add(result["link"])
                parsed.append(result)

        # Filtrar por query si se proporciona
        if search_query:
            query_lower = search_query.lower()
            query_words = query_lower.split()
            filtered = []
            for job in parsed:
                title_lower = job["title"].lower()
                desc_lower = job.get("description", "").lower()
                if any(w in title_lower or w in desc_lower for w in query_words):
                    filtered.append(job)
            parsed = filtered

        print(f"[GetOnBoard] {len(parsed)} ofertas encontradas")
        return parsed[:self.MAX_RESULTS]
