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
    MAX_RESULTS = 50

    def _fetch(self, url: str, params: dict = None) -> str:
        try:
            from curl_cffi import requests as cffi_requests
            resp = cffi_requests.get(url, params=params, impersonate="chrome131", timeout=20)
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

        is_remote = any(loc.lower() in ("remoto", "remote") for loc in (locations or []))
        if is_remote:
            url = f"https://www.tecnoempleo.com/ofertas-trabajo/?te={encoded}&en_remoto=,1,"
        else:
            url = f"https://www.tecnoempleo.com/ofertas-trabajo/?te={encoded}"

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

                # La empresa suele estar en un nodo hermano o padre
                company = ""
                parent = link.find_parent("div") or link.find_parent("li")
                if parent:
                    for sep in [",", "("]:
                        full_text = parent.get_text(" ", strip=True)
                        parts = full_text.split(sep)
                        if len(parts) > 1:
                            candidate = parts[-1].strip().rstrip(")")
                            if 3 < len(candidate) < 60:
                                company = candidate
                                break

                location = ""
                loc_tag = parent.select_one(".text-muted, .location") if parent else None
                if loc_tag:
                    location = loc_tag.get_text(strip=True)
                if not location:
                    location = "España"

                desc = ""
                desc_tag = parent.select_one(".description, .snippet") if parent else None
                if desc_tag:
                    desc = desc_tag.get_text(strip=True)

                jobs.append({
                    "title": title,
                    "company": company or "No especificada",
                    "location": location,
                    "link": href,
                    "description": desc or title,
                    "date_posted": "Reciente",
                    "source": "TecnoEmpleo"
                })
            except Exception:
                continue

        print(f"[TecnoEmpleo] {len(jobs)} ofertas encontradas.")
        return jobs
