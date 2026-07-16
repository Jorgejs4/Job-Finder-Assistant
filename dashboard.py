#!/usr/bin/env python3
"""
Dashboard interactivo para el Job Scraper Assistant.
Ejecutar con: streamlit run dashboard.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st
import pandas as pd
import json
from datetime import datetime
from utils.results import ResultsManager
import config

st.set_page_config(
    page_title="Job Scraper Dashboard",
    page_icon="🔍",
    layout="wide",
)

RESULTS_DIR = os.path.join(Path(__file__).resolve().parent, "results")
rm = ResultsManager(results_dir=RESULTS_DIR)

st.title("🔍 Job Scraper Dashboard")
st.caption(f"Última carga: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

# --- Cargar datos ---
runs = rm.load_all_runs()
history = rm.load_history()

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
    # Contar por estado
    status_counts = {}
    for status in config.APPLICATION_STATUSES:
        count = len([j for j in jobs if j.get("status") == status])
        status_counts[status] = count

    # Mostrar como métricas en fila
    status_cols = st.columns(len(config.APPLICATION_STATUSES))
    for i, status in enumerate(config.APPLICATION_STATUSES):
        status_cols[i].metric(status, status_counts.get(status, 0))

    # Barra de progreso visual
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

# --- Historial ---
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

    # Filtros
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
else:
    st.info("No se encontraron ofertas en esta ejecución.")

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
