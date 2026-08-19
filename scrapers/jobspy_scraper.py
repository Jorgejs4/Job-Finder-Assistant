"""Adapter for the JobSpy multi-board scraper library."""

from typing import Any, Dict, List

from scrapers.base_scraper import BaseScraper
import config


class JobSpyScraper(BaseScraper):
    """Scrapes extra job boards and converts them to the app's common schema."""

    def scrape_jobs(self, search_query: str, locations: List[str]) -> List[Dict[str, Any]]:
        try:
            from jobspy import scrape_jobs
        except ImportError as exc:
            raise RuntimeError(
                "JobSpy no está instalado. Ejecuta: pip install python-jobspy"
            ) from exc

        sites = [s.strip() for s in config.JOBSPY_SITES.split(",") if s.strip()]
        search_locations = locations or ["Spain"]
        jobs: List[Dict[str, Any]] = []

        for location in search_locations:
            # JobSpy accepts a single location per call. Remote is represented by
            # the search flag; Spain keeps results useful for local/hybrid roles.
            is_remote = location.lower() in {"remoto", "remote"}
            # Use the same country-aware location mapping as the legacy scrapers
            # (e.g. ``sevilla`` -> ``Sevilla, España`` for Indeed).
            location_value = (
                "Spain" if is_remote
                else config.get_location_for("indeed", location)
            )
            kwargs = {
                "site_name": sites,
                "search_term": search_query,
                "location": location_value,
                "results_wanted": config.MAX_JOBS_PER_SCRAPER,
                # Indeed does not allow hours_old together with is_remote.
                "hours_old": None if is_remote else config.JOBSPY_HOURS_OLD,
                "country_indeed": config.JOBSPY_COUNTRY_INDEED,
                "is_remote": is_remote,
                "verbose": 0,
            }
            if "google" in sites:
                kwargs["google_search_term"] = f"{search_query} jobs near {location_value}"

            try:
                frame = scrape_jobs(**kwargs)
            except Exception as exc:
                print(f"[JobSpy] Error en {location_value}: {exc}")
                continue

            for _, row in frame.fillna("").iterrows():
                link = str(row.get("job_url", "")).strip()
                title = str(row.get("title", "")).strip()
                if not link or not title:
                    continue
                date_posted = row.get("date_posted", "")
                if hasattr(date_posted, "strftime"):
                    date_posted = date_posted.strftime("%Y-%m-%d")
                date_posted = str(date_posted).strip() or "Reciente"
                source = str(row.get("site", "JobSpy")).strip() or "JobSpy"
                jobs.append({
                    "title": title,
                    "company": str(row.get("company", "No especificada")).strip() or "No especificada",
                    "location": str(row.get("location", location_value)).strip() or location_value,
                    "link": link,
                    "description": str(row.get("description", title)).strip() or title,
                    "date_posted": date_posted,
                    "source": f"JobSpy/{source}",
                    "is_remote": bool(row.get("is_remote", False)),
                    "salary_raw": str(row.get("min_amount", "")).strip(),
                })

        # Job boards can return the same posting across several providers.
        unique: Dict[str, Dict[str, Any]] = {}
        for job in jobs:
            unique.setdefault(job["link"], job)
        result = list(unique.values())
        print(f"[JobSpy] {len(result)} ofertas únicas encontradas para '{search_query}'")
        return result
