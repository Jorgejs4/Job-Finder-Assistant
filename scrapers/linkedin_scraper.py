import re
from typing import List, Dict, Any
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper
import config


class LinkedInScraper(BaseScraper):
    def scrape_jobs(self, search_query: str, locations: List[str]) -> List[Dict[str, Any]]:
        """
        Scrapea ofertas de LinkedIn usando su API pública guest.
        NO fetchea la descripción individual (lento y propenso a 429).
        """
        print(f"[LinkedIn] Buscando ofertas para '{search_query}'...")
        jobs = []

        search_locations = locations if locations else ["Spain"]

        for loc in search_locations:
            api_loc = config.get_location_for("linkedin", loc)
            print(f"[LinkedIn] Buscando en: {api_loc}")

            url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
            params = {
                "keywords": search_query,
                "location": api_loc,
                "start": 0
            }

            html = self.get_html(url, params=params)
            if not html:
                continue

            soup = BeautifulSoup(html, "html.parser")
            cards = soup.find_all("li")

            print(f"[LinkedIn] {len(cards)} tarjetas brutas en {api_loc}")

            count = 0
            for card in cards:
                if count >= 5:
                    break

                try:
                    link_tag = card.find("a", class_=re.compile("base-card__full-link|job-search-card"))
                    if not link_tag or not link_tag.get("href"):
                        continue
                    link = link_tag["href"].split("?")[0]

                    title_tag = card.find("h3", class_=re.compile("base-search-card__title|job-search-card__title"))
                    title = title_tag.text.strip() if title_tag else "No especificado"

                    company_tag = card.find("h4", class_=re.compile("base-search-card__subtitle|job-search-card__subtitle"))
                    company = company_tag.text.strip() if company_tag else "No especificada"

                    loc_tag = card.find("span", class_=re.compile("job-search-card__location"))
                    location = loc_tag.text.strip() if loc_tag else api_loc

                    date_tag = card.find("time", class_=re.compile("job-search-card__listdate"))
                    date_posted = date_tag.get("datetime") if date_tag else "Reciente"

                    jobs.append({
                        "title": title,
                        "company": company,
                        "location": location,
                        "link": link,
                        "description": f"{title} en {company}",
                        "date_posted": date_posted,
                        "source": "LinkedIn"
                    })
                    count += 1

                except Exception as e:
                    print(f"[LinkedIn] Error tarjeta: {e}")
                    continue

        print(f"[LinkedIn] Total: {len(jobs)} ofertas")
        return jobs
