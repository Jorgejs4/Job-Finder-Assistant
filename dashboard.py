#!/usr/bin/env python3
"""
Dashboard interactivo — Panel de gestión de ofertas de empleo.
Ejecutar con: streamlit run dashboard.py
"""
import os
import sys
import hashlib
import time
import unicodedata
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import json
import httpx
import statistics
from datetime import datetime, timedelta
from utils.feedback_manager import FeedbackManager
import config
from notion_sync import NotionSync

st.set_page_config(
    page_title="Job Scraper Dashboard",
    page_icon="🔍",
    layout="wide",
)

RESULTS_DIR = os.path.join(Path(__file__).resolve().parent, "results")


def _generate_ics_content(event_title: str, description: str, link: str,
                          start: datetime, end: datetime, alarms: list = None) -> str:
    alarms_str = ""
    for trigger, text in (alarms or []):
        alarms_str += f"""BEGIN:VALARM
TRIGGER:{trigger}
ACTION:DISPLAY
DESCRIPTION:{text}
END:VALARM
"""
    return f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//JobScraperAI//Dashboard//ES
BEGIN:VEVENT
DTSTART:{start.strftime('%Y%m%dT%H%M%S')}
DTEND:{end.strftime('%Y%m%dT%H%M%S')}
SUMMARY:{event_title}
DESCRIPTION:{description}
URL:{link}
{alarms_str}END:VEVENT
END:VCALENDAR"""


def google_calendar_url(title: str, company: str, link: str, event_datetime: datetime) -> str:
    """Genera URL para crear evento en Google Calendar."""
    from urllib.parse import quote
    event_title = f"Entrevista: {title} @ {company}"
    description = f"Preparar: revisar empresa, practicar preguntas técnicas.\nOferta: {link}"
    end = event_datetime + timedelta(hours=1)
    dates = f"{event_datetime.strftime('%Y%m%dT%H%M%S')}/{end.strftime('%Y%m%dT%H%M%S')}"
    params = f"action=TEMPLATE&text={quote(event_title)}&details={quote(description)}&dates={dates}"
    return f"https://calendar.google.com/calendar/render?{params}"


def ics_followup_content(title: str, company: str, link: str, days: int) -> tuple:
    event_title = f"Follow-up: {title} @ {company}"
    start = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    end = start + timedelta(minutes=15)
    content = _generate_ics_content(
        event_title,
        f"Oferta aplicada hace {days} dias.\\nVer oferta: {link}",
        link, start, end,
        [("-PT0M", f"Follow-up pendiente: {title} @ {company}")]
    )
    filename = f"followup_{company[:20].replace(' ', '_')}_{start.strftime('%Y%m%d')}.ics"
    return content.encode("utf-8"), filename


@st.cache_data(ttl=300, show_spinner=False)
def load_data():
    data_path = os.path.join(RESULTS_DIR, "data.json")
    if os.path.exists(data_path):
        with open(data_path, "r", encoding="utf-8") as f:
            return json.load(f)
    github_repo = config.GITHUB_REPO
    url = f"https://api.github.com/repos/{github_repo}/contents/results/data.json"
    try:
        resp = httpx.get(url, timeout=10, follow_redirects=True)
        if resp.status_code == 200:
            import base64
            content = base64.b64decode(resp.json()["content"])
            return json.loads(content)
    except Exception:
        pass
    return {"runs": []}


def _recalc_archive_reason(job):
    match = job.get("match_score", 0)
    work_mode = config.normalize_work_mode(job.get("work_mode", "Presencial"))
    location = job.get("location", "")
    target_city = getattr(config, "USER_CITY", "")
    if match < config.MIN_MATCH_TO_ARCHIVE:
        return config.ArchiveReason.low_match(match)
    if target_city and work_mode in ("Presencial", "Híbrido"):
        if target_city.lower() not in location.lower():
            return config.ArchiveReason.location_mismatch(work_mode, location)
    return None


@st.cache_data(ttl=300, show_spinner=False)
def aggregate_all_jobs(runs):
    """Agrega todas las ofertas de todas las ejecuciones, deduplicando por URL y titulo+empresa."""
    jobs_by_url = {}
    for run in runs:
        run_id = run.get("run_id", "")
        run_ts = run.get("timestamp", "")
        for job in run.get("jobs", []):
            url = job.get("link", "")
            if not url:
                continue
            if url in jobs_by_url:
                existing = jobs_by_url[url]
                if run_ts > existing.get("_last_seen", ""):
                    existing["_last_seen"] = run_ts
                    existing["_last_run_id"] = run_id
                if run_ts < existing.get("_first_seen", ""):
                    existing["_first_seen"] = run_ts
                for key in ["cover_letter", "custom_cv_url", "custom_cv_html",
                            "cover_letter_pdf_url", "language", "interview_prep",
                            "match_score", "tech_stack", "tailored_advice",
                            "salary", "work_mode", "salary_is_estimate",
                            "required_experience", "status",
                            "company_profile", "project_match"]:
                    if job.get(key):
                        existing[key] = job[key]
            else:
                job["_first_seen"] = run_ts
                job["_last_seen"] = run_ts
                job["_last_run_id"] = run_id
                jobs_by_url[url] = job

    for job in jobs_by_url.values():
        has_match = job.get("match_score") is not None
        if not has_match:
            job["needs_analysis"] = True
            job["archived"] = False
            job.pop("archive_reason", None)
            continue
        job.pop("needs_analysis", None)
        if job.get("work_mode"):
            job["work_mode"] = config.normalize_work_mode(job["work_mode"])
        match = job.get("match_score") or 0
        wm = job.get("work_mode", "Presencial")
        loc = job.get("location", "")
        tc = getattr(config, "USER_CITY", "")
        should_archive = False
        reason = None
        if match < config.MIN_MATCH_TO_ARCHIVE:
            should_archive = True
            reason = config.ArchiveReason.low_match(match)
        elif tc and wm in ("Presencial", "Híbrido"):
            if tc.lower() not in loc.lower():
                should_archive = True
                reason = config.ArchiveReason.location_mismatch(wm, loc)
        if should_archive:
            job["archived"] = True
            job["archive_reason"] = reason
        else:
            job["archived"] = False
            job.pop("archive_reason", None)

    all_jobs = list(jobs_by_url.values())
    if not all_jobs:
        return all_jobs

    def normalize(text):
        text = text.lower().strip()
        text = unicodedata.normalize("NFKD", text)
        text = "".join(c for c in text if not unicodedata.combining(c))
        text = text.replace("sr.", "").replace("sr", "").replace("jr.", "").replace("jr", "")
        text = text.replace("-", " ").replace("_", " ")
        return " ".join(text.split())

    title_company = {}
    for j in all_jobs:
        key = (normalize(j.get("title", "")), normalize(j.get("company", "")))
        if key not in title_company:
            title_company[key] = []
        title_company[key].append(j)

    deduped = []
    for key, group in title_company.items():
        if len(group) == 1:
            deduped.append(group[0])
        else:
            best = max(group, key=lambda j: j.get("match_score", 0))
            sources = [j.get("source", "") for j in group if j.get("source")]
            if sources:
                best["_also_on"] = ", ".join(set(sources))
            if best.get("archived"):
                reason = _recalc_archive_reason(best)
                if reason:
                    best["archive_reason"] = reason
                else:
                    best["archived"] = False
                    best["archive_reason"] = ""
            deduped.append(best)

    return deduped


def sync_statuses_from_notion(data: dict) -> bool:
    """Sincroniza estados y archivado de Notion -> data.json."""
    try:
        notion = NotionSync()
        notion_statuses = notion.get_all_statuses()
        notion_archived = notion.get_all_archived()
    except Exception as e:
        print(f"[Sync] Error conectando con Notion: {e}")
        return False

    updated = False
    for run in data.get("runs", []):
        for job in run.get("jobs", []):
            url = job.get("link", "")
            if url in notion_statuses:
                old_status = job.get("status", "Nuevo")
                new_status = notion_statuses[url]
                if old_status != new_status:
                    job["status"] = new_status
                    updated = True
            if url in notion_archived:
                old_archived = job.get("archived", False)
                new_archived = notion_archived[url]
                if old_archived != new_archived:
                    job["archived"] = new_archived
                    updated = True

    if updated:
        data_path = os.path.join(RESULTS_DIR, "data.json")
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        load_data.clear()
        aggregate_all_jobs.clear()
        print(f"[Sync] Estados y archivado sincronizados desde Notion")
    return updated


def extract_filter_options(all_jobs):
    """Extrae todas las opciones de filtros en una sola pasada sobre all_jobs."""
    sources = set()
    modes = set()
    statuses_present = set()
    salaries = []
    techs = defaultdict(int)
    experiences = set()
    locations = set()

    for j in all_jobs:
        src = j.get("source", "N/A")
        if src:
            sources.add(src)

        wm = j.get("work_mode", "")
        if wm and wm != "N/A":
            modes.add(config.normalize_work_mode(wm))

        st_val = j.get("status", "Nuevo")
        if st_val:
            statuses_present.add(st_val)

        s = parse_salary(j.get("salary"))
        if s:
            salaries.append(s)

        for t in j.get("tech_stack", []):
            techs[t] += 1

        exp = j.get("required_experience")
        if exp:
            experiences.add(exp)

        loc = j.get("location", "").strip()
        if loc:
            locations.add(loc)

    return {
        "sources": sorted(sources),
        "modes": sorted(modes),
        "statuses_present": statuses_present,
        "salaries": salaries,
        "techs": techs,
        "experiences": experiences,
        "locations": sorted(locations),
    }


def save_job_status(data: dict, link: str, new_status: str) -> bool:
    """Guarda el cambio de estado de una oferta en data.json."""
    updated = False
    for run in data.get("runs", []):
        for job in run.get("jobs", []):
            if job.get("link") == link:
                if job.get("status") != new_status:
                    job["status"] = new_status
                    updated = True
    if updated:
        data_path = os.path.join(RESULTS_DIR, "data.json")
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return updated


def save_job_archived(data: dict, link: str, archived: bool, reason: str | None = None) -> bool:
    """Marca/desmarca una oferta como archivada en data.json."""
    updated = False
    for run in data.get("runs", []):
        for job in run.get("jobs", []):
            if job.get("link") == link:
                job["archived"] = archived
                if archived and reason:
                    job["archive_reason"] = reason
                elif not archived:
                    job.pop("archive_reason", None)
                updated = True
    if updated:
        data_path = os.path.join(RESULTS_DIR, "data.json")
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return updated


def save_job_analysis(data: dict, link: str, updates: dict) -> bool:
    """Guarda los resultados del análisis de Gemini en data.json."""
    updated = False
    for run in data.get("runs", []):
        for job in run.get("jobs", []):
            if job.get("link") == link:
                job.update(updates)
                job.pop("needs_analysis", None)
                updated = True
    if updated:
        data_path = os.path.join(RESULTS_DIR, "data.json")
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return updated


def reanalyze_jobs_with_gemini(jobs_list: list) -> tuple:
    """Reanaliza ofertas sin analizar usando Gemini. Devuelve (analyzed, errors)."""
    from utils.gemini_client import GeminiClient
    from utils.cv_parser import parse_cv

    config.validate_config()
    gemini = GeminiClient()
    cv_text = parse_cv(config.CV_PATH)

    total = len(jobs_list)
    progress_bar = st.progress(0)
    status_text = st.empty()
    log_container = st.container()
    log_lines = []
    analyzed = 0
    errors = 0

    for i, job in enumerate(jobs_list):
        title = job.get("title", "?")[:50]
        company = job.get("company", "")[:30]
        status_text.text(f"[{i+1}/{total}] Analizando: {title} @ {company}...")
        try:
            language = config.detect_language(
                job.get("source", ""), job.get("title", ""),
                job.get("description", "") or job.get("title", "")
            )
            desc = job.get("description", "") or job.get("title", "")

            match_result = gemini.match_offer(
                cv_text=cv_text,
                offer_title=job["title"],
                offer_description=desc,
                experience_hint=0,
                language=language,
            )
            time.sleep(2)

            details = gemini.match_details(
                cv_text=cv_text,
                offer_title=job["title"],
                offer_description=desc,
                match_result=match_result,
                language=language,
            )
            time.sleep(2)

            wm = config.normalize_work_mode(match_result.work_mode)
            match_pct = match_result.match_score
            salary = details.estimated_salary
            exp = details.required_experience

            log_lines.append(
                f"✅ **{title}** @ {company} — "
                f"🎯 {match_pct}% | 📍 {wm} | 💰 {salary}€ | 👔 {exp} años"
            )
            with log_container:
                st.markdown("\n".join(log_lines))

            updates = {
                "match_score": match_result.match_score,
                "tech_stack": match_result.tech_stack,
                "work_mode": wm,
                "language": language,
                "salary": str(details.estimated_salary),
                "salary_is_estimate": details.salary_is_estimate,
                "required_experience": details.required_experience,
                "tailored_advice": details.tailored_advice,
            }
            save_job_analysis(data, job["link"], updates)
            job.update(updates)
            analyzed += 1
        except Exception as e:
            errors += 1
            log_lines.append(f"❌ **{title}** @ {company} — Error: {e}")
            with log_container:
                st.markdown("\n".join(log_lines))

        progress_bar.progress((i + 1) / total)

    status_text.success(f"Completado: {analyzed} analizadas, {errors} errores")
    return analyzed, errors


def parse_salary(val):
    if not val:
        return None
    try:
        return int(str(val).replace(".", "").replace(",", ""))
    except (ValueError, TypeError):
        return None


data = load_data()
runs = data.get("runs", [])
all_jobs = aggregate_all_jobs(runs)
feedback_mgr = FeedbackManager()

if config.NOTION_TOKEN and config.NOTION_DATABASE_ID:
    if "last_notion_sync" not in st.session_state:
        st.session_state.last_notion_sync = 0
    if time.time() - st.session_state.last_notion_sync > 300:
        synced = sync_statuses_from_notion(data)
        st.session_state.last_notion_sync = time.time()
        if synced:
            runs = data.get("runs", [])
            all_jobs = aggregate_all_jobs(runs)

st.title("🔍 Job Scraper Dashboard")
st.caption(f"{len(all_jobs)} ofertas de {len(runs)} ejecuciones | Última carga: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

if not runs:
    st.warning("No hay ejecuciones registradas. Ejecuta `python main.py` primero.")
    st.stop()

latest = runs[0]

tab_mis_ofertas, tab_sin_analizar, tab_archivadas, tab_pipeline, tab_stats, tab_ejecuciones = st.tabs(
    ["💼 Mis Ofertas", "📋 Sin analizar", "📦 Ofertas archivadas", "🔄 Pipeline", "📊 Estadísticas", "📈 Ejecuciones"]
)

if config.USER_PORTFOLIO_URL or config.USER_CERTIFICATIONS or config.USER_GITHUB:
    with st.sidebar:
        st.subheader("📋 Mi Perfil")
        if config.USER_GITHUB:
            st.markdown(f"**GitHub:** [{config.USER_GITHUB}](https://github.com/{config.USER_GITHUB})")
        if config.USER_PORTFOLIO_URL:
            st.link_button("🌐 Portfolio", config.USER_PORTFOLIO_URL)
        if config.USER_CERTIFICATIONS:
            st.markdown("**Certificaciones:**")
            for cert in config.USER_CERTIFICATIONS.split(","):
                st.markdown(f"  📜 {cert.strip()}")

# ═══════════════════════════════════════════════════════════════
# TAB 1: MIS OFERTAS — Panel principal
# ═══════════════════════════════════════════════════════════════
with tab_mis_ofertas:
    if not all_jobs:
        st.info("No hay ofertas disponibles.")
        st.stop()

    st.subheader(f"💼 {len(all_jobs)} ofertas disponibles")

    with st.expander("🔍 Filtros avanzados", expanded=True):
        filter_opts = extract_filter_options(all_jobs)

        f1, f2, f3, f4 = st.columns(4)
        with f1:
            source_filter = st.multiselect("Fuente", filter_opts["sources"], default=filter_opts["sources"])
        with f2:
            mode_filter = st.multiselect("Modalidad", filter_opts["modes"], default=filter_opts["modes"])
        with f3:
            all_statuses = [s for s in config.APPLICATION_STATUSES if s in filter_opts["statuses_present"]]
            status_filter = st.multiselect("Estado", config.APPLICATION_STATUSES, default=all_statuses)
        with f4:
            min_score = st.slider("Match minimo (solo aplica a ofertas analizadas)", 0, 100, 0)

        f5, f6, f7, f8 = st.columns(4)
        with f5:
            sal_max = max(filter_opts["salaries"]) if filter_opts["salaries"] else config.MAX_SALARY_SLIDER
            sal_range = st.slider(
                "Rango salarial",
                min_value=0,
                max_value=max(config.MAX_SALARY_SLIDER, sal_max + 10000),
                value=(0, max(config.MAX_SALARY_SLIDER, sal_max + 10000)),
                step=1000,
            )
        with f6:
            top_techs = [t for t, _ in sorted(filter_opts["techs"].items(), key=lambda x: x[1], reverse=True)[:30]]
            tech_filter = st.multiselect("Tech stack", top_techs, default=[])
        with f7:
            exp_values = sorted(filter_opts["experiences"])
            max_exp = max(exp_values) if exp_values else 10
            exp_slider_max = max(max_exp, 10)
            exp_filter = st.slider("Experiencia max (anios)", 0, exp_slider_max, exp_slider_max)
        with f8:
            location_filter = st.multiselect("Ubicacion", filter_opts["locations"], default=[])

        sort_options = {
            "Match ↓": ("match_score", True),
            "Match ↑": ("match_score", False),
            "Salario ↓": ("salary_num", True),
            "Salario ↑": ("salary_num", False),
            "Experiencia ↓": ("required_experience", True),
            "Experiencia ↑": ("required_experience", False),
            "Recientes ↓": ("_last_seen", True),
            "Recientes ↑": ("_last_seen", False),
        }
        sort_by = st.selectbox("Ordenar por", list(sort_options.keys()), index=0)

        search_text = st.text_input("🔎 Buscar por título, empresa o ubicación", placeholder="Ej: Python, Sevilla, Remote...")

        with st.expander("⚙️ Filtros adicionales", expanded=False):
            salary_only_from_offer = st.checkbox("Solo ofertas con salario de la oferta", value=False)

    filtered = []
    for j in all_jobs:
        if j.get("archived"):
            continue
        if j.get("needs_analysis"):
            continue

        if source_filter and j.get("source", "N/A") not in source_filter:
            continue

        wm = j.get("work_mode", "")
        wm_norm = config.normalize_work_mode(wm)
        if wm_norm and wm_norm != "N/A" and mode_filter and wm_norm not in mode_filter:
            continue

        job_status = j.get("status", "Nuevo")
        if status_filter and job_status not in status_filter:
            continue

        match = j.get("match_score") or 0
        if match < min_score:
            continue

        exp = j.get("required_experience") or 0
        if exp > exp_filter:
            continue

        sal = parse_salary(j.get("salary"))
        if sal is not None and sal_range:
            if sal < sal_range[0] or sal > sal_range[1]:
                continue

        if salary_only_from_offer and j.get("salary_is_estimate", True):
            continue

        if tech_filter:
            job_techs = j.get("tech_stack", [])
            if not any(t in tech_filter for t in job_techs):
                continue

        if location_filter:
            jloc = j.get("location", "").strip()
            if not any(loc.lower() in jloc.lower() for loc in location_filter):
                continue

        if search_text.strip():
            q = search_text.lower()
            searchable = f"{j.get('title', '')} {j.get('company', '')} {j.get('location', '')}".lower()
            if q not in searchable:
                continue

        filtered.append(j)

    sort_key, sort_reverse = sort_options[sort_by]
    def sort_val(j):
        if sort_key == "salary_num":
            s = parse_salary(j.get("salary"))
            return s if s else (0 if sort_reverse else 999999999)
        return j.get(sort_key) or (0 if sort_reverse else "")
    filtered.sort(key=sort_val, reverse=sort_reverse)

    st.write(f"**{len(filtered)}** ofertas tras filtros")

    for j in filtered:
        title = j.get("title", "N/A")
        company = j.get("company", "N/A")
        match = j.get("match_score", 0)
        salary = j.get("salary", "")
        salary_is_est = j.get("salary_is_estimate", True)
        mode = config.normalize_work_mode(j.get("work_mode", "N/A"))
        status = j.get("status", "Nuevo")
        source = j.get("source", "N/A")
        exp = j.get("required_experience", 0)
        link = j.get("link", "")
        techs = j.get("tech_stack", [])
        advice = j.get("tailored_advice", "")
        cover_letter = j.get("cover_letter", "")
        cv_url = j.get("custom_cv_url", "")
        cv_html_file = j.get("custom_cv_html", "")
        cl_pdf_url = j.get("cover_letter_pdf_url", "")

        header_parts = [f"**{title}** @ {company}"]
        header_parts.append(f"🎯 {match}%")
        if salary:
            sal_label = f"{salary}€"
            if salary_is_est:
                sal_label += " ≈"
            header_parts.append(f"💰 {sal_label}")
        header_parts.append(f"📍 {mode}")
        source_display = f"🏢 {source}"
        also_on = j.get("_also_on", "")
        if also_on:
            other = [s for s in also_on.split(", ") if s != source]
            if other:
                source_display += f" (+{', '.join(other)})"
        header_parts.append(source_display)

        days_applied = 0
        if status == "Aplicado" and j.get("_first_seen"):
            try:
                first = datetime.fromisoformat(j["_first_seen"])
                days_applied = (datetime.now() - first).days
            except (ValueError, TypeError):
                pass

        if days_applied >= config.FOLLOWUP_REMINDER_DAYS:
            header_parts.append(f"[⏰ {status} — {days_applied}d]")
        else:
            header_parts.append(f"[{status}]")

        with st.expander(" | ".join(header_parts)):
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Match", f"{match}%")
            if salary:
                sal_display = f"{salary}€"
                sal_source = "Aproximación IA" if salary_is_est else "Oferta"
                m2.metric("Salario", sal_display, help=f"Fuente: {sal_source}")
                if salary_is_est:
                    st.caption("≈ Salario estimado por IA")
                else:
                    st.caption("✅ Salario de la oferta")
            else:
                m2.metric("Salario", "No especificado")
            m3.metric("Modalidad", mode)
            m4.metric("Experiencia", f"{exp} años" if exp else "Junior")
            m5.metric("Fuente", source)

            if j.get("location"):
                st.markdown(f"**Ubicación:** {j['location']}")

            _job_key = hashlib.md5(f"{title}{company}{link}".encode()).hexdigest()[:10]
            with st.form(key=f"status_{_job_key}", clear_on_submit=False):
                _sc1, _sc2 = st.columns([3, 1])
                with _sc1:
                    new_status = st.selectbox(
                        "Estado",
                        config.APPLICATION_STATUSES,
                        index=config.APPLICATION_STATUSES.index(status) if status in config.APPLICATION_STATUSES else 0,
                        key=f"st_{_job_key}",
                        label_visibility="collapsed",
                    )
                with _sc2:
                    if st.form_submit_button("Guardar", use_container_width=True):
                        if save_job_status(data, link, new_status):
                            load_data.clear()
                            aggregate_all_jobs.clear()
                            st.success("Guardado")
                            st.rerun()

            if not j.get("archived"):
                if st.button("Archivar oferta", key=f"arch_{_job_key}", use_container_width=True):
                    if save_job_archived(data, link, True, reason=config.ArchiveReason.MANUAL):
                        try:
                            NotionSync().update_job_eliminar(link, True)
                        except Exception:
                            pass
                        load_data.clear()
                        aggregate_all_jobs.clear()
                        st.rerun()

            if techs:
                st.markdown(f"**Stack:** {', '.join(techs)}")

            if link:
                st.link_button("🔗 Ver oferta original", link)

                st.markdown("**📅 Crear evento entrevista:**")
                _ic1, _ic2 = st.columns([1, 1])
                with _ic1:
                    interview_date = st.date_input(
                        "Fecha",
                        value=datetime.now().date() + timedelta(days=1),
                        key=f"int_date_{_job_key}",
                        label_visibility="collapsed",
                    )
                with _ic2:
                    interview_time = st.time_input(
                        "Hora",
                        value=datetime(2026, 1, 1, 10, 0).time(),
                        key=f"int_time_{_job_key}",
                        label_visibility="collapsed",
                    )
                interview_dt = datetime.combine(interview_date, interview_time)
                gcal_url = google_calendar_url(title, company, link, interview_dt)
                st.link_button("Abrir en Google Calendar", gcal_url, use_container_width=True)

            if advice:
                with st.expander("💡 Consejos personalizados"):
                    st.write(advice)

            if cover_letter:
                st.divider()
                st.subheader("📝 Carta de Presentación")
                st.markdown(cover_letter)
                if cl_pdf_url:
                    st.link_button("📥 Descargar Carta en PDF", cl_pdf_url)

            interview_prep = j.get("interview_prep")
            if interview_prep:
                st.divider()
                with st.expander("🎯 Preparación para Entrevista", expanded=False):
                    tech_qs = interview_prep.get("technical_questions", [])
                    beh_qs = interview_prep.get("behavioral_questions", [])
                    key_topics = interview_prep.get("key_topics", [])
                    tips = interview_prep.get("preparation_tips", [])

                    has_content = any([tech_qs, beh_qs, key_topics, tips])
                    if not has_content:
                        st.info("No hay contenido de preparación disponible.")

                    st.markdown("**Preguntas Técnicas:**")
                    if tech_qs:
                        for i, qa in enumerate(tech_qs, 1):
                            st.markdown(f"**{i}. {qa.get('question', '')}**")
                            st.markdown(f"→ {qa.get('answer', '')}")
                            st.markdown("")
                    else:
                        st.markdown("_No disponibles_")

                    st.markdown("**Preguntas Comportamentales (STAR):**")
                    if beh_qs:
                        for i, qa in enumerate(beh_qs, 1):
                            st.markdown(f"**{i}. {qa.get('question', '')}**")
                            st.markdown(f"→ {qa.get('answer', '')}")
                            st.markdown("")
                    else:
                        st.markdown("_No disponibles_")

                    st.markdown("**Temas Clave:**")
                    if key_topics:
                        st.markdown(", ".join(key_topics))
                    else:
                        st.markdown("_No disponibles_")

                    st.markdown("**Consejos:**")
                    if tips:
                        for tip in tips:
                            st.markdown(f"• {tip}")
                    else:
                        st.markdown("_No disponibles_")

            company_profile = j.get("company_profile")
            if company_profile:
                st.divider()
                with st.expander(f"🏢 Perfil de {company_profile.get('name', company)}", expanded=False):
                    cp = company_profile
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown(f"**Sector:** {cp.get('industry', 'N/A')}")
                        st.markdown(f"**Tamaño:** {cp.get('size', 'N/A')}")
                        st.markdown(f"**Salario:** {cp.get('salary_range', 'N/A')}")
                    with c2:
                        remote = "✅ Sí" if cp.get('remote_friendly') else "❌ No"
                        st.markdown(f"**Remoto:** {remote}")
                        techs = ", ".join(cp.get("tech_stack", [])[:8])
                        st.markdown(f"**Tech stack:** {techs}")

                    if cp.get("culture"):
                        st.markdown(f"**Cultura:** {cp['culture']}")

                    pros = cp.get("pros", [])
                    if pros:
                        st.markdown("**✅ Pros:**")
                        for p in pros:
                            st.markdown(f"  • {p}")

                    cons = cp.get("cons", [])
                    if cons:
                        st.markdown("**⚠️ A tener en cuenta:**")
                        for c in cons:
                            st.markdown(f"  • {c}")

                    rec = cp.get("recommendation", "")
                    if rec:
                        st.info(f"💡 {rec}")

            project_match = j.get("project_match")
            if project_match:
                st.divider()
                with st.expander("📁 Match de Proyectos Personales", expanded=False):
                    pm = project_match
                    st.metric("Relevancia de proyectos", f"{pm.get('project_relevance', 0)}%")

                    matching = pm.get("matching_projects", [])
                    if matching:
                        st.markdown("**Proyectos relevantes:**")
                        for mp in matching:
                            st.markdown(f"  ✅ {mp}")

                    missing = pm.get("missing_project_types", [])
                    if missing:
                        st.markdown("**Tipos de proyecto que te faltan:**")
                        for m in missing:
                            st.markdown(f"  📌 {m}")

                    advice = pm.get("project_advice", "")
                    if advice:
                        st.info(f"💡 {advice}")

            if cv_url:
                st.divider()
                st.subheader("📄 CV Personalizado")

                if cv_html_file:
                    cv_html_path = os.path.join(RESULTS_DIR, "cvs", cv_html_file)
                    if os.path.exists(cv_html_path):
                        with open(cv_html_path, "r", encoding="utf-8") as f:
                            html_content = f.read()
                        components.html(html_content, height=800, scrolling=True)
                    else:
                        st.info("Preview HTML no disponible (generado en ejecución anterior)")

                c_dl, c_fb = st.columns([1, 1])
                with c_dl:
                    st.link_button("📥 Descargar CV en PDF", cv_url)
                with c_fb:
                    has_pending = feedback_mgr.has_pending(title, company)
                    if has_pending:
                        st.warning("⏳ Feedback pendiente de procesar")

                with st.form(key=f"fb_{title}_{company}", clear_on_submit=True):
                    st.markdown("**¿Quieres modificar algo del CV?**")
                    fb = st.text_area(
                        "Describe qué cambiar (ej: 'Más detalle en Spring Boot', 'Cambiar resumen para DevOps')",
                        key=f"fbt_{title}_{company}",
                        height=80,
                    )
                    submitted = st.form_submit_button("Enviar feedback")
                    if submitted and fb.strip():
                        feedback_mgr.save_feedback(title, company, fb.strip())
                        st.success("Feedback guardado. Se procesará en la próxima ejecución.")
                        st.rerun()
                    elif submitted:
                        st.warning("Escribe algo antes de enviar.")

    if filtered:
        if st.button("📥 Exportar CSV"):
            csv_data = pd.DataFrame(filtered)
            display_cols = ["title", "company", "source", "match_score", "salary",
                            "work_mode", "required_experience", "status", "link"]
            display_cols = [c for c in display_cols if c in csv_data.columns]
            csv_export = csv_data[display_cols].to_csv(index=False).encode("utf-8")
            st.download_button("📥 Descargar CSV", csv_export,
                               file_name=f"ofertas_{datetime.now().strftime('%Y%m%d')}.csv",
                               mime="text/csv",
                                key="csv_download")

# ═══════════════════════════════════════════════════════════════
# TAB 2: OFERTAS SIN ANALIZAR
# ═══════════════════════════════════════════════════════════════
with tab_sin_analizar:
    unanalyzed_jobs = [j for j in all_jobs if j.get("needs_analysis")]

    if not unanalyzed_jobs:
        st.info("No hay ofertas sin analizar. Todas las ofertas han sido procesadas por Gemini.")
    else:
        st.subheader(f"📋 {len(unanalyzed_jobs)} ofertas sin analizar")
        st.caption("Estas ofertas no pudieron ser clasificadas automaticamente por Gemini y necesitan un análisis.")

        if st.button("🔍 Reanalizar todas las ofertas", type="primary", use_container_width=True):
            analyzed, errors = reanalyze_jobs_with_gemini(unanalyzed_jobs)
            load_data.clear()
            aggregate_all_jobs.clear()
            st.rerun()

        st.divider()

        with st.expander("🔍 Buscar y filtrar", expanded=False):
            search_unanalyzed = st.text_input(
                "🔎 Buscar por titulo, empresa o ubicacion",
                placeholder="Ej: Python, Sevilla...",
                key="search_unanalyzed",
            )

        filtered_unanalyzed = unanalyzed_jobs
        if search_unanalyzed.strip():
            q = search_unanalyzed.lower()
            filtered_unanalyzed = [
                j for j in filtered_unanalyzed
                if q in f"{j.get('title', '')} {j.get('company', '')} {j.get('location', '')}".lower()
            ]

        for j in filtered_unanalyzed:
            title = j.get("title", "N/A")
            company = j.get("company", "N/A")
            source = j.get("source", "N/A")
            link = j.get("link", "")

            header_parts = [f"**{title}** @ {company}"]
            header_parts.append(f"🏢 {source}")

            with st.expander(" | ".join(header_parts)):
                if j.get("location"):
                    st.markdown(f"**Ubicacion:** {j['location']}")
                if j.get("description"):
                    with st.expander("Ver descripcion", expanded=False):
                        st.text(j["description"][:2000])
                if link:
                    st.link_button("🔗 Ver oferta original", link)

# ═══════════════════════════════════════════════════════════════
# TAB 3: OFERTAS ARCHIVADAS
# ═══════════════════════════════════════════════════════════════
with tab_archivadas:
    archived_jobs = [j for j in all_jobs if j.get("archived")]

    if not archived_jobs:
        st.info("No hay ofertas archivadas.")
    else:
        st.subheader(f"📦 {len(archived_jobs)} ofertas archivadas")

        with st.expander("🔍 Buscar y filtrar", expanded=False):
            search_archived = st.text_input(
                "🔎 Buscar por titulo, empresa o ubicacion",
                placeholder="Ej: Python, Sevilla...",
                key="search_archived",
            )
            all_modes_arch = sorted(set(
                config.normalize_work_mode(j.get("work_mode", "N/A"))
                for j in archived_jobs
            ))
            filter_mode_arch = st.multiselect(
                "Modalidad",
                options=all_modes_arch,
                default=[],
                key="filter_mode_arch",
            )

        filtered_archived = archived_jobs
        if search_archived.strip():
            q = search_archived.lower()
            filtered_archived = [
                j for j in filtered_archived
                if q in f"{j.get('title', '')} {j.get('company', '')} {j.get('location', '')}".lower()
            ]
        if filter_mode_arch:
            filtered_archived = [
                j for j in filtered_archived
                if config.normalize_work_mode(j.get("work_mode", "N/A")) in filter_mode_arch
            ]

        for j in filtered_archived:
            title = j.get("title", "N/A")
            company = j.get("company", "N/A")
            match = j.get("match_score", 0)
            salary = j.get("salary", "")
            salary_is_est = j.get("salary_is_estimate", True)
            mode = config.normalize_work_mode(j.get("work_mode", "N/A"))
            status = j.get("status", "Nuevo")
            source = j.get("source", "N/A")
            exp = j.get("required_experience", 0)
            link = j.get("link", "")
            techs = j.get("tech_stack", [])
            advice = j.get("tailored_advice", "")
            cover_letter = j.get("cover_letter", "")
            cv_url = j.get("custom_cv_url", "")
            cv_html_file = j.get("custom_cv_html", "")
            cl_pdf_url = j.get("cover_letter_pdf_url", "")

            header_parts = [f"**{title}** @ {company}"]
            header_parts.append(f"🎯 {match}%")
            if salary:
                sal_label = f"{salary}€"
                if salary_is_est:
                    sal_label += " ≈"
                header_parts.append(f"💰 {sal_label}")
            header_parts.append(f"📍 {mode}")
            header_parts.append(f"🏢 {source}")
            header_parts.append(f"[{status}]")

            with st.expander(" | ".join(header_parts)):
                m1, m2, m3, m4, m5 = st.columns(5)
                m1.metric("Match", f"{match}%")
                if salary:
                    sal_display = f"{salary}€"
                    sal_source = "Aproximacion IA" if salary_is_est else "Oferta"
                    m2.metric("Salario", sal_display, help=f"Fuente: {sal_source}")
                    if salary_is_est:
                        st.caption("≈ Salario estimado por IA")
                    else:
                        st.caption("✅ Salario de la oferta")
                else:
                    m2.metric("Salario", "No especificado")
                m3.metric("Modalidad", mode)
                m4.metric("Experiencia", f"{exp} anios" if exp else "Junior")
                m5.metric("Fuente", source)

                if j.get("location"):
                    st.markdown(f"**Ubicacion:** {j['location']}")

                if j.get("archived") and j.get("archive_reason"):
                    st.warning(f"**Razon de archivado:** {j['archive_reason']}")

                _job_key_arch = hashlib.md5(f"{title}{company}{link}".encode()).hexdigest()[:10]

                if st.button("Desarchivar oferta", key=f"unarch_{_job_key_arch}", use_container_width=True):
                    if save_job_archived(data, link, False):
                        try:
                            NotionSync().update_job_eliminar(link, False)
                        except Exception:
                            pass
                        load_data.clear()
                        aggregate_all_jobs.clear()
                        st.rerun()

                if techs:
                    st.markdown(f"**Stack:** {', '.join(techs)}")

                if link:
                    st.link_button("🔗 Ver oferta original", link)

                if advice:
                    with st.expander("Consejos personalizados"):
                        st.write(advice)

                if cover_letter:
                    st.divider()
                    st.subheader("Carta de Presentacion")
                    st.markdown(cover_letter)
                    if cl_pdf_url:
                        st.link_button("Descargar Carta en PDF", cl_pdf_url)

                interview_prep = j.get("interview_prep")
                if interview_prep:
                    st.divider()
                    with st.expander("Preparacion para Entrevista", expanded=False):
                        tech_qs = interview_prep.get("technical_questions", [])
                        beh_qs = interview_prep.get("behavioral_questions", [])
                        key_topics = interview_prep.get("key_topics", [])
                        tips = interview_prep.get("preparation_tips", [])

                        has_content = any([tech_qs, beh_qs, key_topics, tips])
                        if not has_content:
                            st.info("No hay contenido de preparación disponible.")

                        st.markdown("**Preguntas Tecnicas:**")
                        if tech_qs:
                            for i, qa in enumerate(tech_qs, 1):
                                st.markdown(f"**{i}. {qa.get('question', '')}**")
                                st.markdown(f"→ {qa.get('answer', '')}")
                                st.markdown("")
                        else:
                            st.markdown("_No disponibles_")

                        st.markdown("**Preguntas Comportamentales (STAR):**")
                        if beh_qs:
                            for i, qa in enumerate(beh_qs, 1):
                                st.markdown(f"**{i}. {qa.get('question', '')}**")
                                st.markdown(f"→ {qa.get('answer', '')}")
                                st.markdown("")
                        else:
                            st.markdown("_No disponibles_")

                        st.markdown("**Temas Clave:**")
                        if key_topics:
                            st.markdown(", ".join(key_topics))
                        else:
                            st.markdown("_No disponibles_")

                        st.markdown("**Consejos:**")
                        if tips:
                            for tip in tips:
                                st.markdown(f"• {tip}")
                        else:
                            st.markdown("_No disponibles_")

                company_profile = j.get("company_profile")
                if company_profile:
                    st.divider()
                    with st.expander(f"Perfil de {company_profile.get('name', company)}", expanded=False):
                        cp = company_profile
                        c1, c2 = st.columns(2)
                        with c1:
                            st.markdown(f"**Sector:** {cp.get('industry', 'N/A')}")
                            st.markdown(f"**Tamano:** {cp.get('size', 'N/A')}")
                            st.markdown(f"**Salario:** {cp.get('salary_range', 'N/A')}")
                        with c2:
                            remote = "Si" if cp.get('remote_friendly') else "No"
                            st.markdown(f"**Remoto:** {remote}")
                            techs_cp = ", ".join(cp.get("tech_stack", [])[:8])
                            st.markdown(f"**Tech stack:** {techs_cp}")

                        if cp.get("culture"):
                            st.markdown(f"**Cultura:** {cp['culture']}")

                        pros = cp.get("pros", [])
                        if pros:
                            st.markdown("**Pros:**")
                            for p in pros:
                                st.markdown(f"  • {p}")

                        cons = cp.get("cons", [])
                        if cons:
                            st.markdown("**A tener en cuenta:**")
                            for c in cons:
                                st.markdown(f"  • {c}")

                        rec = cp.get("recommendation", "")
                        if rec:
                            st.info(rec)

                project_match = j.get("project_match")
                if project_match:
                    st.divider()
                    with st.expander("Match de Proyectos Personales", expanded=False):
                        pm = project_match
                        st.metric("Relevancia de proyectos", f"{pm.get('project_relevance', 0)}%")

                        matching = pm.get("matching_projects", [])
                        if matching:
                            st.markdown("**Proyectos relevantes:**")
                            for mp in matching:
                                st.markdown(f"  {mp}")

                        missing = pm.get("missing_project_types", [])
                        if missing:
                            st.markdown("**Tipos de proyecto que te faltan:**")
                            for m in missing:
                                st.markdown(f"  {m}")

                        advice_pm = pm.get("project_advice", "")
                        if advice_pm:
                            st.info(advice_pm)

                if cv_url:
                    st.divider()
                    st.subheader("CV Personalizado")
                    if cv_html_file:
                        cv_html_path = os.path.join(RESULTS_DIR, "cvs", cv_html_file)
                        if os.path.exists(cv_html_path):
                            with open(cv_html_path, "r", encoding="utf-8") as f:
                                html_content = f.read()
                            components.html(html_content, height=800, scrolling=True)
                        else:
                            st.info("Preview HTML no disponible (generado en ejecucion anterior)")
                    st.link_button("Descargar CV en PDF", cv_url)

# ═══════════════════════════════════════════════════════════════
# TAB 3: PIPELINE — Estado de aplicaciones
# ═══════════════════════════════════════════════════════════════
with tab_pipeline:
    st.subheader("🔄 Pipeline de Aplicaciones")

    status_counts = {}
    for status in config.APPLICATION_STATUSES:
        status_counts[status] = len([j for j in all_jobs if j.get("status") == status])
    total = len(all_jobs)

    cols = st.columns(len(config.APPLICATION_STATUSES))
    colors = ["#4CAF50", "#8BC34A", "#CDDC39", "#FFC107", "#FF9800", "#2196F3", "#F44336"]
    for i, status in enumerate(config.APPLICATION_STATUSES):
        count = status_counts.get(status, 0)
        cols[i].metric(status, count)

    if total > 0:
        bar_html = '<div style="display:flex; gap:2px; height:36px; border-radius:6px; overflow:hidden; margin:10px 0;">'
        for i, status in enumerate(config.APPLICATION_STATUSES):
            count = status_counts.get(status, 0)
            pct = (count / total * 100) if total > 0 else 0
            if pct > 0:
                bar_html += f'<div style="width:{pct}%; background:{colors[i]}; display:flex; align-items:center; justify-content:center; color:white; font-size:12px; font-weight:bold;">{count}</div>'
        bar_html += '</div>'
        st.markdown(bar_html, unsafe_allow_html=True)

    follow_up_needed = []
    for j in all_jobs:
        if j.get("status") == "Aplicado" and j.get("_first_seen"):
            try:
                first = datetime.fromisoformat(j["_first_seen"])
                days = (datetime.now() - first).days
                if days >= config.FOLLOWUP_REMINDER_DAYS:
                    j["_days_applied"] = days
                    follow_up_needed.append(j)
            except (ValueError, TypeError):
                pass

    if follow_up_needed:
        st.warning(f"⏰ {len(follow_up_needed)} ofertas aplicadas hace 5+ días sin respuesta — considera hacer follow-up")
        with st.expander(f"🔔 Recordatorios pendientes ({len(follow_up_needed)})", expanded=False):
            for j in follow_up_needed:
                title_fu = j.get('title', '')
                company_fu = j.get('company', '')
                st.write(f"• **{title_fu}** @ {company_fu} — hace {j['_days_applied']} días")
                fc1, fc2 = st.columns([1, 1])
                _fu_key = hashlib.md5(f"{title_fu}{company_fu}".encode()).hexdigest()[:10]
                with fc1:
                    st.link_button("🔗 Ver oferta", j.get("link", ""), key=f"fu_{_fu_key}")
                with fc2:
                    ics_data_fu, ics_name_fu = ics_followup_content(title_fu, company_fu, j.get("link", ""), j["_days_applied"])
                    st.download_button(
                        "📅 Recordatorio",
                        ics_data_fu,
                        file_name=ics_name_fu,
                        mime="text/calendar",
                        key=f"ics_fu_{_fu_key}",
                    )

    if all_jobs:
        st.subheader("Ofertas por estado")
        for status in config.APPLICATION_STATUSES:
            status_jobs = [j for j in all_jobs if j.get("status") == status]
            if status_jobs:
                with st.expander(f"{status} ({len(status_jobs)})"):
                    for j in status_jobs[:20]:
                        st.write(f"• {j.get('title', 'N/A')} @ {j.get('company', 'N/A')} ({j.get('match_score', 0)}%)")

# ═══════════════════════════════════════════════════════════════
# TAB 3: ESTADÍSTICAS — Datos agregados de TODAS las ofertas
# ═══════════════════════════════════════════════════════════════
with tab_stats:
    st.subheader("📊 Estadísticas del mercado laboral")

    if not all_jobs:
        st.info("No hay datos suficientes.")
        st.stop()

    st.markdown("### 💰 Inteligencia Salarial")
    all_sal_data = []
    mode_salaries = defaultdict(list)
    source_salaries = defaultdict(list)
    direct_salaries = []
    estimated_salaries = []
    for j in all_jobs:
        s = parse_salary(j.get("salary"))
        if s:
            all_sal_data.append(s)
            wm = config.normalize_work_mode(j.get("work_mode", "")) or "No especificado"
            mode_salaries[wm].append(s)
            source_salaries[j.get("source", "N/A")].append(s)
            if j.get("salary_is_estimate", True):
                estimated_salaries.append(s)
            else:
                direct_salaries.append(s)

    if all_sal_data:
        sc1, sc2, sc3, sc4 = st.columns(4)
        sc1.metric("Promedio", f"{sum(all_sal_data) // len(all_sal_data):,}€".replace(",", "."))
        sc2.metric("Mediano", f"{statistics.median(all_sal_data):,.0f}€".replace(",", "."))
        sc3.metric("Mínimo", f"{min(all_sal_data):,}€".replace(",", "."))
        sc4.metric("Máximo", f"{max(all_sal_data):,}€".replace(",", "."))

        with st.expander("Salario por modalidad"):
            mode_data = []
            for mode, sals in sorted(mode_salaries.items()):
                mode_data.append({
                    "Modalidad": mode,
                    "Promedio": f"{sum(sals) // len(sals):,}€".replace(",", "."),
                    "Mínimo": f"{min(sals):,}€".replace(",", "."),
                    "Máximo": f"{max(sals):,}€".replace(",", "."),
                    "Ofertas": len(sals),
                })
            st.dataframe(pd.DataFrame(mode_data), use_container_width=True, hide_index=True)

        with st.expander("Salario por plataforma"):
            src_data = []
            for src, sals in sorted(source_salaries.items(), key=lambda x: sum(x[1]) / len(x[1]), reverse=True):
                src_data.append({
                    "Plataforma": src,
                    "Promedio": f"{sum(sals) // len(sals):,}€".replace(",", "."),
                    "Rango": f"{min(sals):,}€ - {max(sals):,}€".replace(",", "."),
                    "Ofertas": len(sals),
                })
            st.dataframe(pd.DataFrame(src_data), use_container_width=True, hide_index=True)

        with st.expander("Salario por fuente (Directo vs Estimado)"):
            src_comp = []
            if direct_salaries:
                src_comp.append({"Tipo": "Directo (de la oferta)", "Ofertas": len(direct_salaries), "Promedio": f"{sum(direct_salaries)//len(direct_salaries):,}€".replace(",", "."), "Minimo": f"{min(direct_salaries):,}€".replace(",", "."), "Maximo": f"{max(direct_salaries):,}€".replace(",", ".")})
            if estimated_salaries:
                src_comp.append({"Tipo": "Estimado (IA)", "Ofertas": len(estimated_salaries), "Promedio": f"{sum(estimated_salaries)//len(estimated_salaries):,}€".replace(",", "."), "Minimo": f"{min(estimated_salaries):,}€".replace(",", "."), "Maximo": f"{max(estimated_salaries):,}€".replace(",", ".")})
            if src_comp:
                st.dataframe(pd.DataFrame(src_comp), use_container_width=True, hide_index=True)
    else:
        st.info("No hay datos de salario disponibles")

    st.markdown("### 🎯 Skills Gap")
    all_techs_stats = defaultdict(int)
    remote_count = 0
    mode_counts = defaultdict(int)
    source_counts = defaultdict(int)
    for j in all_jobs:
        for tech in j.get("tech_stack", []):
            all_techs_stats[tech] += 1
        wm = config.normalize_work_mode(j.get("work_mode", "")) or "No especificado"
        mode_counts[wm] += 1
        source_counts[j.get("source", "N/A")] += 1
        if wm == "Remoto":
            remote_count += 1

    cv_skills_lower = set()
    profile_skills = latest.get("profile_skills", [])
    if profile_skills:
        cv_skills_lower = {s.lower().strip() for s in profile_skills}
        with st.expander("Tus skills del CV", expanded=False):
            st.write(", ".join(sorted(cv_skills_lower)))

    if all_techs_stats:
        demanded = sorted(all_techs_stats.items(), key=lambda x: x[1], reverse=True)
        if cv_skills_lower:
            gap = []
            have = []
            for tech, count in demanded:
                pct = round(count / len(all_jobs) * 100, 1)
                if tech.lower().strip() in cv_skills_lower:
                    have.append({"Skill": tech, "Ofertas": count, "% mercado": f"{pct}%", "Estado": "✅"})
                else:
                    gap.append({"Skill": tech, "Ofertas": count, "% mercado": f"{pct}%", "Estado": "❌"})
            if gap:
                st.subheader("Skills que te faltan")
                st.dataframe(pd.DataFrame(gap), use_container_width=True, hide_index=True)
                st.bar_chart(pd.DataFrame(gap).set_index("Skill")["Ofertas"])
            if have:
                with st.expander(f"Skills que ya tienes ({len(have)})"):
                    st.dataframe(pd.DataFrame(have), use_container_width=True, hide_index=True)
        else:
            tech_data = [{"Skill": t, "Ofertas": c, "%": f"{round(c/len(all_jobs)*100, 1)}%"} for t, c in demanded[:20]]
            st.dataframe(pd.DataFrame(tech_data), use_container_width=True, hide_index=True)
            st.bar_chart(pd.DataFrame(tech_data).set_index("Skill")["Ofertas"])

    st.markdown("### 📈 Resumen del mercado")
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Total ofertas", len(all_jobs))
    mc2.metric("% Remoto", f"{remote_count/len(all_jobs)*100:.0f}%")
    mc3.metric("Salario mediano", f"{statistics.median(all_sal_data):,.0f}€".replace(",", ".") if all_sal_data else "N/A")
    mc4.metric("Plataformas", len(source_counts))

    chart_c1, chart_c2 = st.columns(2)
    with chart_c1:
        st.subheader("Por modalidad")
        st.bar_chart(pd.DataFrame(list(mode_counts.items()), columns=["Modalidad", "Ofertas"]).set_index("Modalidad"))
    with chart_c2:
        st.subheader("Por plataforma")
        st.bar_chart(pd.DataFrame(list(source_counts.items()), columns=["Plataforma", "Ofertas"]).set_index("Plataforma"))

    if len(runs) > 1:
        st.markdown("### 📈 Tendencias Temporales")

        trend_data = []
        for run in reversed(runs):
            run_ts = run.get("timestamp", "")[:10]
            run_jobs = run.get("jobs", [])

            salaries = []
            remote_count = 0
            tech_counts = defaultdict(int)
            for j in run_jobs:
                s = parse_salary(j.get("salary"))
                if s:
                    salaries.append(s)
                if config.normalize_work_mode(j.get("work_mode", "")) == "Remoto":
                    remote_count += 1
                for t in j.get("tech_stack", []):
                    tech_counts[t] += 1

            avg_salary = sum(salaries) // len(salaries) if salaries else 0
            remote_pct = (remote_count / len(run_jobs) * 100) if run_jobs else 0
            top3 = [t for t, _ in sorted(tech_counts.items(), key=lambda x: x[1], reverse=True)[:3]]

            trend_data.append({
                "Fecha": run_ts,
                "Ofertas": len(run_jobs),
                "Salario Promedio (€)": avg_salary,
                "% Remoto": round(remote_pct, 1),
                "Top Techs": ", ".join(top3) if top3 else "N/A",
            })

        if trend_data:
            trend_df = pd.DataFrame(trend_data)

            tc1, tc2 = st.columns(2)
            with tc1:
                st.markdown("**Salario promedio por ejecución**")
                sal_chart = trend_df.set_index("Fecha")[["Salario Promedio (€)"]]
                st.line_chart(sal_chart)
            with tc2:
                st.markdown("**% Remoto por ejecución**")
                remote_chart = trend_df.set_index("Fecha")[["% Remoto"]]
                st.line_chart(remote_chart)

            st.markdown("**Ofertas encontradas por ejecución**")
            offers_chart = trend_df.set_index("Fecha")[["Ofertas"]]
            st.bar_chart(offers_chart)

            with st.expander("Detalle por ejecución"):
                st.dataframe(trend_df, use_container_width=True, hide_index=True)

# ═══════════════════════════════════════════════════════════════
# TAB 4: EJECUCIONES — Historial, scrapers, errores
# ═══════════════════════════════════════════════════════════════
with tab_ejecuciones:
    st.subheader("📈 Ejecuciones")

    stats = latest.get("scraper_stats", {})
    total_found = sum(s.get("found", 0) for s in stats.values())
    scrapers_ok = sum(1 for s in stats.values() if not s.get("failed") and s.get("found", 0) > 0)
    scrapers_zero = sum(1 for s in stats.values() if s.get("failed") and not s.get("error"))
    scrapers_fail = sum(1 for s in stats.values() if s.get("failed") and s.get("error"))
    added = latest.get("_total_added", 0)
    analyzed = latest.get("_analyzed_count", 0)

    st.markdown("#### Última ejecución")
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Ofertas encontradas", total_found)
    k2.metric("Añadidas a Notion", added)
    k3.metric("Analizadas por IA", analyzed)
    k4.metric("Scrapers OK", scrapers_ok)
    k5.metric("Sin ofertas", scrapers_zero)
    k6.metric("Scrapers fallidos", scrapers_fail, delta=f"-{scrapers_fail}" if scrapers_fail else None, delta_color="inverse")

    errors = latest.get("errors", [])
    if errors:
        st.error(f"**{len(errors)} error(es):**")
        for e in errors:
            st.write(f"• {e}")

    st.markdown("#### Scrapers")
    scraper_data = []
    for name, s in stats.items():
        found = s.get("found", 0)
        failed = s.get("failed", False)
        error = s.get("error", "")
        if failed and error:
            estado = "❌ Fallido"
        elif failed:
            estado = "⚠️ Sin ofertas"
        else:
            estado = "✅ OK"
        scraper_data.append({
            "Plataforma": name,
            "Ofertas": found,
            "Estado": estado,
            "Error": error if failed else "",
        })
    st.dataframe(pd.DataFrame(scraper_data), use_container_width=True, hide_index=True)

    if len(runs) > 1:
        st.markdown("#### Historial")
        history = []
        for run in runs:
            st_stats = run.get("scraper_stats", {})
            history.append({
                "Fecha": run.get("timestamp", "")[:16],
                "Encontradas": sum(s.get("found", 0) for s in st_stats.values()),
                "Añadidas": run.get("_total_added", 0),
                "Analizadas": run.get("_analyzed_count", 0),
                "Scrapers OK": sum(1 for s in st_stats.values() if not s.get("failed") and s.get("found", 0) > 0),
                "Sin ofertas": sum(1 for s in st_stats.values() if s.get("failed") and not s.get("error")),
                "Scrapers FAIL": sum(1 for s in st_stats.values() if s.get("failed") and s.get("error")),
                "Errores": len(run.get("errors", [])),
            })
        hist_df = pd.DataFrame(history)
        st.dataframe(hist_df, use_container_width=True, hide_index=True)

        chart_c1, chart_c2 = st.columns(2)
        with chart_c1:
            chart_data = hist_df[["Fecha", "Encontradas", "Añadidas"]].copy()
            chart_data = chart_data.set_index("Fecha")
            st.line_chart(chart_data)
        with chart_c2:
            chart_data2 = hist_df[["Fecha", "Scrapers OK", "Scrapers FAIL"]].copy()
            chart_data2 = chart_data2.set_index("Fecha")
            st.bar_chart(chart_data2)
    else:
        st.info("Solo hay una ejecución registrada.")
