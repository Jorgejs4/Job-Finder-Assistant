import re
import json
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

    def _extract_jsonld(self, soup: BeautifulSoup, fallback_location: str = "") -> List[Dict]:
        """Extrae ofertas desde JSON-LD embebido (método más fiable)."""
        jobs = []
        scripts = soup.find_all("script", type="application/ld+json")
        for script in scripts:
            try:
                data = json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") == "JobPosting":
                        link = item.get("url", "")
                        if not link:
                            continue
                        loc_obj = item.get("jobLocation", {})
                        if isinstance(loc_obj, list):
                            loc_obj = loc_obj[0] if loc_obj else {}
                        location = loc_obj.get("address", {}).get("addressLocality", fallback_location)
                        company_obj = item.get("hiringOrganization", {})
                        company = company_obj.get("name", "No especificada") if isinstance(company_obj, dict) else str(company_obj)
                        jobs.append({
                            "title": item.get("title", "No especificado"),
                            "company": company,
                            "location": location,
                            "link": link,
                            "description": item.get("description", ""),
                            "date_posted": str(item.get("datePosted", "Reciente"))[:10],
                            "source": "Indeed"
                        })
            except Exception:
                continue
        return jobs

    def _parse_job_card(self, card) -> dict:
        """Parsea una tarjeta de empleo de Indeed con múltiples fallbacks."""
        # Título + enlace: probar múltiples selectores del HTML actual
        a_tag = None
        title = ""

        # Selector primario: buscar cualquier <a> con href que contenga /jobs? o/viewjob
        for selector in [
            "a[data-jk]",
            "a[id^='job_']",
            "h2.jobTitle a",
            "h2 a[href*='/jobs']",
            "a[href*='/jobs?']",
            "a[href*='viewjob']",
        ]:
            a_tag = card.select_one(selector)
            if a_tag:
                break

        if not a_tag:
            # Último recurso: primer <a> con href que parezca un enlace de empleo
            for a in card.find_all("a", href=True):
                href = a["href"]
                if "/jobs?" in href or "viewjob" in href or "/rc/clk" in href:
                    a_tag = a
                    break

        if not a_tag:
            return None

        # El título puede estar en h2 dentro de la card, o en el propio <a>
        h2 = card.find("h2")
        if h2:
            title = h2.get_text(strip=True)
        if not title:
            title = a_tag.get_text(strip=True)
        if not title or len(title) < 3:
            return None

        href = a_tag.get("href", "")
        if href.startswith("/"):
            link = "https://es.indeed.com" + href
        elif href.startswith("http"):
            link = href
        else:
            return None

        # Empresa: múltiples selectores ( Indeed post-fusión usa data-testid o clases)
        company = "No especificada"
        for sel in [
            {"data-testid": "company-name"},
            {"class_": "companyName"},
            {"class_": "company"},
            {"class_": re.compile(r"company")},
        ]:
            tag = card.find("span", sel) if isinstance(sel, dict) and "class_" in sel else card.find("span", sel) if isinstance(sel, dict) else None
            if tag is None and isinstance(sel, dict):
                tag = card.find("span", sel)
            if tag:
                company = tag.get_text(strip=True)
                if company:
                    break

        # Ubicación
        location = ""
        for sel in [
            {"data-testid": "text-location"},
            {"class_": "companyLocation"},
            {"class_": re.compile(r"location")},
        ]:
            if isinstance(sel, dict):
                tag = card.find("div", sel)
                if tag:
                    location = tag.get_text(strip=True)
                    if location:
                        break

        # Descripción
        description = ""
        for sel in [
            {"class_": "job-snippet"},
            {"class_": re.compile(r"snippet")},
            {"class_": re.compile(r"jobCard")},
        ]:
            if isinstance(sel, dict):
                tag = card.find(["div", "table", "span"], sel)
                if tag:
                    description = tag.get_text(strip=True)
                    if description:
                        break

        return {
            "title": title,
            "company": company or "No especificada",
            "location": location,
            "link": link,
            "description": description,
            "date_posted": "Reciente",
            "source": "Indeed"
        }

    def scrape_jobs(self, search_query: str, locations: List[str]) -> List[Dict[str, Any]]:
        """Scraper para Indeed España. Usa curl_cffi para evadir Cloudflare."""
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

            # Método 1: JSON-LD (más fiable — Indeed siempre lo embebe)
            parsed = self._extract_jsonld(soup, api_loc)
            if parsed:
                print(f"[Indeed] {len(parsed)} ofertas extraídas via JSON-LD para {api_loc}")
                jobs.extend(parsed)
                continue

            # Método 2: Tarjetas HTML con selectores actualizados
            cards = []
            for selector in [
                "div.job_seen_beacon",
                "div.jobsearch-ResultsList > div",
                "div.mosaic-provider-jobcards > div",
                "td.resultContent",
                "div[data-testid='job-card']",
                "div.jobCard",
            ]:
                cards = soup.select(selector)
                if cards:
                    break

            if not cards:
                cards = soup.find_all("div", class_=re.compile(r"job|result", re.I))

            parsed = []
            for card in cards:
                result = self._parse_job_card(card)
                if result and result["link"]:
                    parsed.append(result)

            if parsed:
                print(f"[Indeed] {len(parsed)} ofertas encontradas via HTML para {api_loc}")
            else:
                print(f"[Indeed] 0 ofertas para {api_loc}")

            jobs.extend(parsed)

        print(f"[Indeed] Total: {len(jobs)} ofertas")
        return jobs
