import re
import json
from typing import List, Dict, Any
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper
import config


class JoobleScraper(BaseScraper):
    """
    Scraper de Jooble vía API (requiere API key gratuita) o HTML fallback.
    Jooble agrega ofertas de múltiples portales.
    API key gratis: https://jooble.org/api/about
    """
    API_URL = "https://jooble.org/api"
    HTML_URL = "https://es.jooble.org/SearchResult"
    MAX_RESULTS = 50

    def _fetch_api(self, query: str, location: str) -> list:
        """Intenta usar la API de Jooble (si hay API key configurada)."""
        api_key = getattr(config, "JOOBLE_API_KEY", "")
        if not api_key:
            return []

        try:
            import httpx
            resp = httpx.post(
                f"{self.API_URL}/{api_key}",
                json={"keywords": query, "location": location, "page": 1},
                headers={"Content-Type": "application/json"},
                timeout=20,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("jobs", [])
        except Exception as e:
            print(f"[Jooble] API error: {e}")
        return []

    def _fetch_html(self, url: str, params: dict = None) -> str:
        """Fetch vía HTML con curl_cffi (puede fallar por Cloudflare)."""
        try:
            from curl_cffi import requests as cffi_requests
            headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
                "Referer": "https://es.jooble.org/",
            }
            for imp in ["chrome131", "chrome120", "safari17_0"]:
                try:
                    resp = cffi_requests.get(
                        url, params=params, headers=headers,
                        impersonate=imp, timeout=20
                    )
                    if resp.status_code == 200:
                        return resp.text
                except Exception:
                    continue
        except ImportError:
            pass
        return ""

    def _parse_html_card(self, card) -> dict:
        """Parsea una tarjeta de empleo de Jooble HTML."""
        try:
            a_tag = card.find("a", href=True)
            if not a_tag:
                return None

            href = a_tag["href"]
            if href.startswith("/"):
                href = "https://es.jooble.org" + href

            title = ""
            for sel in ["h2", "h3", "[data-test-name='jobTitle']", ".title"]:
                t = card.select_one(sel)
                if t:
                    title = t.get_text(strip=True)
                    break
            if not title:
                title = a_tag.get_text(strip=True)[:120]
            if not title:
                return None

            company = ""
            for sel in ["[data-test-name='companyName']", ".company", ".companyName"]:
                c = card.select_one(sel)
                if c:
                    company = c.get_text(strip=True)
                    break

            loc_tag = card.select_one("[data-test-name='location'], .location")
            location = loc_tag.get_text(strip=True) if loc_tag else ""

            desc_tag = card.select_one("[data-test-name='jobDescription'], .description, .snippet")
            description = desc_tag.get_text(strip=True) if desc_tag else title

            return {
                "title": title,
                "company": company or "No especificada",
                "location": location,
                "link": href,
                "description": description,
                "date_posted": "Reciente",
                "source": "Jooble",
            }
        except Exception:
            return None

    def _format_api_job(self, job: dict) -> dict:
        """Convierte un job de la API de Jooble al formato estándar."""
        return {
            "title": job.get("title", "No especificado"),
            "company": job.get("company", "No especificada"),
            "location": job.get("location", ""),
            "link": job.get("link", ""),
            "description": job.get("snippet", job.get("title", "")),
            "date_posted": job.get("updated", "Reciente")[:10] if job.get("updated") else "Reciente",
            "source": "Jooble",
            "salary_raw": job.get("salary", ""),
        }

    def scrape_jobs(self, search_query: str, locations: List[str]) -> List[Dict[str, Any]]:
        print(f"[Jooble] Buscando ofertas para '{search_query}'...")
        jobs = []

        search_locations = locations if locations else ["España"]

        for loc in search_locations:
            jooble_loc = config.get_location_for("jooble", loc)

            # Intentar API primero (más fiable)
            api_jobs = self._fetch_api(search_query, jooble_loc)
            if api_jobs:
                for job in api_jobs[:self.MAX_RESULTS]:
                    formatted = self._format_api_job(job)
                    if formatted["link"]:
                        jobs.append(formatted)
                print(f"[Jooble] {len(jobs)} ofertas vía API para {jooble_loc}")
                continue

            # Fallback: HTML scraping (puede fallar por Cloudflare)
            params = {"p": 1, "ukw": search_query, "rgns": jooble_loc}
            html = self._fetch_html(self.HTML_URL, params=params)

            if not html or "Just a moment" in html:
                print(f"[Jooble] Cloudflare bloqueó HTML para {jooble_loc} (usa API key para mejor resultado)")
                continue

            soup = BeautifulSoup(html, "html.parser")
            cards = soup.select("article, [class*='JobCard'], [class*='vacancy']")
            if not cards:
                cards = soup.find_all("article")

            for card in cards[:self.MAX_RESULTS]:
                result = self._parse_html_card(card)
                if result and result["link"]:
                    jobs.append(result)

            print(f"[Jooble] {len(jobs)} ofertas vía HTML para {jooble_loc}")

        print(f"[Jooble] Total: {len(jobs)} ofertas")
        return jobs
