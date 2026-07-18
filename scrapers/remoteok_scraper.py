import re
import json
from typing import List, Dict, Any
import httpx
from scrapers.base_scraper import BaseScraper
import config


class RemoteOKScraper(BaseScraper):
    """
    Scraper de RemoteOK usando su API JSON pública.
    Excelente fuente de empleo remoto en tech.
    """
    def scrape_jobs(self, search_query: str, locations: List[str]) -> List[Dict[str, Any]]:
        print(f"[RemoteOK] Buscando ofertas para '{search_query}'...")
        jobs = []

        search_locations = locations if locations else ["remoto"]

        is_remote_search = any(loc.lower() in ("remoto", "remote") for loc in search_locations)
        if not is_remote_search:
            print("[RemoteOK] Solo ofrece empleo remoto. Saltando.")
            return []

        try:
            response = self.client.get("https://remoteok.com/api")
            if response.status_code != 200:
                print(f"[RemoteOK] Error en API ({response.status_code})")
                return []

            all_jobs = response.json()
            # El primer elemento suele ser metadata
            all_jobs = [j for j in all_jobs if j.get("position")]

            keywords = search_query.lower().split()
            for item in all_jobs:
                title = item.get("position", "")
                company = item.get("company", "")
                tags = [t.lower() for t in item.get("tags", [])]
                desc = item.get("description", "")
                title_lower = title.lower()
                desc_lower = desc.lower()
                tags_str = " ".join(tags)

                # Filtrar por relevancia
                if not any(kw in title_lower or kw in tags_str or kw in desc_lower for kw in keywords):
                    continue

                link = item.get("url", "")
                if not link:
                    slug = item.get("slug", "")
                    link = f"https://remoteok.com/remote-jobs/{slug}" if slug else ""

                location = item.get("location", "Remote")
                if not location or location.strip() == "":
                    location = "Remote"

                date_posted = item.get("date", "")[:10] if item.get("date") else "Reciente"

                jobs.append({
                    "title": title,
                    "company": company if company else "No especificada",
                    "location": location,
                    "link": link,
                    "description": desc,
                    "date_posted": date_posted,
                    "source": "RemoteOK"
                })

            print(f"[RemoteOK] {len(jobs)} ofertas relevantes encontradas.")

        except Exception as e:
            print(f"[RemoteOK] Error: {e}")

        return jobs
