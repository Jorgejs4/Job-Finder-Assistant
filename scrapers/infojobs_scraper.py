import json
import re
from typing import List, Dict, Any
from scrapers.base_scraper import BaseScraper
import config


class InfoJobsScraper(BaseScraper):
    def _fetch_via_curl_cffi(self, url: str) -> str:
        """Fetch usando curl_cffi para evadir protecciones anti-bot (Distil Networks)."""
        try:
            from curl_cffi import requests as cffi_requests
            resp = cffi_requests.get(url, impersonate="chrome131", timeout=20)
            if resp.status_code == 200:
                return resp.text
            print(f"[InfoJobs] curl_cffi devolvió status {resp.status_code}")
        except ImportError:
            print("[InfoJobs] curl_cffi no disponible, usando httpx (puede ser bloqueado)")
        except Exception as e:
            print(f"[InfoJobs] Error con curl_cffi: {e}")
        return ""

    def _parse_initial_props(self, html: str) -> List[Dict]:
        """Extrae ofertas del JSON embebido en window.__INITIAL_PROPS__."""
        match = re.search(
            r'window\.__INITIAL_PROPS__\s*=\s*JSON\.parse\("(.+?)"\)', html
        )
        if not match:
            return []
        try:
            raw = match.group(1).encode().decode("unicode_escape")
            data = json.loads(raw)
            offers = data.get("offers", [])
            if not offers:
                offers = data.get("searchResults", {}).get("offers", [])
            return offers
        except Exception as e:
            print(f"[InfoJobs] Error parseando __INITIAL_PROPS__: {e}")
            return []

    def _parse_offers_html(self, html: str) -> List[Dict]:
        """Fallback: parsea tarjetas de oferta del HTML directamente."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("[data-testid='o-card'], .ij-Card, .oj-Link")
        if not cards:
            cards = soup.find_all("a", href=re.compile(r"/ofertas-trabajo/"))
        return cards

    def _format_offer(self, offer: dict, search_location: str) -> dict:
        """Convierte una oferta cruda de InfoJobs al formato estándar."""
        title = offer.get("title", "Puesto no especificado")
        company = offer.get("companyName", "No especificada")
        if not company or company.strip() == "":
            company = "No especificada"

        city = offer.get("city", "")
        province = offer.get("province", "")
        location_parts = [p for p in [city, province, "España"] if p]
        location = ", ".join(location_parts) if city else config.get_location_for("infojobs", search_location)

        link = offer.get("link", "")
        if not link:
            offer_id = offer.get("id", offer.get("code", ""))
            link = f"https://www.infojobs.net/ofertas-trabajo/{offer_id}" if offer_id else ""

        description = offer.get("description", offer.get("requirementMin", ""))

        salary_desc = offer.get("salaryDescription", "")
        salary_min = offer.get("salaryMin")
        salary_max = offer.get("salaryMax")

        published = offer.get("published", offer.get("publishedAt", ""))

        return {
            "title": title,
            "company": company,
            "location": location,
            "link": link,
            "description": description,
            "date_posted": published[:10] if published and len(published) >= 10 else "Reciente",
            "source": "InfoJobs",
            "salary_raw": salary_desc,
            "salary_min": salary_min,
            "salary_max": salary_max,
        }

    def _is_remote(self, offer: dict) -> bool:
        teleworking = offer.get("teleworking", "")
        if isinstance(teleworking, dict):
            teleworking = teleworking.get("value", "")
        title = offer.get("title", "").lower()
        desc = offer.get("description", "").lower()
        remote_kw = ["remoto", "remote", "teletrabajo", "distancia", "teleworking"]
        return any(kw in str(teleworking).lower() for kw in remote_kw) or \
               any(kw in title for kw in remote_kw) or \
               any(kw in desc for kw in remote_kw)

    def scrape_jobs(self, search_query: str, locations: List[str]) -> List[Dict[str, Any]]:
        """
        Obtiene ofertas de InfoJobs usando SPA hydration (window.__INITIAL_PROPS__)
        con curl_cffi para evadir protecciones anti-bot.
        """
        print(f"[InfoJobs] Buscando ofertas para '{search_query}'...")
        jobs = []

        search_locations = locations if locations else ["España"]

        for loc in search_locations:
            infojobs_slug = config.get_location_for("infojobs", loc)
            is_remote_search = loc.lower() in ("remoto", "remote")

            print(f"[InfoJobs] Buscando en ubicación: {infojobs_slug}")

            encoded_query = search_query.replace(" ", "+")
            if is_remote_search:
                url = f"https://www.infojobs.net/ofertas-trabajo/teletrabajo?keyword={encoded_query}"
            else:
                # Usar URL por ciudad (funciona) en vez de query params (devuelve vacío)
                province_slug = self._get_province_name(infojobs_slug)
                city_slug = infojobs_slug
                url = f"https://www.infojobs.net/ofertas-trabajo/{province_slug}/{city_slug}?keyword={encoded_query}"

            html = self._fetch_via_curl_cffi(url)
            if not html:
                html = self.get_html(url)

            if not html:
                print(f"[InfoJobs] No se pudo obtener HTML para {infojobs_slug}")
                continue

            offers = self._parse_initial_props(html)

            if not offers:
                print(f"[InfoJobs] No se encontraron ofertas en __INITIAL_PROPS__ para {infojobs_slug}")
                continue

            print(f"[InfoJobs] {len(offers)} ofertas encontradas para {infojobs_slug}")

            for offer in offers:
                if is_remote_search and not self._is_remote(offer):
                    continue

                job = self._format_offer(offer, loc)
                if job["link"]:
                    jobs.append(job)

        print(f"[InfoJobs] Encontradas {len(jobs)} ofertas que coinciden con las preferencias.")
        return jobs

    def _get_province_name(self, slug: str) -> str:
        """Devuelve el slug de provincia para la URL de InfoJobs."""
        province_names = {
            "sevilla": "sevilla",
            "madrid": "madrid",
            "barcelona": "barcelona",
            "valencia": "valencia",
            "vizcaya": "vizcaya",
            "alicante": "alicante",
            "malaga": "malaga",
            "zaragoza": "zaragoza",
            "murcia": "murcia",
            "cadiz": "cadiz",
            "granada": "granada",
            "cordoba": "cordoba",
            "pontevedra": "pontevedra",
            "a coruna": "a-coruna",
            "asturias": "asturias",
            "cantabria": "cantabria",
            "navarra": "navarra",
            "almeria": "almeria",
            "jaen": "jaen",
            "huelva": "huelva",
            "ciudad real": "ciudad-real",
            "toledo": "toledo",
            "badajoz": "badajoz",
            "salamanca": "salamanca",
            "leon": "leon",
            "burgos": "burgos",
            "valladolid": "valladolid",
            "santa cruz de tenerife": "santa-cruz-de-tenerife",
            "las palmas": "las-palmas",
            "bizkaia": "vizcaya",
            "gipuzkoa": "guipuzcoa",
            "alava": "alava",
            "huesca": "huesca",
            "teruel": "teruel",
            "castellon": "castellon",
            "cuenca": "cuenca",
            "guadalajara": "guadalajara",
            "segovia": "segovia",
            "avila": "avila",
            "soria": "soria",
            "palencia": "palencia",
            "zamora": "zamora",
            "lugo": "lugo",
            "ourense": "ourense",
            "lerida": "lerida",
            "girona": "girona",
        }
        return province_names.get(slug.lower(), slug.lower())
