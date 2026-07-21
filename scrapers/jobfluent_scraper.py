import re
from typing import List, Dict, Any
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper
import config


class JobfluentScraper(BaseScraper):
    """
    Scraper de Jobfluent.com — portal tech-oriented.
    """
    MAX_RESULTS = config.MAX_JOBS_PER_SCRAPER

    def _fetch(self, url: str, params: dict = None) -> str:
        try:
            from curl_cffi import requests as cffi_requests
            resp = cffi_requests.get(url, params=params, impersonate=config.IMPERSONATE_BROWSER, timeout=config.REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp.text
            print(f"[Jobfluent] curl_cffi status {resp.status_code}")
        except ImportError:
            print("[Jobfluent] curl_cffi no disponible")
        except Exception as e:
            print(f"[Jobfluent] Error curl_cffi: {e}")
        return ""

    def _parse_card(self, card) -> dict:
        """Parsea una tarjeta de empleo con selectores robustos."""
        a_tag = None

        # Buscar enlace de empleo: probar múltiples selectores
        for selector in [
            "a[href*='/jobs/']",
            "a[href*='/ofertas/']",
            "a.offer-link",
            "h3 a",
            "h2 a",
            "a[href*='job']",
        ]:
            a_tag = card.select_one(selector)
            if a_tag and a_tag.get("href"):
                break

        if not a_tag:
            # Fallback: primer <a> con href que parezca empleo
            for a in card.find_all("a", href=True):
                href = a["href"]
                if "/jobs/" in href or "/ofertas/" in href or "job" in href.lower():
                    a_tag = a
                    break

        if not a_tag or not a_tag.get("href"):
            return None

        href = a_tag["href"]
        if href.startswith("/"):
            href = "https://jobfluent.com" + href

        # Título
        title = ""
        for sel in ["h3", "h2", ".job-title", ".title", "a.offer-title"]:
            tag = card.select_one(sel)
            if tag:
                title = tag.get_text(strip=True)
                if title:
                    break
        if not title:
            title = a_tag.get_text(strip=True)[:100]
        if not title or len(title) < 3:
            return None

        # Empresa: múltiples selectores
        company = ""
        for sel in [".company", ".employer", ".company-name", "a[href*='/company/']",
                    "span.company-name", "div.company"]:
            tag = card.select_one(sel)
            if tag:
                company = tag.get_text(strip=True)
                if company:
                    break
        # Fallback: buscar enlaces que parezcan empresas
        if not company:
            for a in card.find_all("a", href=True):
                if "/company/" in a["href"] or "/empresas/" in a["href"]:
                    company = a.get_text(strip=True)
                    if company:
                        break

        # Ubicación
        location = ""
        for sel in [".location", ".job-location", "span.location",
                    "div.location", "span.city", "span[data-location]"]:
            tag = card.select_one(sel)
            if tag:
                location = tag.get_text(strip=True)
                if location:
                    break
        if not location:
            location = "España"

        # Descripción
        description = ""
        for sel in [".description", ".snippet", ".job-description",
                    "p.description", "div.job-summary"]:
            tag = card.select_one(sel)
            if tag:
                description = tag.get_text(strip=True)
                if description:
                    break

        return {
            "title": title,
            "company": company or "No especificada",
            "location": location,
            "link": href,
            "description": description or title,
            "date_posted": "Reciente",
            "source": "Jobfluent"
        }

    def scrape_jobs(self, search_query: str, locations: List[str]) -> List[Dict[str, Any]]:
        print(f"[Jobfluent] Buscando ofertas para '{search_query}'...")
        jobs = []
        encoded = search_query.replace(" ", "+")

        url = f"https://jobfluent.com/jobs?q={encoded}"
        html = self._fetch(url)
        if not html:
            html = self.get_html(url)

        if not html:
            print("[Jobfluent] No se pudo obtener HTML")
            return []

        soup = BeautifulSoup(html, "html.parser")

        # Estrategia 1: buscar tarjetas con selectores específicos
        cards = []
        for selector in [
            "div.job-card",
            "div.offer-item",
            "article.job",
            "div.panel-offer",
            "div.job-offer",
            "div.offer-card",
        ]:
            cards = soup.select(selector)
            if cards:
                break

        # Estrategia 2: buscar por clases que contengan "job" o "offer"
        if not cards:
            cards = soup.find_all("div", class_=re.compile(r"job|offer", re.I))

        # Estrategia 3: buscar por enlaces a /jobs/ y usar el padre como card
        if not cards:
            job_links = soup.find_all("a", href=re.compile(r"/jobs/"))
            seen_parents = set()
            for link in job_links:
                parent = link.find_parent("div") or link.find_parent("article") or link.find_parent("li")
                if parent and id(parent) not in seen_parents:
                    seen_parents.add(id(parent))
                    cards.append(parent)

        seen = set()
        for card in cards[:self.MAX_RESULTS]:
            try:
                result = self._parse_card(card)
                if not result or not result["link"]:
                    continue
                if result["link"] in seen:
                    continue
                seen.add(result["link"])
                jobs.append(result)
            except Exception:
                continue

        print(f"[Jobfluent] {len(jobs)} ofertas encontradas.")
        return jobs
