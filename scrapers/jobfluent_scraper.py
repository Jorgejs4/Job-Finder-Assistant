import re
from typing import List, Dict, Any
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper


class JobfluentScraper(BaseScraper):
    """
    Scraper de Jobfluent.com — portal tech-oriented.
    """
    MAX_RESULTS = 50

    def _fetch(self, url: str, params: dict = None) -> str:
        try:
            from curl_cffi import requests as cffi_requests
            resp = cffi_requests.get(url, params=params, impersonate="chrome131", timeout=20)
            if resp.status_code == 200:
                return resp.text
            print(f"[Jobfluent] curl_cffi status {resp.status_code}")
        except ImportError:
            print("[Jobfluent] curl_cffi no disponible")
        except Exception as e:
            print(f"[Jobfluent] Error curl_cffi: {e}")
        return ""

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

        cards = soup.select("div.job-card, div.offer-item, article.job")
        if not cards:
            cards = soup.find_all("div", class_=re.compile(r"job|offer", re.I))
        if not cards:
            cards = soup.find_all("a", href=re.compile(r"/jobs/"))

        seen = set()
        for card in cards[:self.MAX_RESULTS]:
            try:
                if card.name == "a":
                    a_tag = card
                    card = card.find_parent("div") or card
                else:
                    a_tag = card.find("a", href=True)
                    if not a_tag:
                        continue

                href = a_tag["href"]
                if href.startswith("/"):
                    href = "https://jobfluent.com" + href
                if href in seen:
                    continue
                seen.add(href)

                title = ""
                for sel in ["h2", "h3", ".job-title", ".title"]:
                    t = card.select_one(sel)
                    if t:
                        title = t.get_text(strip=True)
                        break
                if not title:
                    title = a_tag.get_text(strip=True)[:100]

                company = ""
                for sel in [".company", ".employer", ".company-name"]:
                    c = card.select_one(sel)
                    if c:
                        company = c.get_text(strip=True)
                        break

                loc_tag = card.select_one(".location, .job-location")
                location = loc_tag.get_text(strip=True) if loc_tag else "España"

                desc_tag = card.select_one(".description, .snippet, .job-description")
                desc = desc_tag.get_text(strip=True) if desc_tag else title

                jobs.append({
                    "title": title,
                    "company": company or "No especificada",
                    "location": location,
                    "link": href,
                    "description": desc,
                    "date_posted": "Reciente",
                    "source": "Jobfluent"
                })
            except Exception:
                continue

        print(f"[Jobfluent] {len(jobs)} ofertas encontradas.")
        return jobs
