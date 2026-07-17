#!/usr/bin/env python3
"""
Dashboard interactivo para el Job Scraper Assistant.
Ejecutar con: streamlit run dashboard.py
En Streamlit Cloud: leerá data.json desde GitHub API.
"""
import os
import sys
from pathlib import Path

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

# Intentar cargar data.json: local primero, luego GitHub API
def load_data():
    data_path = os.path.join(RESULTS_DIR, "data.json")
    if os.path.exists(data_path):
        with open(data_path, "r", encoding="utf-8") as f:
            return json.load(f)
    # Fallback: descargar desde GitHub API
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

data = load_data()
runs = data.get("runs", [])

st.title("🔍 Job Scraper Dashboard")
st.caption(f"Última carga: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

if not runs:
    st.warning("No hay ejecuciones registradas. Ejecuta `python main.py` primero.")
    st.stop()

latest = runs[0]

# --- KPIs principales ---
st.header("📊 Resumen de la última ejecución")
stats = latest.get("scraper_stats", {})
total_found = sum(s.get("found", 0) for s in stats.values())
scrapers_ok = sum(1 for s in stats.values() if not s.get("failed"))
scrapers_fail = sum(1 for s in stats.values() if s.get("failed"))
added = latest.get("_total_added", 0)
analyzed = latest.get("_analyzed_count", 0)

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Ofertas encontradas", total_found)
col2.metric("Añadidas a Notion", added)
col3.metric("Analizadas por IA", analyzed)
col4.metric("Scrapers OK", scrapers_ok)
col5.metric("Scrapers fallidos", scrapers_fail, delta=f"-{scrapers_fail}" if scrapers_fail else None, delta_color="inverse")

# --- Pipeline de Aplicaciones ---
st.header("🔄 Pipeline de Aplicaciones")
jobs = latest.get("jobs", [])
if jobs:
    status_counts = {}
    for status in config.APPLICATION_STATUSES:
        count = len([j for j in jobs if j.get("status") == status])
        status_counts[status] = count

    status_cols = st.columns(len(config.APPLICATION_STATUSES))
    for i, status in enumerate(config.APPLICATION_STATUSES):
        status_cols[i].metric(status, status_counts.get(status, 0))

    total_jobs = len(jobs)
    if total_jobs > 0:
        progress_html = '<div style="display:flex; gap:2px; height:30px; border-radius:6px; overflow:hidden; margin:10px 0;">'
        colors = ["#4CAF50", "#8BC34A", "#CDDC39", "#FFC107", "#FF9800", "#2196F3", "#F44336"]
        for i, status in enumerate(config.APPLICATION_STATUSES):
            count = status_counts.get(status, 0)
            pct = (count / total_jobs * 100) if total_jobs > 0 else 0
            if pct > 0:
                progress_html += f'<div style="width:{pct}%; background:{colors[i]}; display:flex; align-items:center; justify-content:center; color:white; font-size:12px; font-weight:bold;">{count}</div>'
        progress_html += '</div>'
        st.markdown(progress_html, unsafe_allow_html=True)
else:
    st.info("No hay ofertas para mostrar el pipeline.")

# --- Inteligencia Salarial ---
st.header("💰 Inteligencia Salarial")
if jobs:
    salaries = [j.get("salary") for j in jobs if j.get("salary")]
    if salaries:
        salaries_num = []
        for s in salaries:
            try:
                salaries_num.append(int(str(s).replace(".", "").replace(",", "")))
            except (ValueError, TypeError):
                pass
        
        if salaries_num:
            avg_sal = sum(salaries_num) // len(salaries_num)
            min_sal = min(salaries_num)
            max_sal = max(salaries_num)
            median_sal = statistics.median(salaries_num)

            sal_col1, sal_col2, sal_col3, sal_col4 = st.columns(4)
            sal_col1.metric("Salario promedio", f"{avg_sal:,}€".replace(",", "."))
            sal_col2.metric("Salario mediano", f"{median_sal:,}€".replace(",", "."))
            sal_col3.metric("Salario mínimo", f"{min_sal:,}€".replace(",", "."))
            sal_col4.metric("Salario máximo", f"{max_sal:,}€".replace(",", "."))

            # Salario por modalidad
            st.subheader("Salario por modalidad")
            mode_salaries = {}
            for j in jobs:
                mode = j.get("work_mode", "N/A")
                sal = j.get("salary")
                if sal and mode:
                    try:
                        sal_num = int(str(sal).replace(".", "").replace(",", ""))
                        if mode not in mode_salaries:
                            mode_salaries[mode] = []
                        mode_salaries[mode].append(sal_num)
                    except (ValueError, TypeError):
                        pass
            
            if mode_salaries:
                mode_data = []
                for mode, sals in mode_salaries.items():
                    mode_data.append({
                        "Modalidad": mode,
                        "Promedio": f"{sum(sals) // len(sals):,}€".replace(",", "."),
                        "Mínimo": f"{min(sals):,}€".replace(",", "."),
                        "Máximo": f"{max(sals):,}€".replace(",", "."),
                        "Ofertas": len(sals),
                    })
                st.dataframe(pd.DataFrame(mode_data), use_container_width=True, hide_index=True)

            # Salario por fuente
            st.subheader("Salario por plataforma")
            source_salaries = {}
            for j in jobs:
                source = j.get("source", "N/A")
                sal = j.get("salary")
                if sal and source:
                    try:
                        sal_num = int(str(sal).replace(".", "").replace(",", ""))
                        if source not in source_salaries:
                            source_salaries[source] = []
                        source_salaries[source].append(sal_num)
                    except (ValueError, TypeError):
                        pass
            
            if source_salaries:
                source_data = []
                for source, sals in sorted(source_salaries.items(), key=lambda x: sum(x[1]) / len(x[1]), reverse=True):
                    source_data.append({
                        "Plataforma": source,
                        "Promedio": f"{sum(sals) // len(sals):,}€".replace(",", "."),
                        "Rango": f"{min(sals):,}€ - {max(sals):,}€".replace(",", "."),
                        "Ofertas": len(sals),
                    })
                st.dataframe(pd.DataFrame(source_data), use_container_width=True, hide_index=True)
        else:
            st.info("No hay datos de salario para analizar")
    else:
        st.info("No hay ofertas con salario para analizar")
else:
    st.info("No hay ofertas para mostrar inteligencia salarial")

# --- Comparador de Ofertas ---
st.header("⚖️ Comparador de Ofertas")
if jobs and len(jobs) >= 2:
    job_options = {f"{j.get('title', 'N/A')} @ {j.get('company', 'N/A')}": j for j in jobs}
    
    selected = st.multiselect(
        "Selecciona 2-3 ofertas para comparar",
        options=list(job_options.keys()),
        max_selections=3,
    )
    
    if len(selected) >= 2:
        compare_jobs = [job_options[s] for s in selected]
        
        # Tabla comparativa
        compare_data = []
        for j in compare_jobs:
            compare_data.append({
                "Puesto": j.get("title", "N/A"),
                "Empresa": j.get("company", "N/A"),
                "Match": f"{j.get('match_score', 0)}%",
                "Salario": f"{j.get('salary', 'N/A')}€" if j.get("salary") else "N/A",
                "Modalidad": j.get("work_mode", "N/A"),
                "Experiencia": f"{j.get('required_experience', 0)} años",
                "Stack": ", ".join(j.get("tech_stack", [])[:5]),
                "Fuente": j.get("source", "N/A"),
            })
        st.dataframe(pd.DataFrame(compare_data), use_container_width=True, hide_index=True)
        
        # Consejos de cada oferta
        st.subheader("Consejos personalizados")
        for j in compare_jobs:
            with st.expander(f"💡 {j.get('title', 'N/A')} @ {j.get('company', 'N/A')}"):
                st.write(j.get("tailored_advice", "Sin consejos disponibles"))
                
        # Resumen comparativo
        st.subheader("📊 Resumen comparativo")
        scores = [j.get("match_score", 0) for j in compare_jobs]
        salaries_comp = []
        for j in compare_jobs:
            try:
                salaries_comp.append(int(str(j.get("salary", 0)).replace(".", "").replace(",", "")))
            except (ValueError, TypeError):
                pass
        
        best_match = compare_jobs[scores.index(max(scores))]
        best_salary = compare_jobs[salaries_comp.index(max(salaries_comp))] if salaries_comp else None
        
        col_a, col_b = st.columns(2)
        with col_a:
            st.success(f"🏆 **Mejor match:** {best_match.get('title', 'N/A')} ({max(scores)}%)")
        with col_b:
            if best_salary:
                st.success(f"💰 **Mejor salario:** {best_salary.get('title', 'N/A')} ({max(salaries_comp):,}€)".replace(",", "."))
else:
    st.info("Selecciona al menos 2 ofertas para comparar")

# --- Historial ---
history = []
for run in runs:
    st_stats = run.get("scraper_stats", {})
    history.append({
        "run_id": run.get("run_id", ""),
        "timestamp": run.get("timestamp", ""),
        "total_jobs_found": sum(s.get("found", 0) for s in st_stats.values()),
        "jobs_added_notion": run.get("_total_added", 0),
        "jobs_analyzed": run.get("_analyzed_count", 0),
        "scrapers_ok": sum(1 for s in st_stats.values() if not s.get("failed")),
        "scrapers_failed": sum(1 for s in st_stats.values() if s.get("failed")),
        "errors": len(run.get("errors", [])),
    })

if len(history) > 1:
    st.header("📈 Historial de ejecuciones")
    hist_df = pd.DataFrame(history)
    for col in ["total_jobs_found", "jobs_added_notion", "scrapers_ok", "scrapers_failed"]:
        if col in hist_df.columns:
            hist_df[col] = pd.to_numeric(hist_df[col], errors="coerce")

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        st.subheader("Ofertas por ejecución")
        chart_data = hist_df[["timestamp", "total_jobs_found", "jobs_added_notion"]].copy()
        chart_data["timestamp"] = pd.to_datetime(chart_data["timestamp"]).dt.strftime("%d/%m %H:%M")
        chart_data = chart_data.set_index("timestamp")
        st.line_chart(chart_data)

    with chart_col2:
        st.subheader("Scrapers OK / Fallidos")
        chart_data2 = hist_df[["timestamp", "scrapers_ok", "scrapers_failed"]].copy()
        chart_data2["timestamp"] = pd.to_datetime(chart_data2["timestamp"]).dt.strftime("%d/%m %H:%M")
        chart_data2 = chart_data2.set_index("timestamp")
        st.bar_chart(chart_data2)

# --- Scrapers ---
st.header("🤖 Scrapers")
scraper_df_data = []
for name, s in stats.items():
    scraper_df_data.append({
        "Plataforma": name,
        "Ofertas": s.get("found", 0),
        "Estado": "❌ Fallido" if s.get("failed") else "✅ OK",
        "Error": s.get("error", "") if s.get("failed") else "",
    })
st.dataframe(pd.DataFrame(scraper_df_data), use_container_width=True, hide_index=True)

# --- Errores ---
errors = latest.get("errors", [])
if errors:
    st.error(f"**{len(errors)} error(es) en la última ejecución:**")
    for e in errors:
        st.write(f"• {e}")

# --- Ofertas ---
st.header("💼 Ofertas encontradas")
if jobs:
    df_jobs = pd.DataFrame(jobs)

    filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
    with filter_col1:
        source_filter = st.multiselect(
            "Filtrar por fuente",
            options=df_jobs["source"].unique() if "source" in df_jobs.columns else [],
            default=df_jobs["source"].unique() if "source" in df_jobs.columns else [],
        )
    with filter_col2:
        if "match_score" in df_jobs.columns:
            min_score = st.slider("Match mínimo", 0, 100, 35)
        else:
            min_score = 0
    with filter_col3:
        if "work_mode" in df_jobs.columns:
            mode_filter = st.multiselect(
                "Modalidad",
                options=["Presencial", "Remoto", "Híbrido"],
                default=["Presencial", "Remoto", "Híbrido"],
            )
        else:
            mode_filter = []
    with filter_col4:
        if "status" in df_jobs.columns:
            status_filter = st.multiselect(
                "Estado",
                options=config.APPLICATION_STATUSES,
                default=config.APPLICATION_STATUSES,
            )
        else:
            status_filter = []

    filtered = df_jobs.copy()
    if "source" in filtered.columns:
        filtered = filtered[filtered["source"].isin(source_filter)]
    if "match_score" in filtered.columns:
        filtered = filtered[filtered["match_score"] >= min_score]
    if mode_filter and "work_mode" in filtered.columns:
        filtered = filtered[filtered["work_mode"].isin(mode_filter)]
    if status_filter and "status" in filtered.columns:
        filtered = filtered[filtered["status"].isin(status_filter)]

    if "match_score" in filtered.columns:
        filtered = filtered.sort_values("match_score", ascending=False)

    st.write(f"Mostrando **{len(filtered)}** ofertas de **{len(jobs)}** totales")

    display_cols = ["title", "company", "source", "location", "work_mode",
                    "match_score", "salary", "status", "link"]
    display_cols = [c for c in display_cols if c in filtered.columns]
    st.dataframe(filtered[display_cols], use_container_width=True, hide_index=True)

    csv_export = filtered.to_csv(index=False).encode("utf-8")
    st.download_button(
        "📥 Exportar CSV",
        csv_export,
        file_name=f"ofertas_{latest.get('run_id', 'export')}.csv",
        mime="text/csv",
    )

    # Visor de cartas y CVs
    st.header("📝 Cartas de Presentación y CVs")
    jobs_with_content = [j for j in jobs if j.get("cover_letter") or j.get("custom_cv_url")]
    feedback_mgr = FeedbackManager()

    if jobs_with_content:
        for j in jobs_with_content:
            title = j.get("title", "N/A")
            company = j.get("company", "N/A")
            with st.expander(f"📄 {title} @ {company}"):
                if j.get("cover_letter"):
                    st.subheader("Carta de Presentación")
                    st.markdown(j["cover_letter"])

                if j.get("custom_cv_url"):
                    st.subheader("CV Personalizado")

                    # Preview HTML del CV
                    cv_html_file = j.get("custom_cv_html", "")
                    if cv_html_file:
                        cv_html_path = os.path.join(RESULTS_DIR, "cvs", cv_html_file)
                        if os.path.exists(cv_html_path):
                            with open(cv_html_path, "r", encoding="utf-8") as f:
                                html_content = f.read()
                            components.html(html_content, height=800, scrolling=True)
                        else:
                            st.info("Archivo HTML del CV no encontrado (se generó en una ejecución anterior)")
                    else:
                        st.info("Preview HTML no disponible (CV generado antes de la actualización)")

                    # Botón de descarga PDF
                    st.link_button("📥 Descargar CV en PDF", j["custom_cv_url"])

                    # Feedback form
                    st.divider()
                    has_pending = feedback_mgr.has_pending(title, company)
                    if has_pending:
                        st.warning("⏳ Feedback pendiente de procesar (se procesará en la próxima ejecución)")

                    with st.form(key=f"feedback_{title}_{company}", clear_on_submit=True):
                        st.markdown("**¿Quieres modificar algo del CV?**")
                        feedback_text = st.text_area(
                            "Describe qué quieres cambiar (ej: 'Más detalle en la experiencia con Spring Boot', 'Quitar el proyecto X', 'Cambiar el resumen para enfocarlo en DevOps')",
                            key=f"fb_{title}_{company}",
                            height=80,
                        )
                        submitted = st.form_submit_button("Enviar feedback")
                        if submitted and feedback_text.strip():
                            feedback_mgr.save_feedback(title, company, feedback_text.strip())
                            st.success("Feedback guardado. Se procesará en la próxima ejecución del cron.")
                            st.rerun()
                        elif submitted:
                            st.warning("Escribe algo de feedback antes de enviar.")
    else:
        st.info("No hay cartas de presentación ni CVs generados en esta ejecución.")
else:
    st.info("No se encontraron ofertas en esta ejecución.")

# --- Skills Gap y Market Report (tabs) ---
if jobs:
    st.header("🎯 Análisis del Mercado")
    tab1, tab2 = st.tabs(["🔍 Skills Gap", "📊 Market Report"])

    with tab1:
        st.subheader("Skills más demandadas que no tienes en tu CV")
        all_techs = {}
        cv_skills_lower = set()
        for j in jobs:
            for tech in j.get("tech_stack", []):
                all_techs[tech] = all_techs.get(tech, 0) + 1

        if all_techs:
            tech_data = []
            for tech, count in sorted(all_techs.items(), key=lambda x: x[1], reverse=True)[:15]:
                pct = round(count / len(jobs) * 100, 1)
                tech_data.append({"Skill": tech, "Ofertas": count, "% del total": f"{pct}%"})
            st.dataframe(pd.DataFrame(tech_data), use_container_width=True, hide_index=True)

            st.bar_chart(pd.DataFrame(tech_data).set_index("Skill")["Ofertas"])
        else:
            st.info("No hay datos de skills suficientes para analizar.")

    with tab2:
        st.subheader("Resumen del mercado laboral")
        salaries_num = []
        remote_count = 0
        mode_counts = {}
        source_counts = {}
        for j in jobs:
            sal = j.get("salary")
            if sal:
                try:
                    salaries_num.append(int(str(sal).replace(".", "").replace(",", "")))
                except (ValueError, TypeError):
                    pass
            mode = j.get("work_mode", "N/A")
            mode_counts[mode] = mode_counts.get(mode, 0) + 1
            source = j.get("source", "N/A")
            source_counts[source] = source_counts.get(source, 0) + 1

            if mode == "Remoto":
                remote_count += 1

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total ofertas", len(jobs))
        m2.metric("% Remoto", f"{remote_count/len(jobs)*100:.0f}%" if jobs else "0%")
        m3.metric("Salario promedio", f"{statistics.median(salaries_num):,.0f}€".replace(",", ".") if salaries_num else "N/A")
        m4.metric("Plataformas activas", len(source_counts))

        st.subheader("Ofertas por modalidad")
        st.bar_chart(pd.DataFrame(list(mode_counts.items()), columns=["Modalidad", "Ofertas"]).set_index("Modalidad"))

        st.subheader("Ofertas por plataforma")
        st.bar_chart(pd.DataFrame(list(source_counts.items()), columns=["Plataforma", "Ofertas"]).set_index("Plataforma"))

        if salaries_num:
            st.subheader("Distribución salarial")
            st.bar_chart(pd.Series(salaries_num).describe())

# --- Seleccionar ejecución ---
st.header("📋 Ver ejecución anterior")
if len(runs) > 1:
    run_ids = [r.get("run_id", "?") for r in runs]
    selected = st.selectbox("Seleccionar ejecución", run_ids)
    selected_run = next((r for r in runs if r.get("run_id") == selected), None)
    if selected_run:
        st.json(selected_run.get("scraper_stats", {}))
else:
    st.info("Solo hay una ejecución registrada.")
