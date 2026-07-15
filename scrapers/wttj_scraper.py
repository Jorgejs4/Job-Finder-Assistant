import re
import json
from typing import List, Dict, Any
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper


class WelcomeToTheJungleScraper(BaseScraper):
    """
    Scraper de Glassdoor — reemplaza WTTJ que ahora requiere auth.
    Usa curl_cffi y fallback a HTML scraping.
    NOTA: Glassdoor es agresivo con anti-bot, puede fallar en CI.
    """
    MAX_RESULTS = 50

    def _fetch(self, url: str, params: dict = None) -> str:
        try:
            from curl_cffi import requests as cffi_requests
            headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            }
            resp = cffi_requests.get(
                url, params=params, headers=headers,
                impersonate="chrome131", timeout=20
            )
            if resp.status_code == 200:
                return resp.text
            print(f"[Glassdoor] curl_cffi status {resp.status_code}")
        except ImportError:
            print("[Glassdoor] curl_cffi no disponible")
        except Exception as e:
            print(f"[Glassdoor] Error curl_cffi: {e}")
        return ""

    def scrape_jobs(self, search_query: str, locations: List[str]) -> List[Dict[str, Any]]:
        print(f"[Glassdoor] Buscando ofertas para '{search_query}'...")
        jobs = []
        encoded = search_query.replace(" ", "-").lower()

        url = f"https://www.glassdoor.es/Empleo/{encoded}-empleos-SRCH_KO0,{len(search_query)}.htm"
        html = self._fetch(url)

        if not html:
            html = self.get_html(url)

        if not html:
            print("[Glassdoor] No se pudo obtener HTML")
            return []

        soup = BeautifulSoup(html, "html.parser")

        # Intentar extraer de JSON-LD
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") == "JobPosting":
                        link = item.get("url", "")
                        jobs.append({
                            "title": item.get("title", "No especificado"),
                            "company": item.get("hiringOrganization", {}).get("name", "No especificada"),
                            "location": item.get("jobLocation", {}).get("address", {}).get("addressLocality", "España"),
                            "link": link,
                            "description": item.get("description", "")[:2000],
                            "date_posted": item.get("datePosted", "Reciente")[:10],
                            "source": "Glassdoor"
                        })
            except Exception:
                continue

        if jobs:
            print(f"[Glassdoor] {len(jobs)} ofertas extraídas via JSON-LD.")
            return jobs[:self.MAX_RESULTS]

        # Fallback: cards HTML
        cards = soup.select("[data-test='jobListing'], .jobCard, li.JobsList_jobListItem__wjTHv")
        if not cards:
            cards = soup.find_all("div", class_=re.compile(r"job|listing", re.I))

        seen = set()
        for card in cards[:self.MAX_RESULTS]:
            try:
                a_tag = card.find("a", href=True)
                if not a_tag:
                    continue

                href = a_tag["href"]
                if href.startswith("/"):
                    href = "https://www.glassdoor.es" + href
                if href in seen:
                    continue
                seen.add(href)

                title = ""
                for sel in ["h2", "h3", ".jobTitle", "[data-test='job-title']"]:
                    t = card.select_one(sel)
                    if t:
                        title = t.get_text(strip=True)
                        break
                if not title:
                    title = a_tag.get_text(strip=True)[:100]

                company = ""
                for sel in [".employerName", ".companyName", "[data-test='employer-short-name']"]:
                    c = card.select_one(sel)
                    if c:
                        company = c.get_text(strip=True)
                        break

                loc_tag = card.select_one("[data-test='emp-location'], .location")
                location = loc_tag.get_text(strip=True) if loc_tag else "España"

                desc_tag = card.select_one(".jobDescription, .description")
                desc = desc_tag.get_text(strip=True) if desc_tag else title

                jobs.append({
                    "title": title,
                    "company": company or "No especificada",
                    "location": location,
                    "link": href,
                    "description": desc,
                    "date_posted": "Reciente",
                    "source": "Glassdoor"
                })
            except Exception:
                continue

        print(f"[Glassdoor] {len(jobs)} ofertas encontradas.")
        return jobs
