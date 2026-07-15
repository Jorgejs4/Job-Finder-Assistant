import re
import json
from typing import List, Dict, Any
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper
import config


class ComputrabajoScraper(BaseScraper):
    def _fetch_with_cffi(self, url: str) -> str:
        """Fetch usando curl_cffi para evadir protección anti-bot."""
        try:
            from curl_cffi import requests as cffi_requests
            resp = cffi_requests.get(url, impersonate="chrome131", timeout=20)
            if resp.status_code == 200:
                return resp.text
            print(f"[Computrabajo] curl_cffi devolvió status {resp.status_code}")
        except ImportError:
            print("[Computrabajo] curl_cffi no disponible")
        except Exception as e:
            print(f"[Computrabajo] Error con curl_cffi: {e}")
        return ""

    def scrape_jobs(self, search_query: str, locations: List[str]) -> List[Dict[str, Any]]:
        """
        Scraping de Computrabajo España.
        """
        print(f"[Computrabajo] Buscando ofertas para '{search_query}'...")
        jobs = []

        search_locations = locations if locations else ["sevilla"]

        for loc in search_locations:
            api_loc = config.get_location_for("computrabajo", loc)
            print(f"[Computrabajo] Buscando en ubicación: {api_loc}")

            slug = api_loc.lower().replace(" ", "-").replace(",", "")
            encoded_query = search_query.replace(" ", "+")
            url = f"https://www.computrabajo.es/trabajo-de-{encoded_query.lower()}-en-{slug}"

            html = self._fetch_with_cffi(url)
            if not html:
                try:
                    response = self.client.get(url)
                    if response.status_code == 200:
                        html = response.text
                except Exception:
                    pass

            if not html:
                print(f"[Computrabajo] No se pudo obtener HTML para {api_loc}")
                continue

            soup = BeautifulSoup(html, "html.parser")

            # Selectores para las tarjetas de Computrabajo
            cards = soup.select("article.box_offer, div.box_offer, article[data-id]")
            if not cards:
                cards = soup.find_all("a", class_=re.compile(r"js-o-link"))
            if not cards:
                # Fallback: buscar todos los enlaces a ofertas
                cards = [a.parent for a in soup.find_all("a", href=re.compile(r"/ofertas-de-trabajo/"))]

            print(f"[Computrabajo] {len(cards)} tarjetas encontradas para {api_loc}")

            for card in cards[:15]:  # Limitar a 15 por ubicación
                try:
                    result = self._parse_card(card, url)
                    if result and result["link"]:
                        jobs.append(result)
                except Exception as e:
                    print(f"[Computrabajo] Error parseando tarjeta: {e}")
                    continue

        print(f"[Computrabajo] Total: {len(jobs)} ofertas")
        return jobs

    def _parse_card(self, card, base_url: str) -> dict:
        """Parsea una tarjeta individual de Computrabajo."""
        # Buscar enlace
        link_tag = None
        if card.name == "a":
            link_tag = card
        else:
            link_tag = card.find("a", href=re.compile(r"/ofertas-de-trabajo/"))
            if not link_tag:
                link_tag = card.find("a", class_=re.compile(r"js-o-link|fc_base"))

        if not link_tag or not link_tag.get("href"):
            return None

        link = link_tag["href"]
        if link.startswith("/"):
            link = "https://www.computrabajo.es" + link

        # Título
        title_tag = card.find("h2") or card.find("a", class_=re.compile(r"fc_base"))
        title = title_tag.text.strip() if title_tag else ""
        if not title:
            return None

        # Empresa
        company_tag = card.find("span", class_=re.compile(r"fc_base|company"))
        if not company_tag:
            company_tag = card.find("a", class_=re.compile(r"fc_base"))
        company = ""
        if company_tag:
            company = company_tag.text.strip()
            # Limpiar si tiene saltos de línea o espacios extra
            company = re.sub(r'\s+', ' ', company)

        if not company or company == title:
            company = "No especificada"

        # Ubicación
        loc_tag = card.find("span", class_=re.compile(r"location|fc_aux"))
        location = loc_tag.text.strip() if loc_tag else ""
        if not location:
            location = "España"

        # Descripción breve
        desc_tag = card.find("p", class_=re.compile(r"description|fc_aux"))
        description = desc_tag.text.strip() if desc_tag else ""

        return {
            "title": title,
            "company": company,
            "location": location,
            "link": link,
            "description": description,
            "date_posted": "Reciente",
            "source": "Computrabajo"
        }
