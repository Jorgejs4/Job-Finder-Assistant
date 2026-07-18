import re
from typing import List, Dict, Any
import httpx
from scrapers.base_scraper import BaseScraper
import config


class RemotiveScraper(BaseScraper):
    """
    Scraper de Remotive.io usando su API JSON pública.
    Ofertas de empleo remoto en tech.
    """
    def scrape_jobs(self, search_query: str, locations: List[str]) -> List[Dict[str, Any]]:
        print(f"[Remotive] Buscando ofertas para '{search_query}'...")
        jobs = []

        search_locations = locations if locations else ["remoto"]
        is_remote_search = any(loc.lower() in ("remoto", "remote") for loc in search_locations)

        if not is_remote_search:
            print("[Remotive] Solo ofrece empleo remoto. Saltando.")
            return []

        try:
            params = {
                "category": "software-dev",
                "search": search_query,
                "limit": "50"
            }
            response = self.client.get("https://remotive.com/api/remote-jobs", params=params)
            if response.status_code != 200:
                print(f"[Remotive] Error en API ({response.status_code})")
                return []

            data = response.json()
            all_jobs = data.get("jobs", [])

            keywords = search_query.lower().split()
            for item in all_jobs:
                title = item.get("title", "")
                company = item.get("company_name", "")
                desc = item.get("description", "")
                title_lower = title.lower()
                desc_lower = desc.lower()

                if not any(kw in title_lower or kw in desc_lower for kw in keywords):
                    continue

                link = item.get("url", "")
                required_location = item.get("candidate_required_location", "Worldwide")

                date_posted = item.get("publication_date", "")[:10]
                if not date_posted:
                    date_posted = "Reciente"

                jobs.append({
                    "title": title,
                    "company": company if company else "No especificada",
                    "location": required_location if required_location else "Remote",
                    "link": link,
                    "description": desc,
                    "date_posted": date_posted,
                    "source": "Remotive"
                })

            print(f"[Remotive] {len(jobs)} ofertas relevantes encontradas.")

        except Exception as e:
            print(f"[Remotive] Error: {e}")

        return jobs
