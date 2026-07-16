import re
from typing import List, Dict, Any
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper
import config


class IndeedScraper(BaseScraper):
    def _fetch_with_cffi(self, url: str, params: dict = None) -> str:
        """Fetch usando curl_cffi para evadir Cloudflare. Prueba múltiples impersonations y cookies."""
        try:
            from curl_cffi import requests as cffi_requests
            headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "es-ES,es;q=0.9,en-US;q=0.8,en;q=0.7",
                "Referer": "https://es.indeed.com/",
                "DNT": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Upgrade-Insecure-Requests": "1",
            }
            for impersonation in ["chrome131", "chrome120", "safari17_0"]:
                try:
                    resp = cffi_requests.get(
                        url, params=params, headers=headers,
                        impersonate=impersonation, timeout=20
                    )
                    if resp.status_code == 200:
                        return resp.text
                    if resp.status_code == 403:
                        # Intentar con cookie de consentimiento
                        cookies = {"CONSENT": "YES+cb.20210328-17-p0.en+FX+410"}
                        resp2 = cffi_requests.get(
                            url, params=params, headers=headers, cookies=cookies,
                            impersonate=impersonation, timeout=20
                        )
                        if resp2.status_code == 200:
                            return resp2.text
                        continue
                    print(f"[Indeed] curl_cffi ({impersonation}) status {resp.status_code}")
                except Exception:
                    continue
        except ImportError:
            print("[Indeed] curl_cffi no disponible")
        except Exception as e:
            print(f"[Indeed] Error con curl_cffi: {e}")
        return ""

    def _parse_job_card(self, card, source_url: str) -> dict:
        """Parsea una tarjeta de empleo de Indeed."""
        # Título y enlace
        title_tag = card.find("h2", class_="jobTitle") or card.find("a", {"data-jk": True})
        if not title_tag:
            title_tag = card.find("a", id=re.compile(r"job_"))
        if not title_tag:
            return None

        a_tag = title_tag.find("a") if title_tag.name == "h2" else title_tag
        title = title_tag.text.strip() if title_tag else ""
        if not title:
            return None

        link = ""
        if a_tag and a_tag.get("href"):
            href = a_tag["href"]
            if href.startswith("/"):
                link = "https://es.indeed.com" + href
            elif href.startswith("http"):
                link = href

        # Empresa
        company_tag = (card.find("span", {"data-testid": "company-name"}) or
                       card.find("span", class_="companyName") or
                       card.find("span", class_="company"))
        company = company_tag.text.strip() if company_tag else "No especificada"

        # Ubicación
        loc_tag = (card.find("div", {"data-testid": "text-location"}) or
                   card.find("div", class_="companyLocation"))
        location = loc_tag.text.strip() if loc_tag else ""

        # Descripción
        desc_tag = (card.find("div", class_="job-snippet") or
                    card.find("table", class_="jobCard_mainContent") or
                    card.find("div", class_="yui-u first"))
        description = desc_tag.text.strip() if desc_tag else ""

        return {
            "title": title,
            "company": company,
            "location": location,
            "link": link,
            "description": description,
            "date_posted": "Reciente",
            "source": "Indeed"
        }

    def scrape_jobs(self, search_query: str, locations: List[str]) -> List[Dict[str, Any]]:
        """
        Scraper para Indeed España. Usa curl_cffi para evadir Cloudflare.
        """
        print(f"[Indeed] Buscando ofertas para '{search_query}'...")
        jobs = []

        search_locations = locations if locations else ["España"]

        for loc in search_locations:
            api_loc = config.get_location_for("indeed", loc)
            print(f"[Indeed] Buscando en ubicación: {api_loc}")

            url = "https://es.indeed.com/jobs"
            params = {
                "q": search_query,
                "l": api_loc,
                "fromage": 7,
            }

            html = self._fetch_with_cffi(url, params=params)
            if not html:
                # Fallback a httpx normal
                try:
                    response = self.client.get(url, params=params)
                    if response.status_code == 200:
                        html = response.text
                except Exception:
                    pass

            if not html:
                print(f"[Indeed] No se pudo obtener HTML para {api_loc}")
                continue

            soup = BeautifulSoup(html, "html.parser")

            # Buscar tarjetas de empleo con múltiples selectores
            cards = soup.find_all("div", class_="job_seen_beacon")
            if not cards:
                cards = soup.find_all("div", class_=re.compile(r"jobsearch-ResultsList"))
            if not cards:
                cards = soup.select("div.job_seen_beacon, td.resultContent")

            # Parsear cards
            parsed = []
            for card in cards:
                result = self._parse_job_card(card, url)
                if result and result["link"]:
                    parsed.append(result)

            print(f"[Indeed] {len(parsed)} ofertas encontradas para {api_loc}")

            # Fallback: extraer del script JSON embebido
            if not parsed:
                scripts = soup.find_all("script", type="application/ld+json")
                for script in scripts:
                    try:
                        import json
                        data = json.loads(script.string or "")
                        items = data if isinstance(data, list) else [data]
                        for item in items:
                            if item.get("@type") == "JobPosting":
                                link = item.get("url", "")
                                parsed.append({
                                    "title": item.get("title", "No especificado"),
                                    "company": item.get("hiringOrganization", {}).get("name", "No especificada"),
                                    "location": item.get("jobLocation", {}).get("address", {}).get("addressLocality", api_loc),
                                    "link": link,
                                    "description": item.get("description", ""),
                                    "date_posted": item.get("datePosted", "Reciente")[:10],
                                    "source": "Indeed"
                                })
                    except Exception:
                        continue

                if parsed:
                    print(f"[Indeed] {len(parsed)} ofertas extraídas via JSON-LD para {api_loc}")

            jobs.extend(parsed)

        print(f"[Indeed] Total: {len(jobs)} ofertas")
        return jobs
