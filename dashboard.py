#!/usr/bin/env python3
"""
Dashboard interactivo — Panel de gestión de ofertas de empleo.
Ejecutar con: streamlit run dashboard.py
"""
import os
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import json
import httpx
import statistics
from datetime import datetime
from utils.feedback_manager import FeedbackManager
import config

st.set_page_config(
    page_title="Job Scraper Dashboard",
    page_icon="🔍",
    layout="wide",
)

RESULTS_DIR = os.path.join(Path(__file__).resolve().parent, "results")


def load_data():
    data_path = os.path.join(RESULTS_DIR, "data.json")
    if os.path.exists(data_path):
        with open(data_path, "r", encoding="utf-8") as f:
            return json.load(f)
    github_repo = os.getenv("GITHUB_REPO", "Jorgejs4/Job-Finder-Assistant")
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


def aggregate_all_jobs(runs):
    """Agrega todas las ofertas de todas las ejecuciones, deduplicando por URL."""
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
                            "match_score", "tech_stack", "tailored_advice",
                            "salary", "work_mode", "salary_is_estimate",
                            "required_experience", "status"]:
                    if job.get(key):
                        existing[key] = job[key]
            else:
                job["_first_seen"] = run_ts
                job["_last_seen"] = run_ts
                job["_last_run_id"] = run_id
                jobs_by_url[url] = job
    return list(jobs_by_url.values())


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

st.title("🔍 Job Scraper Dashboard")
st.caption(f"{len(all_jobs)} ofertas de {len(runs)} ejecuciones | Última carga: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

if not runs:
    st.warning("No hay ejecuciones registradas. Ejecuta `python main.py` primero.")
    st.stop()

latest = runs[0]

tab_mis_ofertas, tab_pipeline, tab_stats, tab_ejecuciones = st.tabs(
    ["💼 Mis Ofertas", "🔄 Pipeline", "📊 Estadísticas", "📈 Ejecuciones"]
)

# ═══════════════════════════════════════════════════════════════
# TAB 1: MIS OFERTAS — Panel principal
# ═══════════════════════════════════════════════════════════════
with tab_mis_ofertas:
    if not all_jobs:
        st.info("No hay ofertas disponibles.")
        st.stop()

    st.subheader(f"💼 {len(all_jobs)} ofertas disponibles")

    with st.expander("🔍 Filtros avanzados", expanded=True):
        f1, f2, f3, f4 = st.columns(4)
        with f1:
            all_sources = sorted(set(j.get("source", "N/A") for j in all_jobs))
            source_filter = st.multiselect("Fuente", all_sources, default=all_sources)
        with f2:
            all_modes_raw = set()
            for j in all_jobs:
                wm = j.get("work_mode", "")
                if wm and wm != "N/A":
                    all_modes_raw.add(wm)
            all_modes = sorted(all_modes_raw)
            mode_filter = st.multiselect("Modalidad", all_modes + ["Sin analizar"], default=all_modes + ["Sin analizar"])
        with f3:
            all_statuses = [s for s in config.APPLICATION_STATUSES if any(j.get("status") == s for j in all_jobs)]
            status_filter = st.multiselect("Estado", config.APPLICATION_STATUSES, default=all_statuses)
        with f4:
            min_score = st.slider("Match mínimo (solo aplica a ofertas analizadas)", 0, 100, 0)

        f5, f6, f7, f8 = st.columns(4)
        with f5:
            all_salaries = [parse_salary(j.get("salary")) for j in all_jobs if parse_salary(j.get("salary"))]
            sal_max = max(all_salaries) if all_salaries else 150000
            sal_range = st.slider(
                "Rango salarial (€)",
                min_value=0,
                max_value=max(150000, sal_max + 10000),
                value=(0, max(150000, sal_max + 10000)),
                step=1000,
            )
        with f6:
            all_techs = defaultdict(int)
            for j in all_jobs:
                for t in j.get("tech_stack", []):
                    all_techs[t] += 1
            top_techs = [t for t, _ in sorted(all_techs.items(), key=lambda x: x[1], reverse=True)[:30]]
            tech_filter = st.multiselect("Tech stack", top_techs, default=[])
        with f7:
            exp_values = sorted(set(j.get("required_experience", 0) for j in all_jobs if j.get("required_experience")))
            max_exp = max(exp_values) if exp_values else 10
            exp_slider_max = max(max_exp, 10)
            exp_filter = st.slider("Experiencia máx (años)", 0, exp_slider_max, exp_slider_max)
        with f8:
            all_locations = set()
            for j in all_jobs:
                loc = j.get("location", "")
                if loc and loc.strip():
                    all_locations.add(loc.strip())
            location_options = sorted(all_locations)
            location_filter = st.multiselect("Ubicación", location_options, default=[])

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

    filtered = []
    for j in all_jobs:
        if source_filter and j.get("source", "N/A") not in source_filter:
            continue

        wm = j.get("work_mode", "")
        is_analyzed = bool(j.get("match_score"))
        if is_analyzed:
            if wm and wm != "N/A" and mode_filter and wm not in mode_filter:
                continue
        else:
            if "Sin analizar" not in mode_filter:
                continue

        job_status = j.get("status", "Nuevo")
        if status_filter and job_status not in status_filter:
            continue

        match = j.get("match_score") or 0
        if is_analyzed and match < min_score:
            continue

        exp = j.get("required_experience") or 0
        if is_analyzed and exp > exp_filter:
            continue

        sal = parse_salary(j.get("salary"))
        if sal is not None and sal_range:
            if sal < sal_range[0] or sal > sal_range[1]:
                continue

        if tech_filter:
            job_techs = j.get("tech_stack", [])
            if not any(t in tech_filter for t in job_techs):
                continue

        if location_filter:
            jloc = j.get("location", "").strip()
            if jloc not in location_filter:
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
        mode = j.get("work_mode", "N/A")
        status = j.get("status", "Nuevo")
        source = j.get("source", "N/A")
        exp = j.get("required_experience", 0)
        link = j.get("link", "")
        techs = j.get("tech_stack", [])
        advice = j.get("tailored_advice", "")
        cover_letter = j.get("cover_letter", "")
        cv_url = j.get("custom_cv_url", "")
        cv_html_file = j.get("custom_cv_html", "")

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
                sal_source = "Aproximación IA" if salary_is_est else "Oferta"
                m2.metric("Salario", sal_display, help=f"Fuente: {sal_source}")
            else:
                m2.metric("Salario", "No especificado")
            m3.metric("Modalidad", mode)
            m4.metric("Experiencia", f"{exp} años" if exp else "Junior")
            m5.metric("Fuente", source)

            if j.get("location"):
                st.markdown(f"**Ubicación:** {j['location']}")

            if techs:
                st.markdown(f"**Stack:** {', '.join(techs)}")

            if link:
                st.link_button("🔗 Ver oferta original", link)

            if advice:
                with st.expander("💡 Consejos personalizados"):
                    st.write(advice)

            if cover_letter:
                st.divider()
                st.subheader("📝 Carta de Presentación")
                st.markdown(cover_letter)

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
        csv_data = pd.DataFrame(filtered)
        display_cols = ["title", "company", "source", "match_score", "salary",
                        "work_mode", "required_experience", "status", "link"]
        display_cols = [c for c in display_cols if c in csv_data.columns]
        csv_export = csv_data[display_cols].to_csv(index=False).encode("utf-8")
        st.download_button("📥 Exportar CSV", csv_export,
                           file_name=f"ofertas_{datetime.now().strftime('%Y%m%d')}.csv",
                           mime="text/csv")

# ═══════════════════════════════════════════════════════════════
# TAB 2: PIPELINE — Estado de aplicaciones
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
    for j in all_jobs:
        s = parse_salary(j.get("salary"))
        if s:
            all_sal_data.append(s)
            wm = j.get("work_mode") or "No especificado"
            mode_salaries[wm].append(s)
            source_salaries[j.get("source", "N/A")].append(s)

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
            direct = [parse_salary(j.get("salary")) for j in all_jobs if parse_salary(j.get("salary")) and not j.get("salary_is_estimate", True)]
            estimated = [parse_salary(j.get("salary")) for j in all_jobs if parse_salary(j.get("salary")) and j.get("salary_is_estimate", True)]
            src_comp = []
            if direct:
                src_comp.append({"Tipo": "Directo (de la oferta)", "Ofertas": len(direct), "Promedio": f"{sum(direct)//len(direct):,}€".replace(",", "."), "Mínimo": f"{min(direct):,}€".replace(",", "."), "Máximo": f"{max(direct):,}€".replace(",", ".")})
            if estimated:
                src_comp.append({"Tipo": "Estimado (IA)", "Ofertas": len(estimated), "Promedio": f"{sum(estimated)//len(estimated):,}€".replace(",", "."), "Mínimo": f"{min(estimated):,}€".replace(",", "."), "Máximo": f"{max(estimated):,}€".replace(",", ".")})
            if src_comp:
                st.dataframe(pd.DataFrame(src_comp), use_container_width=True, hide_index=True)
    else:
        st.info("No hay datos de salario disponibles")

    st.markdown("### 🎯 Skills Gap")
    all_techs = defaultdict(int)
    for j in all_jobs:
        for tech in j.get("tech_stack", []):
            all_techs[tech] += 1

    cv_skills_lower = set()
    profile_skills = latest.get("profile_skills", [])
    if profile_skills:
        cv_skills_lower = {s.lower().strip() for s in profile_skills}
        with st.expander("Tus skills del CV", expanded=False):
            st.write(", ".join(sorted(cv_skills_lower)))

    if all_techs:
        demanded = sorted(all_techs.items(), key=lambda x: x[1], reverse=True)
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
    remote_count = len([j for j in all_jobs if j.get("work_mode") == "Remoto"])
    mode_counts = defaultdict(int)
    source_counts = defaultdict(int)
    for j in all_jobs:
        wm = j.get("work_mode") or "No especificado"
        mode_counts[wm] += 1
        source_counts[j.get("source", "N/A")] += 1

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

# ═══════════════════════════════════════════════════════════════
# TAB 4: EJECUCIONES — Historial, scrapers, errores
# ═══════════════════════════════════════════════════════════════
with tab_ejecuciones:
    st.subheader("📈 Ejecuciones")

    stats = latest.get("scraper_stats", {})
    total_found = sum(s.get("found", 0) for s in stats.values())
    scrapers_ok = sum(1 for s in stats.values() if not s.get("failed"))
    scrapers_fail = sum(1 for s in stats.values() if s.get("failed"))
    added = latest.get("_total_added", 0)
    analyzed = latest.get("_analyzed_count", 0)

    st.markdown("#### Última ejecución")
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Ofertas encontradas", total_found)
    k2.metric("Añadidas a Notion", added)
    k3.metric("Analizadas por IA", analyzed)
    k4.metric("Scrapers OK", scrapers_ok)
    k5.metric("Scrapers fallidos", scrapers_fail, delta=f"-{scrapers_fail}" if scrapers_fail else None, delta_color="inverse")

    errors = latest.get("errors", [])
    if errors:
        st.error(f"**{len(errors)} error(es):**")
        for e in errors:
            st.write(f"• {e}")

    st.markdown("#### Scrapers")
    scraper_data = []
    for name, s in stats.items():
        scraper_data.append({
            "Plataforma": name,
            "Ofertas": s.get("found", 0),
            "Estado": "❌ Fallido" if s.get("failed") else "✅ OK",
            "Error": s.get("error", "") if s.get("failed") else "",
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
                "Scrapers OK": sum(1 for s in st_stats.values() if not s.get("failed")),
                "Scrapers FAIL": sum(1 for s in st_stats.values() if s.get("failed")),
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
