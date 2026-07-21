import re
from typing import List, Dict, Any
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper
import config


class TecnoJobsScraper(BaseScraper):
    """
    Scraper de Tecnoempleo.com — portal IT/tech líder en España.
    Usa curl_cffi para evadir protecciones anti-bot.
    """
    MAX_RESULTS = config.MAX_JOBS_PER_SCRAPER
    TECNOEMPLEO_PROVINCES = {
        "sevilla": "274", "madrid": "263", "barcelona": "240",
        "valencia": "279", "malaga": "291", "bizkaia": "480",
        "guipuzcoa": "200", "aragon": "50", "asturias": "33",
        "galicia": "15", "castilla": "45", "murcia": "30",
    }

    def _fetch(self, url: str, params: dict = None) -> str:
        try:
            from curl_cffi import requests as cffi_requests
            resp = cffi_requests.get(url, params=params, impersonate=config.IMPERSONATE_BROWSER, timeout=config.REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp.text
            print(f"[TecnoEmpleo] curl_cffi status {resp.status_code}")
        except ImportError:
            print("[TecnoEmpleo] curl_cffi no disponible")
        except Exception as e:
            print(f"[TecnoEmpleo] Error curl_cffi: {e}")
        return ""

    def scrape_jobs(self, search_query: str, locations: List[str]) -> List[Dict[str, Any]]:
        print(f"[TecnoEmpleo] Buscando ofertas para '{search_query}'...")
        jobs = []
        encoded = search_query.replace(" ", "+")

        # Determinar parámetros de ubicación
        is_remote = any(loc.lower() in ("remoto", "remote") for loc in (locations or []))
        province_code = ""
        if not is_remote and locations:
            for loc in locations:
                code = self.TECNOEMPLEO_PROVINCES.get(loc.lower().strip())
                if code:
                    province_code = code
                    break

        url = f"https://www.tecnoempleo.com/ofertas-trabajo/?te={encoded}"
        if is_remote:
            url += "&en_remoto=,1,"
        elif province_code:
            url += f"&pr=,{province_code},"

        html = self._fetch(url)
        if not html:
            html = self.get_html(url)

        if not html:
            print("[TecnoEmpleo] No se pudo obtener HTML")
            return []

        soup = BeautifulSoup(html, "html.parser")

        # TecnoEmpleo usa cards con enlaces a /{empresa}/{tecnologias}/rf-{id}
        links = soup.find_all("a", href=re.compile(r"/rf-[a-f0-9]+"))
        seen = set()

        for link in links[:self.MAX_RESULTS]:
            try:
                href = link.get("href", "")
                if href.startswith("/"):
                    href = "https://www.tecnoempleo.com" + href
                if href in seen:
                    continue
                seen.add(href)

                title = link.get_text(strip=True)
                if not title or len(title) < 3:
                    continue

                parent = link.find_parent("div") or link.find_parent("li")

                # Empresa: selector actual a.text-primary.link-muted
                company = ""
                if parent:
                    company_tag = parent.select_one("a.text-primary.link-muted") or parent.select_one("a[href*='-trabajo']")
                    if company_tag:
                        company = company_tag.get_text(strip=True)

                # Ubicación: div col-lg-3 (desktop) o span d-block (mobile)
                location = ""
                if parent:
                    loc_tag = (parent.select_one("div.text-gray-700") or
                               parent.select_one("div.col-lg-3") or
                               parent.select_one("span.d-block.d-lg-none"))
                    if loc_tag:
                        loc_text = loc_tag.get_text(" ", strip=True)
                        # Extraer ciudad: buscar <b> dentro del tag
                        b_tag = loc_tag.find("b")
                        if b_tag:
                            city = b_tag.get_text(strip=True)
                            # Buscar modalidad (Presencial/Remoto/Híbrido)
                            mode = ""
                            for m in ["100% remoto", "Remoto", "Híbrido", "Presencial"]:
                                if m.lower() in loc_text.lower():
                                    mode = m
                                    break
                            location = f"{city} ({mode})" if mode else city
                        elif loc_text:
                            # Fallback: usar el texto directamente
                            location = loc_text.split("\n")[0].strip()

                # Descripción: span.hidden-md-down.text-gray-800
                description = ""
                if parent:
                    desc_tag = parent.select_one("span.hidden-md-down") or parent.select_one("span.text-gray-800")
                    if desc_tag:
                        description = desc_tag.get_text(" ", strip=True)[:300]

                if not location:
                    location = "España"

                jobs.append({
                    "title": title,
                    "company": company or "No especificada",
                    "location": location,
                    "link": href,
                    "description": description or title,
                    "date_posted": "Reciente",
                    "source": "TecnoEmpleo"
                })
            except Exception:
                continue

        print(f"[TecnoEmpleo] {len(jobs)} ofertas encontradas.")
        return jobs
