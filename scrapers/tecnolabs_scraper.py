import re
import json
from typing import List, Dict, Any
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper
import config


class TecnoJobsScraper(BaseScraper):
    def _fetch_with_cffi(self, url: str) -> str:
        """Fetch usando curl_cffi."""
        try:
            from curl_cffi import requests as cffi_requests
            resp = cffi_requests.get(url, impersonate="chrome131", timeout=20)
            if resp.status_code == 200:
                return resp.text
            print(f"[TecnoJobs] curl_cffi devolvió status {resp.status_code}")
        except ImportError:
            print("[TecnoJobs] curl_cffi no disponible")
        except Exception as e:
            print(f"[TecnoJobs] Error con curl_cffi: {e}")
        return ""

    def scrape_jobs(self, search_query: str, locations: List[str]) -> List[Dict[str, Any]]:
        """
        Scraping de TecnoJobs España - portal especializado en empleo tecnológico.
        """
        print(f"[TecnoJobs] Buscando ofertas para '{search_query}'...")
        jobs = []

        search_locations = locations if locations else ["sevilla"]

        for loc in search_locations:
            api_loc = config.get_location_for("tecnolabs", loc)
            print(f"[TecnoJobs] Buscando en ubicación: {api_loc}")

            slug = api_loc.lower().replace(" ", "-").replace(",", "")
            encoded_query = search_query.replace(" ", "+")

            # TecnoJobs tiene buscador por ciudad y keyword
            url = f"https://www.tecnolabs.es/empleo/{slug}?q={encoded_query}"

            html = self._fetch_with_cffi(url)
            if not html:
                try:
                    response = self.client.get(url)
                    if response.status_code == 200:
                        html = response.text
                except Exception:
                    pass

            if not html:
                # Intentar URL base sin ciudad
                url = f"https://www.tecnolabs.es/empleo?q={encoded_query}"
                html = self._fetch_with_cffi(url)

            if not html:
                print(f"[TecnoJobs] No se pudo obtener HTML para {api_loc}")
                continue

            soup = BeautifulSoup(html, "html.parser")

            # Buscar tarjetas de empleo
            cards = soup.select("div.job-card, article.job-card, div.oferta, article.oferta")
            if not cards:
                cards = soup.select("[class*=job], [class*=oferta]")
            if not cards:
                cards = soup.find_all("a", href=re.compile(r"/empleo/"))

            print(f"[TecnoJobs] {len(cards)} tarjetas encontradas para {api_loc}")

            for card in cards[:15]:
                try:
                    result = self._parse_card(card, url)
                    if result and result["link"]:
                        jobs.append(result)
                except Exception as e:
                    print(f"[TecnoJobs] Error parseando tarjeta: {e}")
                    continue

        print(f"[TecnoJobs] Total: {len(jobs)} ofertas")
        return jobs

    def _parse_card(self, card, base_url: str) -> dict:
        """Parsea una tarjeta individual de TecnoJobs."""
        link_tag = card.find("a", href=True) if card.name != "a" else card
        if not link_tag or not link_tag.get("href"):
            return None

        link = link_tag["href"]
        if link.startswith("/"):
            link = "https://www.tecnolabs.es" + link

        title_tag = card.find(["h2", "h3", "h4"]) or card.find("a", class_=re.compile(r"title|name"))
        title = title_tag.text.strip() if title_tag else ""
        if not title:
            return None

        company_tag = card.find(["span", "div", "p"], class_=re.compile(r"company|empresa|employer"))
        company = company_tag.text.strip() if company_tag else "No especificada"

        loc_tag = card.find(["span", "div"], class_=re.compile(r"location|ubicacion|city"))
        location = loc_tag.text.strip() if loc_tag else "España"

        desc_tag = card.find(["p", "div"], class_=re.compile(r"desc|snippet|summary"))
        description = desc_tag.text.strip() if desc_tag else ""

        return {
            "title": title,
            "company": company,
            "location": location,
            "link": link,
            "description": description,
            "date_posted": "Reciente",
            "source": "TecnoJobs"
        }
